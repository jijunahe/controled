"""AES-128-GCM envelope for TTGO WLED (lora_rx / Wi-Fi JSON API).

Wire format (same as firmware usermods/lora_rx):
  0xA1 | nonce(12) | ciphertext | tag(16)

HTTP body when key is configured:
  {"aes": "<base64 of frame>"}

HTTP plaintext is compact JSON for a Wi-Fi receiver.
A LoRa transmitter (WLED_LORA_GATEWAY_IPS) receives AES(MessagePack) and forwards those bytes.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AES_MAGIC = 0xA1
AES_NONCE_LEN = 12
AES_TAG_LEN = 16
# Firmware useful MessagePack max after AES overhead; for HTTP we still keep
# payloads small so the same state can be re-broadcast over LoRa later.
MAX_PLAINTEXT_BYTES = 226

_SEG_KEYS = ("id", "start", "stop", "fx", "sx", "ix", "pal", "col")
_ROOT_KEYS = ("on", "bri", "ps", "seg")


def parse_aes_key_hex(value: Optional[str]) -> Optional[bytes]:
    if value is None:
        return None
    hex_key = value.strip().replace(" ", "").lower()
    if not hex_key:
        return None
    if len(hex_key) != 32:
        raise ValueError("WLED_AES_KEY must be 32 hex characters (16 bytes)")
    try:
        return bytes.fromhex(hex_key)
    except ValueError as exc:
        raise ValueError("WLED_AES_KEY is not valid hexadecimal") from exc


def sanitize_wled_state(state: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys accepted by the TTGO LoRa JSON contract."""
    if not isinstance(state, dict):
        raise ValueError("state must be an object")

    # Unwrap {"state": {...}} when root has no LED keys
    if "state" in state and not any(k in state for k in ("on", "bri", "seg", "ps")):
        inner = state.get("state")
        if isinstance(inner, dict):
            state = inner

    out: dict[str, Any] = {}
    if "on" in state:
        out["on"] = bool(state["on"])
    if "bri" in state:
        out["bri"] = max(0, min(255, int(state["bri"])))
    if "ps" in state:
        out["ps"] = int(state["ps"])

    seg = state.get("seg")
    if isinstance(seg, list) and seg:
        clean_segs = []
        for item in seg[:5]:  # hard cap: 5 one-color segs per packet
            if not isinstance(item, dict):
                continue
            s: dict[str, Any] = {}
            if "id" in item:
                s["id"] = max(0, min(31, int(item["id"])))
            for key in ("start", "stop", "fx", "sx", "ix", "pal"):
                if key in item:
                    s[key] = int(item[key])
            col = item.get("col")
            if isinstance(col, list) and col:
                colors = []
                for c in col[:3]:
                    if isinstance(c, (list, tuple)) and len(c) >= 3:
                        colors.append(
                            [int(c[0]) % 256, int(c[1]) % 256, int(c[2]) % 256]
                        )
                if colors:
                    s["col"] = colors
            if s:
                clean_segs.append(s)
        if clean_segs:
            out["seg"] = clean_segs

    if not out:
        raise ValueError("empty WLED state after sanitize")
    return out


def _pack_int(number: int) -> bytes:
    if 0 <= number <= 127:
        return bytes([number])
    if number <= 255:
        return bytes([0xCC, number & 0xFF])
    if number <= 65535:
        return b"\xcd" + number.to_bytes(2, "big")
    raise ValueError(f"entero fuera de rango para MessagePack: {number}")


def _pack_msgpack(value: Any) -> bytes:
    if value is True:
        return b"\xc3"
    if value is False:
        return b"\xc2"
    if isinstance(value, int):
        return _pack_int(value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        if len(raw) > 31:
            raise ValueError("clave MessagePack demasiado larga")
        return bytes([0xA0 | len(raw)]) + raw
    if isinstance(value, list):
        if len(value) > 15:
            raise ValueError("arreglo MessagePack demasiado largo")
        return bytes([0x90 | len(value)]) + b"".join(_pack_msgpack(item) for item in value)
    if isinstance(value, dict):
        if len(value) > 15:
            raise ValueError("objeto MessagePack demasiado largo")
        body = b"".join(_pack_msgpack(key) + _pack_msgpack(item) for key, item in value.items())
        return bytes([0x80 | len(value)]) + body
    raise ValueError(f"tipo no soportado en MessagePack: {type(value).__name__}")


def compact_msgpack_bytes(state: dict[str, Any]) -> bytes:
    """Estado WLED ya saneado, en MessagePack. El transmisor no lo vuelve a codificar."""
    raw = _pack_msgpack(sanitize_wled_state(state))
    if len(raw) > MAX_PLAINTEXT_BYTES:
        raise ValueError(
            f"MessagePack demasiado grande para LoRa: {len(raw)} > {MAX_PLAINTEXT_BYTES}"
        )
    return raw


def build_lora_forward_body(state: dict[str, Any], key: bytes) -> dict[str, str]:
    """Trama lista para el aire: AES-128-GCM(MessagePack). El transmisor la reenvía tal cual."""
    if key is None or len(key) != 16:
        raise ValueError("el transmisor LoRa exige WLED_AES_KEY")
    frame = encrypt_frame(compact_msgpack_bytes(state), key)
    if len(frame) > 255:
        raise ValueError(f"trama LoRa de {len(frame)} bytes; el máximo es 255")
    return {"aes": base64.b64encode(frame).decode("ascii")}


def compact_json_bytes(state: dict[str, Any]) -> bytes:
    clean = sanitize_wled_state(state)
    raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_PLAINTEXT_BYTES:
        raise ValueError(
            f"payload too large for TTGO AES envelope: {len(raw)} > {MAX_PLAINTEXT_BYTES}"
        )
    return raw


def encrypt_frame(plaintext: bytes, key: bytes) -> bytes:
    if len(key) != 16:
        raise ValueError("AES key must be 16 bytes")
    nonce = secrets.token_bytes(AES_NONCE_LEN)
    aesgcm = AESGCM(key)
    # cryptography appends the 16-byte tag to the ciphertext
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, None)
    return bytes([AES_MAGIC]) + nonce + ct_and_tag


def build_http_aes_body(state: dict[str, Any], key: bytes) -> dict[str, str]:
    plaintext = compact_json_bytes(state)
    frame = encrypt_frame(plaintext, key)
    return {"aes": base64.b64encode(frame).decode("ascii")}


def prepare_http_body(
    state: dict[str, Any], aes_key: Optional[bytes]
) -> dict[str, Any]:
    """Return either clear JSON state or {"aes": "..."} when key is set."""
    if aes_key is None:
        return sanitize_wled_state(state)
    return build_http_aes_body(state, aes_key)
