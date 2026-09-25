"""Cliente HTTP hacia la API JSON de WLED."""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from settings import Settings

logger = logging.getLogger("orchestrator.wled")


class WledClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )

    def resolve_ip(self, device_ip: Optional[str]) -> str:
        return (device_ip or self.settings.wled_default_ip).strip()

    def post_state(self, ip: str, state: dict[str, Any]) -> tuple[bool, Optional[int], str]:
        """
        Envía estado a http://<ip>/json/state.
        Retorna (ok, http_status, mensaje).
        """
        url = f"http://{ip}/json/state"
        if self.settings.dry_run:
            logger.info("[DRY_RUN] POST %s → %s", url, state)
            return True, 200, "dry_run"

        try:
            response = self.session.post(
                url,
                json=state,
                timeout=self.settings.wled_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                logger.info("WLED OK %s status=%s", url, response.status_code)
                return True, response.status_code, "ok"
            msg = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error("WLED error %s — %s", url, msg)
            return False, response.status_code, msg
        except requests.RequestException as exc:
            msg = str(exc)
            logger.error("WLED unreachable %s — %s", url, msg)
            return False, None, msg
