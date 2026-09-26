#!/usr/bin/env python3
"""
Orquestador Control LEDs — Raspberry Pi 3
Polling MySQL (status=1) → POST http://<WLED_IP>/json/state (multi-dispositivo)

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
from runner import ConfigRunner
from settings import Settings
from wled import WledClient

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


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings)
    wled = WledClient(settings)
    runner = ConfigRunner(db, wled)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "Orquestador iniciado | poll=%.1fs | WLED default=%s | dry_run=%s | multi-device=ON",
        settings.poll_interval_seconds,
        settings.wled_default_ip,
        settings.dry_run,
    )

    running: dict[int, Future] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        while _running:
            try:
                # Limpiar futures terminados
                for cid, fut in list(running.items()):
                    if fut.done():
                        try:
                            fut.result()
                        except Exception:
                            logger.exception("Worker config #%s falló", cid)
                        running.pop(cid, None)

                actives = db.fetch_all_active()
                for cfg in actives:
                    if cfg.id not in running:
                        logger.debug(
                            "Lanzando worker #%s → %s",
                            cfg.id,
                            ", ".join(cfg.device_ips),
                        )
                        running[cfg.id] = executor.submit(runner.apply, cfg)
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
