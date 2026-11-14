#!/usr/bin/env python3
"""
Orquestador Control LEDs — Raspberry Pi 3
Polling MySQL (status=1) → JSON en claro por USB a la TTGO transmisora LoRa

Uso:
  cd orchestrator
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  cp .env.example .env
  python orchestrator.py
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor

from db import Database
from heartbeat import format_mac, parse_heartbeat
from lora_link import LoRaLink, LoRaLinkError
from runner import ConfigRunner
from settings import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")

_running = True


def _handle_signal(signum: int, _frame: object) -> None:
    global _running
    logger.info("Señal %s recibida; deteniendo…", signum)
    _running = False


def _hold(db: Database, config_id: int) -> bool:
    play = db.current_play()
    if play.mode == "off":
        return False
    if play.mode == "run":
        return play.config is not None and play.config.id == config_id
    return db.is_still_active(config_id)


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings)
    lora = LoRaLink(settings.lora_usb_port, settings.lora_usb_baud, settings.dry_run)
    runner = ConfigRunner(db, lora)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "Orquestador iniciado | poll=%.1fs | LoRa USB=%s | dry_run=%s",
        settings.poll_interval_seconds,
        settings.lora_usb_port,
        settings.dry_run,
    )

    running: dict[int, Future] = {}
    off_sent = 0.0
    heartbeat_at = 0.0
    with ThreadPoolExecutor(max_workers=8) as executor:
        while _running:
            try:
                if time.monotonic() - heartbeat_at >= 20:
                    heartbeat_at = time.monotonic()
                    try:
                        for frame in lora.poll_heartbeat():
                            beat = parse_heartbeat(frame)
                            if beat is None:
                                continue
                            db.record_heartbeat(beat["mac"], beat["rssi"])
                            logger.info(
                                "Bit de vida %s rssi %s",
                                format_mac(beat["mac"]),
                                beat["rssi"],
                            )
                    except LoRaLinkError as exc:
                        logger.warning("Bit de vida: %s", exc)
                for cid, fut in list(running.items()):
                    if fut.done():
                        try:
                            fut.result()
                        except Exception:
                            logger.exception("Worker config #%s falló", cid)
                        running.pop(cid, None)

                play = db.current_play()
                if play.mode == "off":
                    if time.monotonic() - off_sent >= 5:
                        try:
                            lora.send_payload({"on": False})
                            off_sent = time.monotonic()
                            logger.info("Luces apagadas (%s)", play.reason)
                        except LoRaLinkError as exc:
                            logger.warning("No se pudo apagar por LoRa: %s", exc)
                elif play.mode == "run" and play.config is not None:
                    cfg = play.config
                    if cfg.id not in running:
                        logger.info("Horario %s → #%s %s", play.reason, cfg.id, cfg.name)
                        running[cfg.id] = executor.submit(
                            runner.apply, cfg, lambda cid=cfg.id: _hold(db, cid)
                        )
                else:
                    for cfg in db.fetch_all_active():
                        if cfg.id not in running:
                            logger.debug(
                                "Lanzando worker #%s → %s",
                                cfg.id,
                                ", ".join(cfg.device_ips),
                            )
                            running[cfg.id] = executor.submit(
                                runner.apply, cfg, lambda cid=cfg.id: _hold(db, cid)
                            )
            except Exception:
                logger.exception("Error en ciclo de orquestación")

            slept = 0.0
            interval = max(0.5, settings.poll_interval_seconds)
            while _running and slept < interval:
                time.sleep(min(0.25, interval - slept))
                slept += 0.25

    logger.info("Orquestador detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
