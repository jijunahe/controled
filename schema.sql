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
