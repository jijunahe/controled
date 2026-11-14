"""Escena que la simulación dibuja: el horario en curso o la configuración activa."""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import LedConfiguration
from app.presets_catalog import PRESET_CATALOG
from app.services.lora_air import color_for_editor
from app.services.schedule import is_paused, load_schedule
from app.services.schedule_clock import as_time, clock_now, interval_covers

_NAMES = {preset_id: name for preset_id, name, _kind in PRESET_CATALOG}
_VISUALS = Path(__file__).resolve().parent.parent / "data" / "preset_visuals.json"


@lru_cache(maxsize=1)
def _visuals() -> dict[str, Any]:
    if not _VISUALS.exists():
        return {}
    loaded = json.loads(_VISUALS.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _preset_name(preset_id: int) -> str:
    return _NAMES.get(preset_id, f"Preset {preset_id}")


def _off(source: str, detail: str) -> dict[str, Any]:
    now = clock_now()
    return {
        "mode": "off",
        "source": source,
        "name": "Apagado",
        "detail": detail,
        "clock": now.strftime("%H:%M:%S"),
        "now": time.time(),
        "leds": 98,
        "bri": 0,
        "kind": "segments",
        "segments": [],
        "steps": [],
        "presets": {},
    }


def _color_segments(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    state = color_for_editor(payload) if "z" in payload and not isinstance(payload.get("seg"), list) else payload
    raw = state.get("seg") if isinstance(state, dict) else None
    segments: list[dict[str, Any]] = []
    leds = 98
    if isinstance(raw, list):
        for seg in raw:
            if not isinstance(seg, dict) or seg.get("on") is False:
                continue
            start = int(seg.get("start") or 0)
            stop = int(seg.get("stop") or 0)
            if stop <= start:
                continue
            cols = []
            for col in (seg.get("col") or [])[:3]:
                if isinstance(col, list) and len(col) >= 3:
                    cols.append([int(col[0]), int(col[1]), int(col[2])])
            if not cols:
                cols = [[255, 255, 255]]
            leds = max(leds, stop)
            segments.append(
                {
                    "a": start,
                    "b": stop,
                    "fx": int(seg.get("fx") or 0),
                    "sx": int(seg.get("sx") or 128),
                    "col": cols,
                }
            )
    bri = state.get("bri", 160) if isinstance(state, dict) else 160
    if isinstance(bri, bool) or not isinstance(bri, int):
        bri = 160
    return segments, max(1, min(leds, 600)), max(0, min(bri, 255))


def _playlist_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("steps")
    if not isinstance(raw, list):
        return []
    steps = []
    for step in raw:
        if not isinstance(step, dict):
            continue
        preset = step.get("playlist")
        seconds = step.get("seg", step.get("seconds", 10))
        if isinstance(preset, bool) or not isinstance(preset, int):
            continue
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1:
            seconds = 10
        steps.append({"id": preset, "seconds": seconds, "name": _preset_name(preset)})
    return steps


def _used_presets(roots: list[int]) -> dict[str, Any]:
    visuals = _visuals()
    pending = list(roots)
    seen: set[str] = set()
    while pending:
        preset_id = pending.pop()
        key = str(preset_id)
        if key in seen or key not in visuals:
            continue
        seen.add(key)
        item = visuals[key]
        for child in item.get("pl") or []:
            if isinstance(child, list) and child:
                pending.append(int(child[0]))
    selected: dict[str, Any] = {}
    for key in seen:
        item = visuals[key]
        if "pl" in item:
            selected[key] = {
                "playlist": [
                    {"id": int(child[0]), "seconds": int(child[1]), "name": _preset_name(int(child[0]))}
                    for child in item["pl"]
                    if isinstance(child, list) and len(child) >= 2
                ]
            }
        else:
            selected[key] = {"seg": item.get("seg") or [], "bri": int(item.get("bri") or 160)}
    return selected


def _from_config(config: LedConfiguration, source: str, detail: str) -> dict[str, Any]:
    now = clock_now()
    payload = config.payload_json if isinstance(config.payload_json, dict) else {}
    base = {
        "mode": "run",
        "source": source,
        "name": config.name,
        "detail": detail,
        "clock": now.strftime("%H:%M:%S"),
        "now": time.time(),
        "id": config.id,
    }
    if config.config_type == "static" or (isinstance(payload.get("seg"), list) and "steps" not in payload):
        try:
            segments, leds, bri = _color_segments(payload)
        except (ValueError, TypeError):
            segments, leds, bri = [], 98, 0
        base.update(
            {
                "leds": leds,
                "bri": bri,
                "kind": "segments",
                "segments": segments,
                "steps": [],
                "presets": {},
            }
        )
        return base
    steps = _playlist_steps(payload)
    base.update(
        {
            "leds": 99,
            "bri": 160,
            "kind": "sequence",
            "segments": [],
            "steps": steps,
            "presets": _used_presets([step["id"] for step in steps]),
        }
    )
    return base


def _matching_config(schedule) -> LedConfiguration | None:
    now = clock_now()
    enabled = [item for item in schedule.intervals if item.enabled]
    for interval in sorted(enabled, key=lambda item: item.id):
        days = {int(day.weekday) for day in interval.days}
        if interval_covers(as_time(interval.start_time), as_time(interval.end_time), now, days):
            return interval.configuration
    return None


def current_scene(db: Session) -> dict[str, Any]:
    try:
        paused = is_paused(db)
        schedule = load_schedule(db)
    except SQLAlchemyError:
        db.rollback()
        paused = False
        schedule = None

    if paused:
        return _off("Apagado", "Apagado manual. El horario sigue en pausa.")

    if schedule is not None and schedule.enabled:
        enabled = [item for item in schedule.intervals if item.enabled]
        if enabled:
            config = _matching_config(schedule)
            if config is None:
                return _off("Horario", "Fuera de horario. Las luces están apagadas.")
            return _from_config(config, "Horario", "Este es el horario que está en curso.")

    config = (
        db.query(LedConfiguration)
        .filter(LedConfiguration.status == 1)
        .order_by(LedConfiguration.updated_at.desc())
        .first()
    )
    if config is None:
        return _off("Efecto activo", "No hay una configuración activa.")
    return _from_config(config, "Efecto activo", "No hay un horario en esta hora. Manda la configuración activa.")
