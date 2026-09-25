"""WebSocket modo musical / audio-reactivo → WLED en tiempo real."""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import AudioSession, LedConfiguration, User, WledDevice
from app.security import decode_access_token
from app.services.wled_realtime import WledRealtimeClient

logger = logging.getLogger("controled.realtime")
router = APIRouter(tags=["realtime"])
settings = get_settings()


def _get_token(websocket: WebSocket) -> Optional[str]:
    token = websocket.query_params.get("token")
    if token:
        return token
    return websocket.cookies.get("access_token")


def _authenticate(db: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        if not username:
            return None
    except ValueError:
        return None
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    return user


def _resolve_device(db: Session, device_id: Optional[int]) -> tuple[Optional[int], str]:
    if device_id is not None:
        device = db.get(WledDevice, device_id)
        if device:
            return device.id, device.ip_address
    default = (
        db.query(WledDevice)
        .filter(WledDevice.is_default.is_(True))
        .order_by(WledDevice.id.asc())
        .first()
    )
    if default:
        return default.id, default.ip_address
    return None, settings.wled_default_ip


def _pause_orchestrator_queue(db: Session) -> None:
    """Evita pelea orquestador vs modo musical."""
    db.query(LedConfiguration).filter(LedConfiguration.status == 1).update(
        {LedConfiguration.status: 0},
        synchronize_session=False,
    )


def _start_session(
    db: Session,
    *,
    user: User,
    device_id: Optional[int],
    source: str,
) -> AudioSession:
    _pause_orchestrator_queue(db)
    session = AudioSession(
        user_id=user.id,
        device_id=device_id,
        session_token=secrets.token_hex(16),
        source=source if source in {"websocket", "mic_wled", "playlist_sim"} else "websocket",
        is_active=True,
        frames_sent=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _bump_frames(db: Session, session_id: int, count: int = 1) -> None:
    row = db.get(AudioSession, session_id)
    if not row:
        return
    row.frames_sent = int(row.frames_sent or 0) + count
    db.commit()


def _end_session(db: Session, session_id: int) -> None:
    row = db.get(AudioSession, session_id)
    if not row:
        return
    row.is_active = False
    row.ended_at = datetime.utcnow()
    db.commit()


async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


@router.websocket("/ws/music")
async def music_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    db = SessionLocal()
    wled = WledRealtimeClient(settings)
    session: Optional[AudioSession] = None
    device_ip = settings.wled_default_ip
    frames_ok = 0
    frames_dropped = 0

    try:
        token = _get_token(websocket)
        user = _authenticate(db, token)
        if not user:
            await _send(websocket, {"type": "error", "detail": "No autenticado"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if user.role == "viewer":
            await _send(websocket, {"type": "error", "detail": "Sin permisos"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        device_id_param = websocket.query_params.get("device_id")
        initial_device_id = (
            int(device_id_param) if device_id_param and device_id_param.isdigit() else None
        )
        source = websocket.query_params.get("source", "websocket")
        device_id, device_ip = _resolve_device(db, initial_device_id)
        session = _start_session(db, user=user, device_id=device_id, source=source)

        await _send(
            websocket,
            {
                "type": "ready",
                "session_token": session.session_token,
                "device_id": device_id,
                "device_ip": device_ip,
                "dry_run": settings.wled_dry_run,
                "max_fps": settings.music_max_fps,
                "user": user.username,
            },
        )

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, {"type": "error", "detail": "JSON inválido"})
                continue

            msg_type = message.get("type", "frame")

            if msg_type == "ping":
                await _send(websocket, {"type": "pong"})
                continue

            if msg_type == "hello":
                if message.get("device_id") is not None:
                    device_id, device_ip = _resolve_device(db, int(message["device_id"]))
                await _send(
                    websocket,
                    {
                        "type": "ready",
                        "session_token": session.session_token,
                        "device_id": device_id,
                        "device_ip": device_ip,
                        "dry_run": settings.wled_dry_run,
                    },
                )
                continue

            if msg_type == "stop":
                await _send(
                    websocket,
                    {
                        "type": "stopped",
                        "frames_ok": frames_ok,
                        "frames_dropped": frames_dropped,
                    },
                )
                break

            if msg_type not in {"frame", "burst"}:
                await _send(websocket, {"type": "error", "detail": f"Tipo desconocido: {msg_type}"})
                continue

            frames = message.get("frames") if msg_type == "burst" else [message]
            if not isinstance(frames, list):
                frames = [message]

            for frame in frames:
                if not isinstance(frame, dict):
                    continue
                try:
                    state = WledRealtimeClient.frame_to_state(frame)
                except (TypeError, ValueError) as exc:
                    await _send(websocket, {"type": "error", "detail": str(exc)})
                    continue

                ok, http_status, detail, throttled = await wled.post_state(device_ip, state)
                if throttled:
                    frames_dropped += 1
                    continue
                if ok:
                    frames_ok += 1
                    if frames_ok % 25 == 0:
                        _bump_frames(db, session.id, 25)
                else:
                    await _send(
                        websocket,
                        {
                            "type": "error",
                            "detail": f"WLED: {detail}",
                            "http_status": http_status,
                        },
                    )

            if frames_ok and frames_ok % 10 == 0:
                await _send(
                    websocket,
                    {
                        "type": "ack",
                        "frames_ok": frames_ok,
                        "frames_dropped": frames_dropped,
                    },
                )

    except WebSocketDisconnect:
        logger.info("WS music desconectado frames_ok=%s", frames_ok)
    except Exception:
        logger.exception("Error en WebSocket music")
        try:
            await _send(websocket, {"type": "error", "detail": "Error interno"})
        except Exception:
            pass
    finally:
        if session is not None:
            remainder = frames_ok % 25
            if remainder:
                try:
                    _bump_frames(db, session.id, remainder)
                except Exception:
                    logger.exception("No se pudo actualizar frames")
            try:
                _end_session(db, session.id)
            except Exception:
                logger.exception("No se pudo cerrar sesión audio")
        await wled.aclose()
        db.close()
