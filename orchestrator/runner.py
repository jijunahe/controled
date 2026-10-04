"""Repite la secuencia de playlists y envía cada número por LoRa."""

from __future__ import annotations

import logging
import time
from typing import Any

from db import ActiveConfig, Database
from lora_link import LoRaLink, LoRaLinkError

logger = logging.getLogger("orchestrator.runner")


def playlist_steps(payload: dict[str, Any]) -> list[dict[str, int]]:
    raw_steps = payload.get("steps") if isinstance(payload, dict) else None
    if raw_steps is None and isinstance(payload, dict) and "playlist" in payload:
        raw_steps = [
            {
                "playlist": payload.get("playlist"),
                "seg": payload.get("seg", payload.get("seconds", 10)),
            }
        ]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise LoRaLinkError("la secuencia no tiene pasos")

    steps: list[dict[str, int]] = []
    for index, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            raise LoRaLinkError(f"paso {index} inválido")
        playlist = step.get("playlist")
        seconds = step.get("seg", step.get("seconds", step.get("duration_sec")))
        if isinstance(playlist, bool) or not isinstance(playlist, int) or not 1 <= playlist <= 250:
            raise LoRaLinkError(f"paso {index}: playlist fuera de rango")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1:
            raise LoRaLinkError(f"paso {index}: seg inválido")
        steps.append({"playlist": playlist, "seg": seconds})
    return steps


class ConfigRunner:
    def __init__(self, db: Database, lora: LoRaLink) -> None:
        self.db = db
        self.lora = lora

    def apply(self, config: ActiveConfig) -> bool:
        logger.info("Secuencia #%s '%s' en bucle", config.id, config.name)
        cycle = 0
        while True:
            payload = self.db.fetch_active_payload(config.id)
            if payload is None:
                logger.info("Secuencia #%s ya no está activa", config.id)
                return False
            try:
                steps = playlist_steps(payload)
            except LoRaLinkError as exc:
                logger.error("Secuencia inválida #%s: %s", config.id, exc)
                self.db.mark_failed_and_release(
                    config, http_status=None, error_message=str(exc)
                )
                return True

            cycle += 1
            logger.info("Secuencia #%s ciclo %s, %s pasos", config.id, cycle, len(steps))
            for index, step in enumerate(steps, start=1):
                if self.db.fetch_active_payload(config.id) is None:
                    logger.info("Secuencia #%s detenida", config.id)
                    return False
                packet = {"playlist": step["playlist"]}
                try:
                    self.lora.send_payload(packet)
                except LoRaLinkError as exc:
                    logger.warning(
                        "Fallo LoRa #%s ciclo %s paso %s: %s",
                        config.id,
                        cycle,
                        index,
                        exc,
                    )
                    self._sleep(config.id, 2)
                    continue
                logger.info(
                    "LoRa #%s ciclo %s paso %s/%s %s durante %ss",
                    config.id,
                    cycle,
                    index,
                    len(steps),
                    packet,
                    step["seg"],
                )
                self._sleep(config.id, step["seg"])

    def _sleep(self, config_id: int, seconds: int) -> None:
        end = time.monotonic() + max(0, seconds)
        while time.monotonic() < end:
            if not self.db.is_still_active(config_id):
                return
            time.sleep(min(0.5, max(0.05, end - time.monotonic())))
