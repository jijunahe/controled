"""Repite la configuración activa y envía cada paquete por LoRa."""

from __future__ import annotations

import json
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


def is_playlist_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("steps"), list):
        return True
    return "playlist" in payload and "z" not in payload and not isinstance(payload.get("seg"), list)


def shared_clock() -> int:
    # Mismo reloj de 32 bits para todas las TTGO. WLED hace now = millis() + timebase
    # con timebase = tb - millis(), así que al aplicar el paquete todas quedan en tb.
    return int(time.time() * 1000) & 0xFFFFFFFF


def _every_seconds(payload: dict[str, Any]) -> int:
    every = payload.get("every", 5) if isinstance(payload, dict) else 5
    if isinstance(every, bool) or not isinstance(every, int) or not 1 <= every <= 3600:
        return 5
    return every


class ConfigRunner:
    def __init__(self, db: Database, lora: LoRaLink) -> None:
        self.db = db
        self.lora = lora

    def apply(self, config: ActiveConfig, still) -> bool:
        logger.info("Configuración #%s '%s' en bucle", config.id, config.name)
        cycle = 0
        while still():
            payload = self.db.fetch_payload(config.id)
            if payload is None:
                logger.info("Configuración #%s ya no está", config.id)
                return False
            cycle += 1
            if is_playlist_payload(payload):
                if not self._run_playlist_cycle(config, payload, cycle, still):
                    return False
                continue
            if not self._send_color(config, payload, cycle, still):
                return False
        logger.info("Configuración #%s detenida", config.id)
        return False

    def _run_playlist_cycle(self, config: ActiveConfig, payload: dict[str, Any], cycle: int, still) -> bool:
        try:
            steps = playlist_steps(payload)
        except LoRaLinkError as exc:
            logger.error("Secuencia inválida #%s: %s", config.id, exc)
            self.db.mark_failed_and_release(config, http_status=None, error_message=str(exc))
            self._sleep(2, still, sync=False)
            return False

        logger.info("Secuencia #%s ciclo %s, %s pasos", config.id, cycle, len(steps))
        for index, step in enumerate(steps, start=1):
            if not still():
                logger.info("Secuencia #%s detenida", config.id)
                return False
            packet = {"playlist": step["playlist"], "tb": shared_clock()}
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
                if not self._sleep(2, still, sync=False):
                    return False
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
            if not self._sleep(step["seg"], still, sync=True):
                return False
        return True

    def _send_color(self, config: ActiveConfig, payload: dict[str, Any], cycle: int, still) -> bool:
        if not still():
            return False
        if not isinstance(payload, dict):
            self.db.mark_failed_and_release(
                config, http_status=None, error_message="el efecto de color no es un objeto"
            )
            return False
        try:
            stamped = dict(payload)
            stamped["tb"] = shared_clock()
            self.lora.send_payload(stamped)
        except LoRaLinkError as exc:
            logger.warning("Fallo LoRa #%s ciclo %s: %s", config.id, cycle, exc)
            self._sleep(2, still, sync=False)
            return True
        every = _every_seconds(payload)
        logger.info("LoRa #%s ciclo %s color %s bytes, repite en %ss", config.id, cycle, len(json.dumps(payload, separators=(',', ':'))), every)
        return self._sleep(every, still, sync=True)

    def _sleep(self, seconds: int, still, sync: bool = False) -> bool:
        end = time.monotonic() + max(0, seconds)
        next_sync = time.monotonic() + 5
        while time.monotonic() < end:
            if not still():
                return False
            if sync and time.monotonic() >= next_sync and end - time.monotonic() > 1:
                try:
                    self.lora.send_payload({"tb": shared_clock()})
                except LoRaLinkError as exc:
                    logger.warning("Reloj LoRa no enviado: %s", exc)
                next_sync = time.monotonic() + 5
            time.sleep(min(0.5, max(0.05, end - time.monotonic())))
        return still()
