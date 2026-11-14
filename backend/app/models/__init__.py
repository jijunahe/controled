from datetime import datetime, time as time_type
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

led_configuration_devices = Table(
    "led_configuration_devices",
    Base.metadata,
    Column(
        "configuration_id",
        Integer,
        ForeignKey("led_configurations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "device_id",
        Integer,
        ForeignKey("wled_devices.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("admin", "operator", "viewer", name="user_role"),
        default="operator",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class WledDevice(Base):
    __tablename__ = "wled_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), unique=True, nullable=False)
    mac_address: Mapped[Optional[str]] = mapped_column(String(17))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class LedConfiguration(Base):
    __tablename__ = "led_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config_type: Mapped[str] = mapped_column(
        Enum(
            "static",
            "sequence",
            "playlist",
            "audio_reactive",
            name="config_type_enum",
        ),
        nullable=False,
    )
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    device_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("wled_devices.id", ondelete="SET NULL")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    description: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    device: Mapped[Optional[WledDevice]] = relationship(
        "WledDevice", foreign_keys=[device_id]
    )
    devices: Mapped[list[WledDevice]] = relationship(
        "WledDevice",
        secondary=led_configuration_devices,
        lazy="selectin",
    )
    creator: Mapped[Optional[User]] = relationship("User")


class LedConfigurationLog(Base):
    __tablename__ = "led_configuration_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    configuration_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("led_configurations.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("wled_devices.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(
        Enum(
            "created",
            "updated",
            "activated",
            "deactivated",
            "applied",
            "apply_failed",
            "deleted",
            name="log_action_enum",
        ),
        nullable=False,
    )
    previous_status: Mapped[Optional[int]] = mapped_column(Integer)
    new_status: Mapped[Optional[int]] = mapped_column(Integer)
    http_status: Mapped[Optional[int]] = mapped_column(SmallInteger)
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    payload_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    actor: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )


class AudioSession(Base):
    __tablename__ = "audio_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    device_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("wled_devices.id", ondelete="SET NULL")
    )
    session_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(
        Enum("websocket", "mic_wled", "playlist_sim", name="audio_source_enum"),
        default="websocket",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    frames_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LedSchedule(Base):
    __tablename__ = "led_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    intervals: Mapped[list["LedScheduleInterval"]] = relationship(
        back_populates="schedule",
        cascade="all, delete-orphan",
        order_by="LedScheduleInterval.id",
        lazy="selectin",
    )


class LedScheduleInterval(Base):
    __tablename__ = "led_schedule_intervals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("led_schedules.id", ondelete="CASCADE"), nullable=False
    )
    configuration_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("led_configurations.id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[time_type] = mapped_column(Time, nullable=False)
    end_time: Mapped[time_type] = mapped_column(Time, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    schedule: Mapped[LedSchedule] = relationship(back_populates="intervals")
    configuration: Mapped[LedConfiguration] = relationship()
    days: Mapped[list["LedScheduleIntervalDay"]] = relationship(
        back_populates="interval",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class LedScheduleIntervalDay(Base):
    __tablename__ = "led_schedule_interval_days"

    interval_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("led_schedule_intervals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weekday: Mapped[int] = mapped_column(Integer, primary_key=True)
    interval: Mapped[LedScheduleInterval] = relationship(back_populates="days")


class LedPreset(Base):
    __tablename__ = "led_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)


class LedHeartbeat(Base):
    __tablename__ = "led_heartbeats"

    mac: Mapped[str] = mapped_column(String(12), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rssi: Mapped[Optional[int]] = mapped_column(SmallInteger)
    packets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LedPowerOverride(Base):
    __tablename__ = "led_power_override"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
