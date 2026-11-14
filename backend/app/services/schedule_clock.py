"""Reloj del horario en hora de Colombia.

La misma lógica está en orchestrator/schedule_clock.py. Si cambia una, cambia la otra.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")


def clock_now() -> datetime:
    return datetime.now(BOGOTA)


def as_time(value: object) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, timedelta):
        base = datetime.min + value
        return time(base.hour, base.minute)
    if isinstance(value, datetime):
        return time(value.hour, value.minute)
    raise TypeError(f"hora no reconocida: {value!r}")


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def interval_covers(start: time, end: time, moment: datetime, days: set[int]) -> bool:
    """True si moment cae en el intervalo. El fin es exclusivo.

    Si la hora de fin es menor que la de inicio, el tramo cruza la medianoche
    y sigue contando como el día en que empezó.
    """
    start_m = _minutes(as_time(start))
    end_m = _minutes(as_time(end))
    if start_m == end_m:
        return False
    weekday = moment.weekday()
    minute = moment.hour * 60 + moment.minute
    selected = set(days)
    if start_m < end_m:
        return weekday in selected and start_m <= minute < end_m
    if minute >= start_m and weekday in selected:
        return True
    previous = (weekday - 1) % 7
    return minute < end_m and previous in selected


def intervals_overlap(
    start_a: time,
    end_a: time,
    days_a: set[int],
    start_b: time,
    end_b: time,
    days_b: set[int],
) -> bool:
    origin = datetime(2026, 11, 16, 0, 0, tzinfo=BOGOTA)
    for offset in range(7 * 24 * 60):
        moment = origin + timedelta(minutes=offset)
        if interval_covers(start_a, end_a, moment, days_a) and interval_covers(
            start_b, end_b, moment, days_b
        ):
            return True
    return False
