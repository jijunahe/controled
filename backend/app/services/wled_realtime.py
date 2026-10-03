"""Envío rápido de estados al WLED/TTGO (modo musical, opcional AES)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from app.config import Settings
from app.services.wled_aes import parse_aes_key_hex, prepare_http_body

logger = logging.getLogger("controled.wled_realtime")


class WledRealtimeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.wled_timeout_seconds)
        self._last_sent_at = 0.0
        self._min_interval = max(
            1.0 / max(settings.music_max_fps, 1.0),
            settings.music_min_interval_ms / 1000.0,
        )
        self._aes_key = parse_aes_key_hex(settings.wled_aes_key or None)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _throttle_ok(self) -> bool:
        now = time.monotonic()
        if now - self._last_sent_at < self._min_interval:
            return False
        self._last_sent_at = now
        return True

    @staticmethod
    def frame_to_state(frame: dict[str, Any]) -> dict[str, Any]:
        if isinstance(frame.get("state"), dict):
            return frame["state"]

        if any(k in frame for k in ("seg", "on", "bri", "ps", "pl")) and "col" not in frame:
            return {
                k: v
                for k, v in frame.items()
                if k not in {"type", "device_id", "source", "transition"}
            }

        bri = int(frame.get("bri", 128))
        bri = max(0, min(255, bri))
        fx = int(frame.get("fx", 0))
        sx = int(frame.get("sx", 128))
        on = bool(frame.get("on", True))
        col = frame.get("col", [255, 0, 0])
        if not isinstance(col, (list, tuple)) or len(col) < 3:
            col = [255, 0, 0]
        r, g, b = (int(col[0]) % 256, int(col[1]) % 256, int(col[2]) % 256)
        # Contrato TTGO: un color principal basta; máx. 3 en col
        return {
            "on": on,
            "bri": bri,
            "seg": [{"id": 0, "fx": fx, "sx": sx, "col": [[r, g, b]]}],
        }

    async def post_state(
        self, ip: str, state: dict[str, Any], *, force: bool = False
    ) -> tuple[bool, Optional[int], str, bool]:
        if not force and not self._throttle_ok():
            return True, None, "throttled", True

        path = self.settings.wled_json_path or "/json/state"
        if not path.startswith("/"):
            path = "/" + path
        url = f"http://{ip}{path}"

        try:
            body = prepare_http_body(state, self._aes_key)
        except ValueError as exc:
            logger.warning("Payload inválido: %s", exc)
            return False, None, str(exc), False

        if self.settings.wled_dry_run:
            logger.debug(
                "[DRY_RUN] POST %s aes=%s → %s",
                url,
                self._aes_key is not None,
                body if self._aes_key is None else {"aes": "<…>"},
            )
            return True, 200, "dry_run", False

        try:
            response = await self._client.post(url, json=body)
            if 200 <= response.status_code < 300:
                return True, response.status_code, "ok", False
            return False, response.status_code, response.text[:200], False
        except httpx.HTTPError as exc:
            logger.warning("WLED error %s: %s", url, exc)
            return False, None, str(exc), False
