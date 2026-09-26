"""Ejecución de payloads estáticos y secuencias temporizadas (multi-dispositivo)."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from db import ActiveConfig, Database
from wled import WledClient

logger = logging.getLogger("orchestrator.runner")

_META_KEYS = {"steps", "loop", "mode", "repeat", "name"}


def extract_wled_state(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in _META_KEYS}


def normalize_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
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

    def _post_all(
        self, config: ActiveConfig, state: dict[str, Any]
    ) -> tuple[bool, Optional[int], str]:
        ips = config.device_ips or [self.wled.resolve_ip(None)]
        errors: list[str] = []
        last_status: Optional[int] = 200

        def _one(ip: str) -> tuple[str, bool, Optional[int], str]:
            ok, http_status, msg = self.wled.post_state(ip, state)
            return ip, ok, http_status, msg

        with ThreadPoolExecutor(max_workers=max(1, len(ips))) as pool:
            futures = [pool.submit(_one, ip) for ip in ips]
            for fut in as_completed(futures):
                ip, ok, http_status, msg = fut.result()
                if http_status is not None:
                    last_status = http_status
                if not ok:
                    errors.append(f"{ip}: {msg}")
                    self.db.log_step_error(
                        config,
                        http_status=http_status,
                        error_message=f"{ip}: {msg}",
                        payload_snapshot=state,
                    )

        if errors:
            return False, last_status, "; ".join(errors)
        return True, last_status, "ok"

    def apply(self, config: ActiveConfig) -> bool:
        try:
            steps = normalize_steps(config.payload_json)
        except ValueError as exc:
            logger.error("Payload inválido #%s: %s", config.id, exc)
            self.db.mark_failed_and_release(
                config, http_status=None, error_message=str(exc)
            )
            return True

        loop = should_loop(config.payload_json, config.config_type)
        logger.info(
            "Aplicando #%s '%s' type=%s steps=%s loop=%s → %s",
            config.id,
            config.name,
            config.config_type,
            len(steps),
            loop,
            ", ".join(config.device_ips) or self.wled.resolve_ip(None),
        )

        cycle = 0
        while True:
            cycle += 1
            for idx, step in enumerate(steps):
                if not self.db.is_still_active(config.id):
                    logger.info("Config #%s interrumpida en paso %s", config.id, idx)
                    return False

                ok, http_status, msg = self._post_all(config, step["state"])
                if not ok:
                    if loop:
                        logger.warning(
                            "Fallo de red en secuencia #%s; reintento en próximo poll: %s",
                            config.id,
                            msg,
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
