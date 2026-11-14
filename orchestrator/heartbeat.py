"""Lectura del bit de vida que contestan las TTGO por LoRa."""

from __future__ import annotations

import json
from typing import Optional

_HEX = set("0123456789abcdef")


def parse_heartbeat(raw: bytes) -> Optional[dict]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    mac = data.get("mac")
    if not isinstance(mac, str):
        return None
    mac = mac.replace(":", "").strip().lower()
    if len(mac) != 12 or any(char not in _HEX for char in mac):
        return None
    rssi = data.get("rssi")
    if type(rssi) is not int:
        rssi = None
    return {"mac": mac, "rssi": rssi}


def format_mac(mac: str) -> str:
    return ":".join(mac[i : i + 2] for i in range(0, 12, 2)).upper()
