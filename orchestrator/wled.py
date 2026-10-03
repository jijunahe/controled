"""Cliente HTTP hacia la API JSON de WLED / TTGO (opcionalmente cifrada)."""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from settings import Settings
from wled_aes import build_lora_forward_body, prepare_http_body

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
        Envía estado a http://<ip><WLED_JSON_PATH>.
        Con WLED_AES_KEY: body = {"aes":"<base64 0xA1|nonce|ct|tag>"}.
        Retorna (ok, http_status, mensaje).
        """
        path = self.settings.wled_json_path
        if not path.startswith("/"):
            path = "/" + path
        url = f"http://{ip}{path}"

        gateway = ip in self.settings.lora_gateway_ips
        try:
            if gateway:
                body = build_lora_forward_body(state, self.settings.wled_aes_key)
            else:
                body = prepare_http_body(state, self.settings.wled_aes_key)
        except ValueError as exc:
            logger.error("Payload inválido para TTGO/WLED: %s", exc)
            return False, None, str(exc)

        aes_on = self.settings.wled_aes_key is not None
        if self.settings.dry_run:
            preview = body if not aes_on else {"aes": f"<{len(body.get('aes', ''))} b64 chars>"}
            logger.info(
                "[DRY_RUN] POST %s aes=%s → %s",
                url,
                aes_on,
                preview,
            )
            return True, 200, "dry_run"

        try:
            response = self.session.post(
                url,
                json=body,
                timeout=self.settings.wled_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                logger.info(
                    "WLED OK %s status=%s aes=%s",
                    url,
                    response.status_code,
                    aes_on,
                )
                return True, response.status_code, "ok"
            msg = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error("WLED error %s — %s", url, msg)
            return False, response.status_code, msg
        except requests.RequestException as exc:
            msg = str(exc)
            logger.error("WLED unreachable %s — %s", url, msg)
            return False, None, msg
