-- =============================================================================
-- Migración: multi-dispositivo para Control LEDs
-- =============================================================================
USE control_leds;

-- 1) Permitir varias configs activas a la vez (independientes por dispositivo)
ALTER TABLE led_configurations
  DROP INDEX uk_led_one_active;

ALTER TABLE led_configurations
  DROP COLUMN active_marker;

-- 2) Relación N:N configuración ↔ dispositivos
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
  COMMENT='Destinos WLED de cada configuración (broadcast o individual)';

-- 3) Migrar device_id legado a la tabla puente
INSERT IGNORE INTO led_configuration_devices (configuration_id, device_id)
SELECT id, device_id
FROM led_configurations
WHERE device_id IS NOT NULL;
