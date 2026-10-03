"""Configuración del orquestador (variables de entorno / .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from wled_aes import parse_aes_key_hex

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
    wled_aes_key: Optional[bytes]
    wled_json_path: str
    lora_gateway_ips: frozenset[str]

    @classmethod
    def from_env(cls) -> "Settings":
        aes_raw = os.getenv("WLED_AES_KEY", "").strip()
        aes_key = parse_aes_key_hex(aes_raw) if aes_raw else None
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
            wled_aes_key=aes_key,
            wled_json_path=os.getenv("WLED_JSON_PATH", "/json/state").strip()
            or "/json/state",
            lora_gateway_ips=frozenset(
                item.strip()
                for item in os.getenv("WLED_LORA_GATEWAY_IPS", "").split(",")
                if item.strip()
            ),
        )
