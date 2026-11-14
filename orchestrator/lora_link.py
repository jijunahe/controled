"""Enlace USB con la TTGO transmisora. El JSON sale en claro, sin AES ni MessagePack."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

import serial

logger = logging.getLogger("orchestrator.lora")

MAGIC = b"\xA5\x5A"
CMD_PING = 0x01
CMD_TX = 0x02
CMD_POLL = 0x03
CMD_UPLINK = 0x04
STATUS_OK = 0
MAX_AIR = 255
POLL_TIMEOUT = 6.0


class LoRaLinkError(Exception):
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


def integer_payload(payload: dict[str, Any]) -> dict[str, int]:
    if not isinstance(payload, dict) or not payload:
        raise LoRaLinkError("payload_json debe ser un objeto de enteros")
    clean: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise LoRaLinkError(f"{key} debe ser un número entero")
        clean[str(key)] = value
    playlist = clean.get("playlist")
    if playlist is None or not 1 <= playlist <= 250:
        raise LoRaLinkError("playlist debe estar entre 1 y 250")
    return clean


def clear_json_bytes(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if not raw or raw[:1] != b"{" or len(raw) > MAX_AIR:
        raise LoRaLinkError(f"JSON de {len(raw)} bytes; el máximo LoRa es {MAX_AIR}")
    return raw


class LoRaLink:
    def __init__(self, port: str, baud: int = 115200, dry_run: bool = False) -> None:
        self.port = port
        self.baud = baud
        self.dry_run = dry_run
        self._lock = threading.Lock()
        self._ser: Optional[serial.Serial] = None

    def close(self) -> None:
        with self._lock:
            if self._ser is not None:
                self._ser.close()
                self._ser = None

    def send_payload(self, payload: dict[str, Any]) -> bytes:
        if not isinstance(payload, dict):
            raise LoRaLinkError("el paquete LoRa debe ser un objeto JSON")
        raw = clear_json_bytes(payload)
        if self.dry_run:
            logger.info("[DRY_RUN] LoRa USB %s → %s", self.port, raw.decode("utf-8"))
            return raw
        with self._lock:
            self._ensure_open()
            self._transmit(raw)
        logger.info("LoRa USB %s ← %s", self.port, raw.decode("utf-8"))
        return raw

    def poll_heartbeat(self) -> list[bytes]:
        """Pregunta {"hb":1} y devuelve las tramas que contestaron las receptoras."""
        raw = clear_json_bytes({"hb": 1})
        if self.dry_run:
            logger.info("[DRY_RUN] bit de vida %s → %s", self.port, raw.decode("utf-8"))
            return []
        with self._lock:
            self._ensure_open()
            self._write(CMD_POLL, raw)
            frames = self._read_poll(POLL_TIMEOUT)
        for frame in frames:
            logger.info("Bit de vida USB %s → %s", self.port, frame.decode("utf-8", "replace"))
        return frames

    def _ensure_open(self) -> None:
        if self._ser is not None and self._ser.is_open:
            return
        self._ser = serial.Serial(self.port, self.baud, timeout=0.05)
        self._ser.dtr = False
        self._ser.rts = False
        time.sleep(0.2)
        self._ser.reset_input_buffer()
        self._ping_ready()

    def _ping_ready(self) -> None:
        assert self._ser is not None
        last: Optional[Exception] = None
        for _ in range(8):
            try:
                self._write(CMD_PING, None)
                status, _detail = self._read_reply(CMD_PING, 0.8)
                if status == STATUS_OK:
                    return
                raise LoRaLinkError(f"la radio de la TTGO no está lista ({status})")
            except LoRaLinkError as exc:
                last = exc
                time.sleep(0.4)
        raise LoRaLinkError("la TTGO transmisora no respondió por USB") from last

    def _transmit(self, payload: bytes) -> None:
        assert self._ser is not None
        self._write(CMD_TX, payload)
        status, detail = self._read_reply(CMD_TX, 4.0)
        if status != STATUS_OK:
            raise LoRaLinkError(f"la TTGO rechazó el envío (estado {status}, código {detail})")

    def _write(self, cmd: int, payload: Optional[bytes]) -> None:
        assert self._ser is not None
        body = bytes([cmd])
        if payload is not None:
            body += len(payload).to_bytes(2, "little") + payload + crc16(payload).to_bytes(2, "little")
        self._ser.write(MAGIC + body)
        self._ser.flush()

    def _read_reply(self, cmd: int, timeout: float) -> tuple[int, int]:
        assert self._ser is not None
        expect = cmd | 0x80
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
                if buf[2] != expect:
                    del buf[:1]
                    continue
                status = buf[3]
                detail = int.from_bytes(buf[4:6], "little", signed=True)
                del buf[:6]
                return status, detail
            time.sleep(0.01)
        raise LoRaLinkError("la TTGO no respondió")

    def _read_poll(self, timeout: float) -> list[bytes]:
        assert self._ser is not None
        expect = CMD_POLL | 0x80
        deadline = time.monotonic() + timeout
        buf = bytearray()
        found: list[bytes] = []
        while time.monotonic() < deadline:
            chunk = self._ser.read(128)
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
                if len(buf) < 3:
                    break
                cmd = buf[2]
                if cmd == expect:
                    if len(buf) < 6:
                        break
                    status = buf[3]
                    detail = int.from_bytes(buf[4:6], "little", signed=True)
                    del buf[:6]
                    if status != STATUS_OK:
                        raise LoRaLinkError(
                            f"la TTGO rechazó el bit de vida (estado {status}, código {detail})"
                        )
                    return found
                if cmd == CMD_UPLINK:
                    if len(buf) < 5:
                        break
                    length = int.from_bytes(buf[3:5], "little")
                    total = 5 + length + 2
                    if length == 0 or length > MAX_AIR:
                        del buf[:1]
                        continue
                    if len(buf) < total:
                        break
                    payload = bytes(buf[5 : 5 + length])
                    crc = int.from_bytes(buf[5 + length : total], "little")
                    del buf[:total]
                    if crc16(payload) == crc:
                        found.append(payload)
                    continue
                del buf[:1]
            time.sleep(0.01)
        raise LoRaLinkError("la TTGO no respondió al bit de vida")
