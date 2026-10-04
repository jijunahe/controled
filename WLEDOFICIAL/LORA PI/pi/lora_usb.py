#!/usr/bin/env python3
"""Envía por USB la trama que la TTGO retransmite por LoRa.

La placa no interpreta el contenido: los bytes que salen por el aire son
exactamente el payload. Para las WLED con lora_rx, ese payload es
AES-128-GCM(MessagePack) del estado.

Protocolo (little-endian), el mismo que firmware/src/main.cpp:
  petición  A5 5A | cmd | [len u16 | payload | crc16]
  respuesta A5 5A | cmd|0x80 | status | detail i16
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from typing import Any, Optional

try:
    import serial
except ImportError:
    serial = None  # type: ignore

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None  # type: ignore

MAGIC = b"\xA5\x5A"
CMD_PING = 0x01
CMD_TX = 0x02
STATUS_OK = 0
STATUS_NAMES = {
    0: "ok",
    1: "crc",
    2: "longitud",
    3: "radio",
    4: "orden",
}
AES_MAGIC = 0xA1
MAX_PLAINTEXT = 226
MAX_AIR = 255


class LoRaUsbError(Exception):
    pass


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _pack_int(number: int) -> bytes:
    if 0 <= number <= 127:
        return bytes([number])
    if number <= 255:
        return bytes([0xCC, number & 0xFF])
    if number <= 65535:
        return b"\xcd" + number.to_bytes(2, "big")
    raise LoRaUsbError(f"entero fuera de rango: {number}")


def _pack_msgpack(value: Any) -> bytes:
    if value is True:
        return b"\xc3"
    if value is False:
        return b"\xc2"
    if isinstance(value, int) and not isinstance(value, bool):
        return _pack_int(value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        if len(raw) > 31:
            raise LoRaUsbError("clave demasiado larga")
        return bytes([0xA0 | len(raw)]) + raw
    if isinstance(value, list):
        if len(value) > 15:
            raise LoRaUsbError("arreglo demasiado largo")
        return bytes([0x90 | len(value)]) + b"".join(_pack_msgpack(item) for item in value)
    if isinstance(value, dict):
        if len(value) > 15:
            raise LoRaUsbError("objeto demasiado grande")
        body = b"".join(_pack_msgpack(key) + _pack_msgpack(item) for key, item in value.items())
        return bytes([0x80 | len(value)]) + body
    raise LoRaUsbError(f"tipo no soportado: {type(value).__name__}")


def sanitize_wled_state(state: dict[str, Any]) -> dict[str, Any]:
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
        clean = []
        for item in seg[:5]:
            if not isinstance(item, dict):
                continue
            piece: dict[str, Any] = {}
            if "id" in item:
                piece["id"] = max(0, min(31, int(item["id"])))
            for key in ("start", "stop", "fx", "sx", "ix", "pal"):
                if key in item:
                    piece[key] = int(item[key])
            col = item.get("col")
            if isinstance(col, list) and col:
                colors = []
                for color in col[:3]:
                    if isinstance(color, (list, tuple)) and len(color) >= 3:
                        colors.append([int(color[0]) % 256, int(color[1]) % 256, int(color[2]) % 256])
                if colors:
                    piece["col"] = colors
            if piece:
                clean.append(piece)
        if clean:
            out["seg"] = clean
    if not out:
        raise LoRaUsbError("el estado WLED quedó vacío")
    return out


def clear_json_bytes(state: dict[str, Any]) -> bytes:
    """JSON en claro, solo enteros. Es el payload que viaja por LoRa."""
    if not isinstance(state, dict) or not state:
        raise LoRaUsbError("el JSON debe ser un objeto de enteros")
    clean: dict[str, int] = {}
    for key, value in state.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise LoRaUsbError(f"{key} debe ser un número entero")
        clean[str(key)] = value
    playlist = clean.get("playlist")
    if playlist is None or not 1 <= playlist <= 250:
        raise LoRaUsbError("playlist debe estar entre 1 y 250")
    raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_AIR:
        raise LoRaUsbError(f"JSON de {len(raw)} bytes; el máximo en el aire es {MAX_AIR}")
    return raw


def encode_air_frame(state: dict[str, Any], key: bytes) -> bytes:
    if AESGCM is None:
        raise LoRaUsbError("falta el paquete cryptography")
    if len(key) != 16:
        raise LoRaUsbError("la llave AES debe tener 16 bytes")
    plain = _pack_msgpack(sanitize_wled_state(state))
    if len(plain) > MAX_PLAINTEXT:
        raise LoRaUsbError(f"MessagePack de {len(plain)} bytes; el máximo es {MAX_PLAINTEXT}")
    nonce = secrets.token_bytes(12)
    sealed = AESGCM(key).encrypt(nonce, plain, None)
    frame = bytes([AES_MAGIC]) + nonce + sealed
    if len(frame) > MAX_AIR:
        raise LoRaUsbError(f"trama de {len(frame)} bytes; el máximo en el aire es {MAX_AIR}")
    return frame


def parse_key(text: str) -> bytes:
    hex_key = text.strip().replace(" ", "").lower()
    if len(hex_key) != 32:
        raise LoRaUsbError("la llave debe ser 32 caracteres hexadecimales")
    try:
        return bytes.fromhex(hex_key)
    except ValueError as exc:
        raise LoRaUsbError("la llave no es hexadecimal") from exc


class LoRaUsb:
    def __init__(self, port: str, baud: int = 115200) -> None:
        if serial is None:
            raise LoRaUsbError("falta el paquete pyserial")
        self._ser = serial.Serial(port, baud, timeout=0.05)
        self._ser.dtr = False
        self._ser.rts = False
        time.sleep(0.2)
        self._ser.reset_input_buffer()

    def close(self) -> None:
        self._ser.close()

    def _write_frame(self, cmd: int, payload: Optional[bytes] = None) -> None:
        body = bytes([cmd])
        if payload is not None:
            if not 1 <= len(payload) <= MAX_AIR:
                raise LoRaUsbError(f"payload de {len(payload)} bytes; permitido 1..{MAX_AIR}")
            crc = crc16(payload)
            body += len(payload).to_bytes(2, "little") + payload + crc.to_bytes(2, "little")
        self._ser.write(MAGIC + body)
        self._ser.flush()

    def _read_reply(self, cmd: int, timeout: float) -> tuple[int, int]:
        expect = bytes([cmd | 0x80])
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._ser.read(64)
            if chunk:
                buf += chunk
            while True:
                start = buf.find(MAGIC)
                if start < 0:
                    if len(buf) > 1:
                        del buf[:-1]
                    break
                if start:
                    del buf[:start]
                if len(buf) < 6:
                    break
                if buf[2] != expect[0]:
                    del buf[:1]
                    continue
                status = buf[3]
                detail = int.from_bytes(buf[4:6], "little", signed=True)
                del buf[:6]
                return status, detail
            time.sleep(0.01)
        raise LoRaUsbError("la TTGO no respondió")

    def ping(self, timeout: float = 2.0) -> tuple[int, int]:
        self._write_frame(CMD_PING)
        return self._read_reply(CMD_PING, timeout)

    def wait_ready(self, attempts: int = 8) -> tuple[int, int]:
        last: Optional[Exception] = None
        for _ in range(attempts):
            try:
                return self.ping(timeout=0.8)
            except LoRaUsbError as exc:
                last = exc
                time.sleep(0.4)
        raise LoRaUsbError("la TTGO no respondió al ping") from last

    def transmit(self, payload: bytes, timeout: float = 4.0) -> int:
        self._write_frame(CMD_TX, payload)
        status, detail = self._read_reply(CMD_TX, timeout)
        if status != STATUS_OK:
            name = STATUS_NAMES.get(status, str(status))
            raise LoRaUsbError(f"la TTGO rechazó el envío ({name}, código {detail})")
        return detail

    def send_state(self, state: dict[str, Any], key: bytes) -> int:
        return self.transmit(encode_air_frame(state, key))

    def send_clear(self, state: dict[str, Any]) -> int:
        return self.transmit(clear_json_bytes(state))


def self_test() -> None:
    sample = b"123456789"
    got = crc16(sample)
    if got != 0x29B1:
        raise SystemExit(f"CRC inesperado: {got:#06x}")
    state = {"on": True, "bri": 160, "seg": [{"id": 0, "fx": 0, "col": [[255, 0, 0]]}]}
    key = bytes(range(16))
    frame = encode_air_frame(state, key)
    if frame[0] != AES_MAGIC or len(frame) > MAX_AIR:
        raise SystemExit("la trama de prueba no cumple el sobre AES")
    clear = clear_json_bytes({"playlist": 1})
    if clear != b'{"playlist":1}':
        raise SystemExit(f"JSON en claro inesperado: {clear!r}")
    print(f"self-test ok, trama de ejemplo {len(frame)} bytes, claro {clear.decode()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manda un paquete a la TTGO por USB para que lo retransmita por LoRa")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--key", help="llave AES-128 de la WLED, 32 hex")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-test")
    sub.add_parser("ping")
    send = sub.add_parser("send")
    send.add_argument("state", help='JSON de estado, por ejemplo \'{"on":false}\'')
    raw = sub.add_parser("raw")
    raw.add_argument("hex", help="bytes en hexadecimal que se transmiten tal cual")
    args = parser.parse_args()

    if args.cmd == "self-test":
        self_test()
        return 0

    link = LoRaUsb(args.port, args.baud)
    try:
        status, detail = link.wait_ready()
        if args.cmd == "ping":
            if status != STATUS_OK:
                print(f"radio no lista (estado {STATUS_NAMES.get(status, status)}, código {detail})", file=sys.stderr)
                return 1
            print(f"TTGO lista, protocolo {detail}")
            return 0
        if status != STATUS_OK:
            print("la radio de la TTGO no arrancó", file=sys.stderr)
            return 1
        if args.cmd == "raw":
            payload = bytes.fromhex(args.hex.replace(" ", ""))
            count = link.transmit(payload)
        else:
            count = link.send_clear(json.loads(args.state))
        print(f"enviado, paquete {count}")
        return 0
    finally:
        link.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LoRaUsbError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
