"""Listado del bit de vida para el panel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import LedHeartbeat

BOGOTA = ZoneInfo("America/Bogota")
FRESH = timedelta(seconds=45)


def format_mac(mac: str) -> str:
    compact = mac.replace(":", "").lower()
    return ":".join(compact[i : i + 2] for i in range(0, 12, 2)).upper()


def list_beats(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = db.query(LedHeartbeat).order_by(LedHeartbeat.mac.asc()).all()
    beats = []
    for row in rows:
        seen = row.last_seen
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        local = seen.astimezone(BOGOTA)
        beats.append(
            {
                "mac": format_mac(row.mac),
                "alive": now - seen <= FRESH,
                "seen": local.strftime("%H:%M:%S"),
                "rssi": row.rssi,
            }
        )
    return beats
