"""Envío rápido de estados al Gledopto WLED (modo musical)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from app.config import Settings

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
        """
        Acepta:
          - state completo WLED: {"state": {...}} o claves on/bri/seg
          - frame ligero: {"bri": 180, "col": [r,g,b], "fx": 0, "on": true}
        """
        if isinstance(frame.get("state"), dict):
            return frame["state"]

        if any(k in frame for k in ("seg", "on", "bri", "ps", "pl")) and "col" not in frame:
            return {k: v for k, v in frame.items() if k not in {"type", "device_id", "source"}}

        bri = int(frame.get("bri", 128))
        bri = max(1, min(255, bri))
        fx = int(frame.get("fx", 0))
        sx = int(frame.get("sx", 128))
        ix = int(frame.get("ix", 128))
        on = bool(frame.get("on", True))
        col = frame.get("col", [255, 0, 0])
        if not isinstance(col, (list, tuple)) or len(col) < 3:
            col = [255, 0, 0]
        r, g, b = (int(col[0]) % 256, int(col[1]) % 256, int(col[2]) % 256)
        return {
            "on": on,
            "bri": bri,
            "transition": int(frame.get("transition", 0)),
            "seg": [
                {
                    "id": 0,
                    "fx": fx,
                    "sx": sx,
                    "ix": ix,
                    "col": [[r, g, b], [0, 0, 0], [0, 0, 0]],
                }
            ],
        }

    async def post_state(
        self, ip: str, state: dict[str, Any], *, force: bool = False
    ) -> tuple[bool, Optional[int], str, bool]:
        """
        Retorna (ok, http_status, mensaje, throttled).
        throttled=True → se omitió el envío por rate-limit (no es error).
        """
        if not force and not self._throttle_ok():
            return True, None, "throttled", True

        url = f"http://{ip}/json/state"
        if self.settings.wled_dry_run:
            logger.debug("[DRY_RUN] POST %s → %s", url, state)
            return True, 200, "dry_run", False

        try:
            response = await self._client.post(url, json=state)
            if 200 <= response.status_code < 300:
                return True, response.status_code, "ok", False
            return False, response.status_code, response.text[:200], False
        except httpx.HTTPError as exc:
            logger.warning("WLED error %s: %s", url, exc)
            return False, None, str(exc), False
