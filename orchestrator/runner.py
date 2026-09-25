"""Ejecución de payloads estáticos y secuencias temporizadas."""

from __future__ import annotations

import logging
import time
from typing import Any

from db import ActiveConfig, Database
from wled import WledClient

logger = logging.getLogger("orchestrator.runner")

_META_KEYS = {"steps", "loop", "mode", "repeat", "name"}


def extract_wled_state(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in _META_KEYS}


def normalize_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Lista de pasos: [{"duration_ms": int, "state": {...}}, ...]
    """
    raw_steps = payload.get("steps")
    if isinstance(raw_steps, list) and raw_steps:
        steps: list[dict[str, Any]] = []
        for idx, step in enumerate(raw_steps):
            if not isinstance(step, dict):
                raise ValueError(f"Paso {idx} inválido")
            duration = step.get("duration_ms", step.get("duration", 1000))
            try:
                duration_ms = max(100, int(float(duration)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"duration_ms inválida en paso {idx}") from exc
            state = step.get("state")
            if state is None:
                state = extract_wled_state(step)
            if not isinstance(state, dict) or not state:
                raise ValueError(f"state vacío en paso {idx}")
            steps.append({"duration_ms": duration_ms, "state": state})
        return steps

    state = extract_wled_state(payload)
    if not state:
        raise ValueError("payload sin estado WLED utilizable")
    return [{"duration_ms": 0, "state": state}]


def should_loop(payload: dict[str, Any], config_type: str) -> bool:
    if "steps" not in payload:
        return False
    if "loop" in payload:
        return bool(payload["loop"])
    return config_type in {"sequence", "playlist"}


class ConfigRunner:
    def __init__(self, db: Database, wled: WledClient) -> None:
        self.db = db
        self.wled = wled

    def apply(self, config: ActiveConfig) -> bool:
        """
        Aplica la configuración.
        True  = completada (o liberada tras fallo definitivo).
        False = interrumpida / reintento pendiente (sigue status=1).
        """
        ip = self.wled.resolve_ip(config.device_ip)

        try:
            steps = normalize_steps(config.payload_json)
        except ValueError as exc:
            logger.error("Payload inválido #%s: %s", config.id, exc)
            self.db.mark_failed_and_release(config, http_status=None, error_message=str(exc))
            return True

        loop = should_loop(config.payload_json, config.config_type)
        logger.info(
            "Aplicando #%s '%s' type=%s steps=%s loop=%s → %s",
            config.id,
            config.name,
            config.config_type,
            len(steps),
            loop,
            ip,
        )

        cycle = 0
        while True:
            cycle += 1
            for idx, step in enumerate(steps):
                if not self.db.is_still_active(config.id):
                    logger.info("Config #%s interrumpida en paso %s", config.id, idx)
                    return False

                ok, http_status, msg = self.wled.post_state(ip, step["state"])
                if not ok:
                    self.db.log_step_error(
                        config,
                        http_status=http_status,
                        error_message=f"paso {idx}: {msg}",
                        payload_snapshot=step["state"],
                    )
                    if loop:
                        # Secuencia en bucle: dejar status=1 para reintentar luego
                        logger.warning(
                            "Fallo de red en secuencia #%s; se reintentará en el próximo ciclo de poll",
                            config.id,
                        )
                        return False
                    self.db.mark_failed_and_release(
                        config, http_status=http_status, error_message=msg
                    )
                    return True

                duration_ms = int(step["duration_ms"])
                if duration_ms > 0:
                    self._interruptible_sleep(config.id, duration_ms / 1000.0)
                    if not self.db.is_still_active(config.id):
                        logger.info("Config #%s interrumpida durante espera", config.id)
                        return False

            if not loop:
                break

            logger.debug("Secuencia #%s ciclo %s OK; repitiendo", config.id, cycle)
            if not self.db.is_still_active(config.id):
                return False

        self.db.mark_applied(config, http_status=200)
        return True

    def _interruptible_sleep(self, config_id: int, seconds: float) -> None:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if not self.db.is_still_active(config_id):
                return
            time.sleep(min(0.5, max(0.05, end - time.monotonic())))
