-- Bit de vida de las TTGO. La MAC es la de Wi-Fi, 12 hex sin separadores.
-- No modifica las tablas que ya existían.

CREATE TABLE IF NOT EXISTS led_heartbeats (
  mac        CHAR(12)  NOT NULL,
  last_seen  DATETIME(3) NOT NULL,
  rssi       SMALLINT  NULL,
  packets    INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (mac)
) ENGINE=InnoDB
  COMMENT='Último aviso LoRa de cada TTGO, identificado por MAC';
