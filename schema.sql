-- =============================================================================
-- CONTROL LEDS — Esquema MySQL 8
-- Dispositivo: Gledopto GL-C-016WL-D (WLED / ESP32)
-- Orquestador: Raspberry Pi 3 → polling status=1 → POST /json/state
-- =============================================================================

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE DATABASE IF NOT EXISTS control_leds
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE control_leds;

-- -----------------------------------------------------------------------------
-- Usuarios (autenticación JWT del panel / API FastAPI)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id            INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  username      VARCHAR(64)      NOT NULL,
  email         VARCHAR(255)     NOT NULL,
  password_hash VARCHAR(255)     NOT NULL COMMENT 'bcrypt/argon2 — nunca texto plano',
  full_name     VARCHAR(120)     NULL,
  is_active     TINYINT(1)       NOT NULL DEFAULT 1,
  role          ENUM('admin', 'operator', 'viewer') NOT NULL DEFAULT 'operator',
  created_at    TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_username (username),
  UNIQUE KEY uk_users_email (email),
  KEY idx_users_active (is_active)
) ENGINE=InnoDB
  COMMENT='Cuentas del panel web y API';

-- -----------------------------------------------------------------------------
-- Dispositivos WLED (IP local, p. ej. Gledopto en la LAN de la Pi)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wled_devices (
  id            INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  name          VARCHAR(100)     NOT NULL,
  ip_address    VARCHAR(45)      NOT NULL COMMENT 'IPv4/IPv6 del controlador WLED',
  mac_address   VARCHAR(17)      NULL,
  is_default    TINYINT(1)       NOT NULL DEFAULT 0,
  is_online     TINYINT(1)       NOT NULL DEFAULT 0,
  last_seen_at  TIMESTAMP        NULL,
  notes         VARCHAR(255)     NULL,
  created_at    TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_wled_devices_ip (ip_address),
  KEY idx_wled_devices_default (is_default)
) ENGINE=InnoDB
  COMMENT='Controladores WLED alcanzables desde la Raspberry Pi';

-- Garantiza como máximo un dispositivo marcado como default (MySQL 8).
-- Cuando is_default=0 → NULL (varios permitidos); cuando =1 → 1 (único).
ALTER TABLE wled_devices
  ADD COLUMN default_marker TINYINT GENERATED ALWAYS AS (
    CASE WHEN is_default = 1 THEN 1 ELSE NULL END
  ) STORED,
  ADD UNIQUE KEY uk_wled_one_default (default_marker);

-- -----------------------------------------------------------------------------
-- Configuraciones LED (tabla maestra para el orquestador)
-- status = 1 → pendiente de aplicar; status = 0 → inactiva / ya procesada
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS led_configurations (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name            VARCHAR(120) NOT NULL,
  config_type     ENUM(
                    'static',
                    'sequence',
                    'playlist',
                    'audio_reactive'
                  )            NOT NULL,
  payload_json    JSON         NOT NULL
    COMMENT 'Estado WLED: on, bri, seg[{col,fx,sx,ix,...}], etc.',
  status          TINYINT(1)   NOT NULL DEFAULT 0
    COMMENT '1 = activa/pendiente orquestador; 0 = inactiva/procesada',
  device_id       INT UNSIGNED NULL
    COMMENT 'Opcional: dispositivo destino; NULL = usar el default',
  created_by      INT UNSIGNED NULL,
  description     VARCHAR(255) NULL,
  created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  applied_at      TIMESTAMP    NULL
    COMMENT 'Marca de tiempo cuando el orquestador propagó al WLED',
  PRIMARY KEY (id),
  KEY idx_led_cfg_status (status),
  KEY idx_led_cfg_type (config_type),
  KEY idx_led_cfg_created (created_at),
  KEY idx_led_cfg_device (device_id),
  CONSTRAINT fk_led_cfg_device
    FOREIGN KEY (device_id) REFERENCES wled_devices (id)
    ON UPDATE CASCADE ON DELETE SET NULL,
  CONSTRAINT fk_led_cfg_user
    FOREIGN KEY (created_by) REFERENCES users (id)
    ON UPDATE CASCADE ON DELETE SET NULL,
  CONSTRAINT chk_led_cfg_status CHECK (status IN (0, 1)),
  CONSTRAINT chk_led_cfg_payload_object CHECK (JSON_TYPE(payload_json) = 'OBJECT')
) ENGINE=InnoDB
  COMMENT='Cola maestra: el orquestador aplica registros con status=1';

-- Destinos N:N (una config puede ir a varios Gledopto)
CREATE TABLE IF NOT EXISTS led_configuration_devices (
  configuration_id INT UNSIGNED NOT NULL,
  device_id        INT UNSIGNED NOT NULL,
  PRIMARY KEY (configuration_id, device_id),
  KEY idx_lcd_device (device_id),
  CONSTRAINT fk_lcd_configuration
    FOREIGN KEY (configuration_id) REFERENCES led_configurations (id)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_lcd_device
    FOREIGN KEY (device_id) REFERENCES wled_devices (id)
    ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB
  COMMENT='Destinos WLED de cada configuración';

-- (Migración 002 eliminó uk_led_one_active para permitir configs
--  independientes en paralelo sobre distintos dispositivos.)


-- -----------------------------------------------------------------------------
-- Historial / auditoría de aplicaciones y cambios de estado
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS led_configuration_logs (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  configuration_id  INT UNSIGNED    NOT NULL,
  device_id         INT UNSIGNED    NULL,
  action            ENUM(
                      'created',
                      'updated',
                      'activated',
                      'deactivated',
                      'applied',
                      'apply_failed',
                      'deleted'
                    )               NOT NULL,
  previous_status   TINYINT(1)      NULL,
  new_status        TINYINT(1)      NULL,
  http_status       SMALLINT        NULL COMMENT 'Código HTTP de WLED al aplicar',
  error_message     VARCHAR(500)    NULL,
  payload_snapshot  JSON            NULL COMMENT 'Copia del payload enviado',
  actor             VARCHAR(64)     NULL
    COMMENT 'api|orchestrator|websocket|system|<username>',
  created_at        TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_led_logs_cfg (configuration_id),
  KEY idx_led_logs_action (action),
  KEY idx_led_logs_created (created_at),
  CONSTRAINT fk_led_logs_cfg
    FOREIGN KEY (configuration_id) REFERENCES led_configurations (id)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_led_logs_device
    FOREIGN KEY (device_id) REFERENCES wled_devices (id)
    ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB
  COMMENT='Trazabilidad de activaciones y propagación al WLED';

-- -----------------------------------------------------------------------------
-- Sesiones de modo musical / audio-reactivo (WebSockets)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audio_sessions (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id         INT UNSIGNED    NULL,
  device_id       INT UNSIGNED    NULL,
  session_token   VARCHAR(64)     NOT NULL,
  source          ENUM('websocket', 'mic_wled', 'playlist_sim') NOT NULL DEFAULT 'websocket',
  is_active       TINYINT(1)      NOT NULL DEFAULT 1,
  started_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at        TIMESTAMP       NULL,
  frames_sent     INT UNSIGNED    NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_audio_session_token (session_token),
  KEY idx_audio_sessions_active (is_active),
  CONSTRAINT fk_audio_user
    FOREIGN KEY (user_id) REFERENCES users (id)
    ON UPDATE CASCADE ON DELETE SET NULL,
  CONSTRAINT fk_audio_device
    FOREIGN KEY (device_id) REFERENCES wled_devices (id)
    ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB
  COMMENT='Sesiones de control reactivo en tiempo real';

-- -----------------------------------------------------------------------------
-- Datos semilla mínimos (desarrollo)
-- Contraseña del admin: cambiar en producción.
-- Hash bcrypt de "admin123" (cost 12) — se regenerará desde FastAPI en fase 2.
-- -----------------------------------------------------------------------------
INSERT INTO users (username, email, password_hash, full_name, role)
VALUES (
  'admin',
  'admin@controled.local',
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.G2oQ.YqKxqKxqK',
  'Administrador',
  'admin'
)
ON DUPLICATE KEY UPDATE username = username;

INSERT INTO wled_devices (name, ip_address, is_default, notes)
VALUES (
  'Gledopto GL-C-016WL-D',
  '192.168.1.100',
  1,
  'Actualizar IP local real del controlador WLED'
)
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- Ejemplo de configuración estática inactiva (referencia de payload WLED)
INSERT INTO led_configurations (name, config_type, payload_json, status, device_id, created_by, description)
SELECT
  'Rojo estático demo',
  'static',
  JSON_OBJECT(
    'on', TRUE,
    'bri', 128,
    'seg', JSON_ARRAY(
      JSON_OBJECT(
        'id', 0,
        'fx', 0,
        'sx', 128,
        'ix', 128,
        'col', JSON_ARRAY(
          JSON_ARRAY(255, 0, 0),
          JSON_ARRAY(0, 0, 0),
          JSON_ARRAY(0, 0, 0)
        )
      )
    )
  ),
  0,
  d.id,
  u.id,
  'Payload de ejemplo compatible con POST /json/state'
FROM wled_devices d
CROSS JOIN users u
WHERE d.is_default = 1 AND u.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM led_configurations WHERE name = 'Rojo estático demo'
  )
LIMIT 1;

-- Horario y apagado manual. La misma definición está en schema_schedule.sql
-- para bases que ya existen.

CREATE TABLE IF NOT EXISTS led_schedules (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name       VARCHAR(120) NOT NULL,
  enabled    TINYINT(1)   NOT NULL DEFAULT 1,
  created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB
  COMMENT='Horario de encendido. enabled=0 vuelve al modo manual';

CREATE TABLE IF NOT EXISTS led_schedule_intervals (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  schedule_id      INT UNSIGNED NOT NULL,
  configuration_id INT UNSIGNED NOT NULL,
  start_time       TIME         NOT NULL,
  end_time         TIME         NOT NULL,
  enabled          TINYINT(1)   NOT NULL DEFAULT 1,
  created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_sched_interval_schedule (schedule_id),
  KEY idx_sched_interval_config (configuration_id),
  CONSTRAINT fk_sched_interval_schedule
    FOREIGN KEY (schedule_id) REFERENCES led_schedules (id)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_sched_interval_config
    FOREIGN KEY (configuration_id) REFERENCES led_configurations (id)
    ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB
  COMMENT='Cada intervalo enciende una configuración ya guardada';

CREATE TABLE IF NOT EXISTS led_schedule_interval_days (
  interval_id INT UNSIGNED NOT NULL,
  weekday     TINYINT      NOT NULL COMMENT '0=lunes ... 6=domingo',
  PRIMARY KEY (interval_id, weekday),
  CONSTRAINT fk_sched_day_interval
    FOREIGN KEY (interval_id) REFERENCES led_schedule_intervals (id)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT chk_sched_weekday CHECK (weekday BETWEEN 0 AND 6)
) ENGINE=InnoDB
  COMMENT='Días en que corre el intervalo';

CREATE TABLE IF NOT EXISTS led_power_override (
  id         TINYINT   NOT NULL,
  paused     TINYINT(1) NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT chk_power_single CHECK (id = 1),
  CONSTRAINT chk_power_paused CHECK (paused IN (0, 1))
) ENGINE=InnoDB
  COMMENT='paused=1 apaga las luces y frena el horario hasta Encender';

INSERT INTO led_power_override (id, paused)
VALUES (1, 0)
ON DUPLICATE KEY UPDATE id = id;

-- Catálogo de presets de las TTGO. El id es el número que viaja en {"playlist": N}.
-- No modifica las tablas que ya existían.

CREATE TABLE IF NOT EXISTS led_presets (
  id   SMALLINT UNSIGNED NOT NULL,
  name VARCHAR(120)      NOT NULL,
  kind VARCHAR(16)       NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT chk_led_preset_kind CHECK (kind IN ('preset', 'playlist'))
) ENGINE=InnoDB
  COMMENT='Presets WLED para elegir el efecto por nombre';

INSERT INTO led_presets (id, name, kind) VALUES
(1, 'Bandera Colombia', 'preset'),
(2, 'Barrido tricolor', 'preset'),
(3, 'Persecucion tricolor', 'preset'),
(4, 'Fundido tricolor', 'preset'),
(5, 'Arcoiris', 'preset'),
(6, 'Respiracion', 'preset'),
(7, 'Teatro', 'preset'),
(8, 'Cometa', 'preset'),
(9, 'Fuego', 'preset'),
(10, 'Destellos', 'preset'),
(11, 'Playlist', 'playlist'),
(12, 'PacMan', 'preset'),
(13, 'Tetrix', 'preset'),
(14, 'Chase', 'preset'),
(15, '01 Amber warm 1', 'preset'),
(16, '01 Amber warm 2', 'preset'),
(17, '02 Ocean teal 1', 'preset'),
(18, '02 Ocean teal 2', 'preset'),
(19, '03 Forest green 1', 'preset'),
(20, '03 Forest green 2', 'preset'),
(21, '04 Violet magenta 1', 'preset'),
(22, '04 Violet magenta 2', 'preset'),
(23, '05 Sunset coral 1', 'preset'),
(24, '05 Sunset coral 2', 'preset'),
(25, '06 Ice cyan 1', 'preset'),
(26, '06 Ice cyan 2', 'preset'),
(27, '07 Ember 1', 'preset'),
(28, '07 Ember 2', 'preset'),
(29, '08 Rose lavender 1', 'preset'),
(30, '08 Rose lavender 2', 'preset'),
(31, '09 Tropical 1', 'preset'),
(32, '09 Tropical 2', 'preset'),
(33, '10 Midnight silver 1', 'preset'),
(34, '10 Midnight silver 2', 'preset'),
(35, '11 Rainbow 1', 'preset'),
(36, '11 Rainbow 2', 'preset'),
(37, '12 Scan glow 1', 'preset'),
(38, '12 Scan glow 2', 'preset'),
(39, '13 Color chase 1', 'preset'),
(40, '13 Color chase 2', 'preset'),
(41, '14 Fireworks 1', 'preset'),
(42, '14 Fireworks 2', 'preset'),
(43, '15 Fire ember 1', 'preset'),
(44, '15 Fire ember 2', 'preset'),
(45, '16 Star sparkle 1', 'preset'),
(46, '16 Star sparkle 2', 'preset'),
(47, '17 Meteors 1', 'preset'),
(48, '17 Meteors 2', 'preset'),
(49, '18 Color waves 1', 'preset'),
(50, '18 Color waves 2', 'preset'),
(51, '19 Scanner 1', 'preset'),
(52, '19 Scanner 2', 'preset'),
(53, '20 Rain storm 1', 'preset'),
(54, '20 Rain storm 2', 'preset'),
(55, '01 Amber warm', 'playlist'),
(56, '02 Ocean teal', 'playlist'),
(57, '03 Forest green', 'playlist'),
(58, '04 Violet magenta', 'playlist'),
(59, '05 Sunset coral', 'playlist'),
(60, '06 Ice cyan', 'playlist'),
(61, '07 Ember', 'playlist'),
(62, '08 Rose lavender', 'playlist'),
(63, '09 Tropical', 'playlist'),
(64, '10 Midnight silver', 'playlist'),
(65, '11 Rainbow', 'playlist'),
(66, '12 Scan glow', 'playlist'),
(67, '13 Color chase', 'playlist'),
(68, '14 Fireworks', 'playlist'),
(69, '15 Fire ember', 'playlist'),
(70, '16 Star sparkle', 'playlist'),
(71, '17 Meteors', 'playlist'),
(72, '18 Color waves', 'playlist'),
(73, '19 Scanner', 'playlist'),
(74, '20 Rain storm', 'playlist'),
(75, 'Solid', 'preset')
ON DUPLICATE KEY UPDATE name = VALUES(name), kind = VALUES(kind);

-- Bit de vida de las TTGO. La MAC es la de Wi-Fi, 12 hex sin separadores.

CREATE TABLE IF NOT EXISTS led_heartbeats (
  mac        CHAR(12)  NOT NULL,
  last_seen  DATETIME(3) NOT NULL,
  rssi       SMALLINT  NULL,
  packets    INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (mac)
) ENGINE=InnoDB
  COMMENT='Último aviso LoRa de cada TTGO, identificado por MAC';

