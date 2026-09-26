"""Acceso MySQL del orquestador."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
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
    device_ids: list[int] = field(default_factory=list)
    device_ips: list[str] = field(default_factory=list)


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

    def _resolve_targets(
        self, conn: Connection, config_id: int, legacy_device_id: Optional[int]
    ) -> tuple[list[int], list[str]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.ip_address
                FROM led_configuration_devices lcd
                JOIN wled_devices d ON d.id = lcd.device_id
                WHERE lcd.configuration_id = %s
                ORDER BY d.id
                """,
                (config_id,),
            )
            rows = cur.fetchall()
        if rows:
            return [int(r["id"]) for r in rows], [r["ip_address"] for r in rows]

        if legacy_device_id:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, ip_address FROM wled_devices WHERE id = %s",
                    (legacy_device_id,),
                )
                row = cur.fetchone()
            if row:
                return [int(row["id"])], [row["ip_address"]]

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, ip_address FROM wled_devices
                WHERE is_default = 1
                ORDER BY id ASC LIMIT 1
                """
            )
            row = cur.fetchone()
        if row:
            return [int(row["id"])], [row["ip_address"]]

        return [], [self.settings.wled_default_ip]

    def _row_to_config(self, conn: Connection, row: dict[str, Any]) -> ActiveConfig:
        payload = row["payload_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError(f"payload_json inválido en config #{row['id']}")

        device_ids, device_ips = self._resolve_targets(
            conn, int(row["id"]), row.get("device_id")
        )
        return ActiveConfig(
            id=int(row["id"]),
            name=row["name"],
            config_type=row["config_type"],
            payload_json=payload,
            device_ids=device_ids,
            device_ips=device_ips,
        )

    def fetch_all_active(self) -> list[ActiveConfig]:
        sql = """
            SELECT id, name, config_type, payload_json, device_id
            FROM led_configurations
            WHERE status = 1
            ORDER BY updated_at ASC
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
            return [self._row_to_config(conn, row) for row in rows]

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
        device_id: Optional[int] = None,
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
                    device_id
                    if device_id is not None
                    else (config.device_ids[0] if config.device_ids else None),
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
        logger.info("Config #%s aplicada → status=0 (%s IPs)", config.id, len(config.device_ips))

    def mark_failed_and_release(
        self,
        config: ActiveConfig,
        *,
        http_status: Optional[int],
        error_message: str,
    ) -> None:
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
        device_id: Optional[int] = None,
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
                device_id=device_id,
            )
