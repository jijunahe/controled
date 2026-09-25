"""Acceso MySQL del orquestador."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generator, Optional

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from settings import Settings

logger = logging.getLogger("orchestrator.db")


@dataclass
class ActiveConfig:
    id: int
    name: str
    config_type: str
    payload_json: dict[str, Any]
    device_id: Optional[int]
    device_ip: Optional[str]


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @contextmanager
    def connection(self) -> Generator[Connection, None, None]:
        conn = pymysql.connect(
            host=self.settings.db_host,
            port=self.settings.db_port,
            user=self.settings.db_user,
            password=self.settings.db_password,
            database=self.settings.db_name,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_active(self) -> Optional[ActiveConfig]:
        sql = """
            SELECT
              c.id,
              c.name,
              c.config_type,
              c.payload_json,
              c.device_id,
              d.ip_address AS device_ip
            FROM led_configurations c
            LEFT JOIN wled_devices d ON d.id = c.device_id
            WHERE c.status = 1
            ORDER BY c.updated_at DESC
            LIMIT 1
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
        if not row:
            return None

        payload = row["payload_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError(f"payload_json inválido en config #{row['id']}")

        return ActiveConfig(
            id=int(row["id"]),
            name=row["name"],
            config_type=row["config_type"],
            payload_json=payload,
            device_id=row["device_id"],
            device_ip=row["device_ip"],
        )

    def is_still_active(self, config_id: int) -> bool:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM led_configurations WHERE id = %s",
                    (config_id,),
                )
                row = cur.fetchone()
        return bool(row and int(row["status"]) == 1)

    def _insert_log(
        self,
        conn: Connection,
        *,
        config: ActiveConfig,
        action: str,
        previous_status: Optional[int],
        new_status: Optional[int],
        http_status: Optional[int],
        error_message: Optional[str],
        payload_snapshot: Optional[dict[str, Any]] = None,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO led_configuration_logs (
                  configuration_id, device_id, action,
                  previous_status, new_status, http_status,
                  error_message, payload_snapshot, actor
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    config.id,
                    config.device_id,
                    action,
                    previous_status,
                    new_status,
                    http_status,
                    (error_message[:500] if error_message else None),
                    json.dumps(
                        payload_snapshot or config.payload_json, ensure_ascii=False
                    ),
                    "orchestrator",
                ),
            )

    def mark_applied(
        self,
        config: ActiveConfig,
        *,
        http_status: Optional[int] = 200,
    ) -> None:
        """Éxito: status → 0 y applied_at."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE led_configurations
                    SET status = 0, applied_at = %s
                    WHERE id = %s AND status = 1
                    """,
                    (datetime.utcnow(), config.id),
                )
            self._insert_log(
                conn,
                config=config,
                action="applied",
                previous_status=1,
                new_status=0,
                http_status=http_status,
                error_message=None,
            )
        logger.info("Config #%s aplicada → status=0", config.id)

    def mark_failed_and_release(
        self,
        config: ActiveConfig,
        *,
        http_status: Optional[int],
        error_message: str,
    ) -> None:
        """Fallo definitivo: libera status=0 para no bloquear la cola."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE led_configurations
                    SET status = 0
                    WHERE id = %s AND status = 1
                    """,
                    (config.id,),
                )
            self._insert_log(
                conn,
                config=config,
                action="apply_failed",
                previous_status=1,
                new_status=0,
                http_status=http_status,
                error_message=error_message,
            )
        logger.error("Config #%s falló y se liberó: %s", config.id, error_message)

    def log_step_error(
        self,
        config: ActiveConfig,
        *,
        http_status: Optional[int],
        error_message: str,
        payload_snapshot: dict[str, Any],
    ) -> None:
        with self.connection() as conn:
            self._insert_log(
                conn,
                config=config,
                action="apply_failed",
                previous_status=1,
                new_status=1,
                http_status=http_status,
                error_message=error_message,
                payload_snapshot=payload_snapshot,
            )
