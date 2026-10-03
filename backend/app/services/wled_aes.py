"""AES-128-GCM envelope for TTGO WLED Wi-Fi JSON API (lora_rx contract)."""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AES_MAGIC = 0xA1
AES_NONCE_LEN = 12
MAX_PLAINTEXT_BYTES = 226


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
    if not isinstance(state, dict):
        raise ValueError("state must be an object")

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
        for item in seg[:5]:
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
    ct_and_tag = AESGCM(key).encrypt(nonce, plaintext, None)
    return bytes([AES_MAGIC]) + nonce + ct_and_tag


def build_http_aes_body(state: dict[str, Any], key: bytes) -> dict[str, str]:
    plaintext = compact_json_bytes(state)
    frame = encrypt_frame(plaintext, key)
    return {"aes": base64.b64encode(frame).decode("ascii")}


def prepare_http_body(
    state: dict[str, Any], aes_key: Optional[bytes]
) -> dict[str, Any]:
    if aes_key is None:
        return sanitize_wled_state(state)
    return build_http_aes_body(state, aes_key)
