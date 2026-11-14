"""Horario nuevo. No altera las tablas de configuraciones."""

from __future__ import annotations

from datetime import time

from sqlalchemy.orm import Session, selectinload

from app.models import (
    LedConfiguration,
    LedPowerOverride,
    LedSchedule,
    LedScheduleInterval,
    LedScheduleIntervalDay,
)
from app.services.schedule_clock import (
    as_time,
    clock_now,
    interval_covers,
    intervals_overlap,
)

DAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def is_paused(db: Session) -> bool:
    row = db.get(LedPowerOverride, 1)
    return bool(row and row.paused)


def set_paused(db: Session, paused: bool) -> None:
    row = db.get(LedPowerOverride, 1)
    if row is None:
        db.add(LedPowerOverride(id=1, paused=paused))
    else:
        row.paused = paused
    db.commit()


def load_schedule(db: Session) -> LedSchedule | None:
    return (
        db.query(LedSchedule)
        .options(
            selectinload(LedSchedule.intervals).selectinload(LedScheduleInterval.days),
            selectinload(LedSchedule.intervals).selectinload(LedScheduleInterval.configuration),
        )
        .order_by(LedSchedule.id.asc())
        .first()
    )


def _ensure_schedule(db: Session) -> LedSchedule:
    schedule = load_schedule(db)
    if schedule is not None:
        return schedule
    schedule = LedSchedule(name="Horario", enabled=True)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return load_schedule(db) or schedule


def set_enabled(db: Session, enabled: bool) -> None:
    schedule = _ensure_schedule(db)
    schedule.enabled = enabled
    db.commit()


def parse_clock(value: str) -> time:
    parts = (value or "").strip().split(":")
    if len(parts) < 2:
        raise ValueError("la hora debe ser HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("la hora está fuera de rango")
    return time(hour, minute)


def _selected_days(days: list[int]) -> list[int]:
    selected = sorted({int(day) for day in days})
    if not selected or any(day < 0 or day > 6 for day in selected):
        raise ValueError("elige al menos un día")
    return selected


def _require_config(db: Session, configuration_id: int) -> LedConfiguration:
    config = db.get(LedConfiguration, configuration_id)
    if config is None:
        raise ValueError("esa configuración ya no existe")
    return config


def _assert_clear(
    db: Session,
    start: time,
    end: time,
    days: set[int],
    *,
    ignore_id: int | None = None,
) -> None:
    others = (
        db.query(LedScheduleInterval)
        .options(selectinload(LedScheduleInterval.days))
        .all()
    )
    for other in others:
        if ignore_id is not None and other.id == ignore_id:
            continue
        if not other.enabled:
            continue
        other_days = {int(day.weekday) for day in other.days}
        if intervals_overlap(
            start,
            end,
            days,
            as_time(other.start_time),
            as_time(other.end_time),
            other_days,
        ):
            raise ValueError("ese horario se cruza con otro activo. Cambia el día o la hora")


def _load_interval(db: Session, interval_id: int) -> LedScheduleInterval:
    interval = (
        db.query(LedScheduleInterval)
        .options(selectinload(LedScheduleInterval.days))
        .filter(LedScheduleInterval.id == interval_id)
        .one_or_none()
    )
    if interval is None:
        raise ValueError("ese horario ya no existe")
    return interval


def _replace_days(db: Session, interval: LedScheduleInterval, days: list[int]) -> None:
    interval.days.clear()
    db.flush()
    for day in days:
        db.add(LedScheduleIntervalDay(interval_id=interval.id, weekday=day))


def add_interval(
    db: Session,
    *,
    days: list[int],
    start: time,
    end: time,
    configuration_id: int,
) -> None:
    selected = _selected_days(days)
    if start == end:
        raise ValueError("la hora de inicio y la de apagado no pueden ser iguales")
    config = _require_config(db, configuration_id)
    _assert_clear(db, start, end, set(selected))

    schedule = _ensure_schedule(db)
    interval = LedScheduleInterval(
        schedule_id=schedule.id,
        configuration_id=config.id,
        start_time=start,
        end_time=end,
        enabled=True,
    )
    db.add(interval)
    db.flush()
    _replace_days(db, interval, selected)
    db.commit()


def update_interval(
    db: Session,
    interval_id: int,
    *,
    days: list[int],
    start: time,
    end: time,
    configuration_id: int,
) -> None:
    selected = _selected_days(days)
    if start == end:
        raise ValueError("la hora de inicio y la de apagado no pueden ser iguales")
    config = _require_config(db, configuration_id)
    interval = _load_interval(db, interval_id)
    if interval.enabled:
        _assert_clear(db, start, end, set(selected), ignore_id=interval.id)
    interval.configuration_id = config.id
    interval.start_time = start
    interval.end_time = end
    _replace_days(db, interval, selected)
    db.commit()


def set_interval_enabled(db: Session, interval_id: int, enabled: bool) -> None:
    interval = _load_interval(db, interval_id)
    if enabled and not interval.enabled:
        _assert_clear(
            db,
            as_time(interval.start_time),
            as_time(interval.end_time),
            {int(day.weekday) for day in interval.days},
            ignore_id=interval.id,
        )
    interval.enabled = enabled
    db.commit()


def delete_interval(db: Session, interval_id: int) -> None:
    row = db.get(LedScheduleInterval, interval_id)
    if row is not None:
        db.delete(row)
        db.commit()


def interval_rows(schedule: LedSchedule | None) -> list[dict]:
    if schedule is None:
        return []
    rows: list[dict] = []
    for interval in schedule.intervals:
        days = sorted(int(day.weekday) for day in interval.days)
        rows.append(
            {
                "id": interval.id,
                "days": " ".join(DAY_LABELS[day] for day in days),
                "weekdays": days,
                "start": as_time(interval.start_time).strftime("%H:%M"),
                "end": as_time(interval.end_time).strftime("%H:%M"),
                "configuration_id": interval.configuration_id,
                "config_name": interval.configuration.name if interval.configuration else "—",
                "enabled": bool(interval.enabled),
            }
        )
    return rows


def describe_now(paused: bool, schedule: LedSchedule | None) -> str:
    now = clock_now()
    clock = now.strftime("%H:%M")
    if paused:
        return f"Apagado manual. El horario sigue en pausa. Hora Colombia {clock}."
    active = [item for item in schedule.intervals if item.enabled] if schedule and schedule.enabled else []
    if schedule is None or not schedule.enabled or not active:
        return f"Sin horario en marcha. Hora Colombia {clock}. Manda la configuración activa."
    for interval in sorted(active, key=lambda item: item.id):
        days = {int(day.weekday) for day in interval.days}
        if interval_covers(as_time(interval.start_time), as_time(interval.end_time), now, days):
            name = interval.configuration.name if interval.configuration is not None else "configuración"
            return f"Ahora, {clock}, toca «{name}»."
    return f"Ahora, {clock}, está fuera de horario: las luces quedan apagadas."
