"""Configuración del orquestador (variables de entorno / .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    wled_default_ip: str
    wled_timeout_seconds: float
    poll_interval_seconds: float
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_host=os.getenv("DB_HOST", "127.0.0.1"),
            db_port=int(os.getenv("DB_PORT", "3306")),
            db_user=os.getenv("DB_USER", "controled"),
            db_password=os.getenv("DB_PASSWORD", ""),
            db_name=os.getenv("DB_NAME", "control_leds"),
            wled_default_ip=os.getenv("WLED_DEFAULT_IP", "192.168.1.100"),
            wled_timeout_seconds=float(os.getenv("WLED_TIMEOUT_SECONDS", "5")),
            poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "2.5")),
            dry_run=_bool(os.getenv("DRY_RUN"), default=False),
        )
