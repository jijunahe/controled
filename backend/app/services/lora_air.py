"""JSON compacto para LoRa. Si no cabe en 250 bytes, se empaqueta en {"z": "..."}."""

from __future__ import annotations

import base64
import json
from typing import Any

AIR_MAX = 250

_TOP_FLAGS_ON = 0x01
_TOP_FLAGS_BRI = 0x02
_TOP_FLAGS_TRANSITION = 0x04
_SEG_FX = 0x01
_SEG_SX = 0x02
_SEG_IX = 0x04
_SEG_PAL = 0x08
_SEG_COLORS = (0x10, 0x20, 0x40)


def compact_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _byte(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{label} debe ser un entero entre 0 y 255")
    return value


def _color(value: Any, label: str) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} admite solo R, G y B")
    return [_byte(channel, label) for channel in value]


def _clean_segment(segment: Any, index: int) -> dict[str, Any]:
    if not isinstance(segment, dict):
        raise ValueError(f"segmento {index} inválido")
    unknown = set(segment) - {"id", "fx", "sx", "ix", "pal", "col", "start", "stop"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"segmento {index}: quita propiedades ({names})")
    clean: dict[str, Any] = {"id": _byte(segment.get("id", 0), f"segmento {index}: id")}
    if "start" in segment or "stop" in segment:
        start = segment.get("start")
        stop = segment.get("stop")
        if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start <= 65534:
            raise ValueError(f"segmento {index}: desde debe ser un LED entre 0 y 65534")
        if isinstance(stop, bool) or not isinstance(stop, int) or not 1 <= stop <= 65535:
            raise ValueError(f"segmento {index}: hasta debe ser mayor que desde")
        if stop <= start:
            raise ValueError(f"segmento {index}: el último LED debe quedar después del primero")
        clean["start"] = start
        clean["stop"] = stop
    for key in ("fx", "sx", "ix", "pal"):
        if key in segment:
            clean[key] = _byte(segment[key], f"segmento {index}: {key}")
    if "col" in segment:
        colors = segment["col"]
        if not isinstance(colors, list) or not colors or len(colors) > 3:
            raise ValueError(f"segmento {index}: el color admite hasta 3 RGB")
        clean["col"] = [_color(color, f"segmento {index}: color") for color in colors]
    return clean


def _clean_state(payload: dict[str, Any]) -> dict[str, Any]:
    unknown = set(payload) - {"every", "on", "bri", "transition", "seg", "z"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"El efecto tiene propiedades que no caben en el paquete ({names}). Quítalas.")
    state: dict[str, Any] = {}
    if "on" in payload:
        if not isinstance(payload["on"], bool):
            raise ValueError("on debe ser true o false")
        state["on"] = payload["on"]
    if "bri" in payload:
        state["bri"] = _byte(payload["bri"], "el brillo")
    if "transition" in payload:
        transition = payload["transition"]
        if isinstance(transition, bool) or not isinstance(transition, int) or not 0 <= transition <= 65535:
            raise ValueError("transition debe ser un entero entre 0 y 65535")
        state["transition"] = transition
    if "seg" in payload:
        segments = payload["seg"]
        if not isinstance(segments, list) or not segments:
            raise ValueError("el efecto necesita al menos un segmento")
        if len(segments) > 32:
            raise ValueError("el efecto admite como máximo 32 segmentos")
        state["seg"] = [_clean_segment(segment, index) for index, segment in enumerate(segments, start=1)]
    if not state:
        raise ValueError("el efecto no tiene propiedades")
    return state


def pack_state(state: dict[str, Any]) -> bytes:
    """Binario versión 1. El receptor arma con esto el JSON de WLED."""
    flags = 0
    tail = bytearray()
    if "on" in state:
        flags |= _TOP_FLAGS_ON
        tail.append(1 if state["on"] else 0)
    if "bri" in state:
        flags |= _TOP_FLAGS_BRI
        tail.append(state["bri"])
    if "transition" in state:
        flags |= _TOP_FLAGS_TRANSITION
        tail.append(state["transition"] & 0xFF)
        tail.append((state["transition"] >> 8) & 0xFF)
    body = bytearray((1, flags))
    body += tail
    segments = state.get("seg") or []
    body.append(len(segments))
    for segment in segments:
        seg_flags = 0
        fields = bytearray()
        if "fx" in segment:
            seg_flags |= _SEG_FX
            fields.append(segment["fx"])
        if "sx" in segment:
            seg_flags |= _SEG_SX
            fields.append(segment["sx"])
        if "ix" in segment:
            seg_flags |= _SEG_IX
            fields.append(segment["ix"])
        if "pal" in segment:
            seg_flags |= _SEG_PAL
            fields.append(segment["pal"])
        for bit, color in zip(_SEG_COLORS, segment.get("col") or []):
            seg_flags |= bit
            fields.extend(color)
        if "start" in segment and "stop" in segment:
            seg_flags |= 0x80
            fields.append(segment["start"] & 0xFF)
            fields.append((segment["start"] >> 8) & 0xFF)
            fields.append(segment["stop"] & 0xFF)
            fields.append((segment["stop"] >> 8) & 0xFF)
        body.append(segment["id"])
        body.append(seg_flags)
        body += fields
    return bytes(body)


def unpack_state(data: bytes) -> dict[str, Any]:
    if len(data) < 3 or data[0] != 1 or data[1] & 0xF8:
        raise ValueError("paquete z inválido")
    index = 2
    flags = data[1]
    state: dict[str, Any] = {}

    def take() -> int:
        nonlocal index
        if index >= len(data):
            raise ValueError("paquete z incompleto")
        value = data[index]
        index += 1
        return value

    if flags & _TOP_FLAGS_ON:
        state["on"] = take() != 0
    if flags & _TOP_FLAGS_BRI:
        state["bri"] = take()
    if flags & _TOP_FLAGS_TRANSITION:
        state["transition"] = take() | (take() << 8)
    count = take()
    if count > 32:
        raise ValueError("paquete z inválido")
    segments: list[dict[str, Any]] = []
    for _ in range(count):
        segment: dict[str, Any] = {"id": take()}
        seg_flags = take()
        if seg_flags & _SEG_FX:
            segment["fx"] = take()
        if seg_flags & _SEG_SX:
            segment["sx"] = take()
        if seg_flags & _SEG_IX:
            segment["ix"] = take()
        if seg_flags & _SEG_PAL:
            segment["pal"] = take()
        colors = []
        for bit in _SEG_COLORS:
            if seg_flags & bit:
                colors.append([take(), take(), take()])
        if colors:
            segment["col"] = colors
        if seg_flags & 0x80:
            segment["start"] = take() | (take() << 8)
            segment["stop"] = take() | (take() << 8)
        segments.append(segment)
    if segments:
        state["seg"] = segments
    if index != len(data):
        raise ValueError("paquete z inválido")
    return state


def _every(payload: dict[str, Any]) -> int:
    every = payload.get("every", 5)
    if isinstance(every, bool) or not isinstance(every, int) or not 1 <= every <= 3600:
        raise ValueError("la repetición debe ser un entero entre 1 y 3600 segundos")
    return every


def _too_heavy(size: int) -> ValueError:
    return ValueError(
        f"El efecto programado es muy pesado ({size} bytes, máximo {AIR_MAX}). "
        "Edítalo y quita propiedades."
    )


def fit_color_packet(payload: dict[str, Any]) -> dict[str, Any]:
    """Devuelve el JSON que se guarda y se transmite, sin espacios y de hasta 250 bytes."""
    if not isinstance(payload, dict) or not payload:
        raise ValueError("el efecto de color no es válido")
    every = _every(payload)
    if "z" in payload and not any(key in payload for key in ("on", "bri", "transition", "seg")):
        packed = payload["z"]
        if not isinstance(packed, str) or not packed:
            raise ValueError("z no es válido")
        unpack_state(base64.b64decode(packed, validate=True))
        wire = {"every": every, "z": packed}
        raw = compact_json(wire)
        if len(raw) > AIR_MAX:
            raise _too_heavy(len(raw))
        return wire

    state = _clean_state(payload)
    wire = {"every": every, **state}
    raw = compact_json(wire)
    if len(raw) <= AIR_MAX:
        return wire

    wrapped = {"every": every, "z": base64.b64encode(pack_state(state)).decode("ascii")}
    packed_raw = compact_json(wrapped)
    if len(packed_raw) > AIR_MAX:
        raise _too_heavy(len(packed_raw))
    return wrapped


def color_for_editor(payload: dict[str, Any]) -> dict[str, Any]:
    """Estado editable. Si estaba empaquetado, recupera brillo, efecto y color."""
    if not isinstance(payload, dict):
        raise ValueError("el efecto de color no es válido")
    if "z" in payload and not isinstance(payload.get("seg"), list):
        state = unpack_state(base64.b64decode(payload["z"], validate=True))
        state["every"] = _every(payload)
        return state
    return payload
