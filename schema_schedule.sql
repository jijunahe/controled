-- Horario y apagado manual. No modifica las tablas que ya existen.

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
