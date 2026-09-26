from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigType(str, Enum):
    static = "static"
    sequence = "sequence"
    playlist = "playlist"
    audio_reactive = "audio_reactive"


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool


class WledPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    on: Optional[bool] = True
    bri: Optional[int] = Field(default=128, ge=1, le=255)
    transition: Optional[int] = Field(default=None, ge=0, le=65535)
    seg: Optional[list[dict[str, Any]]] = None


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ip_address: str = Field(min_length=7, max_length=45)
    mac_address: Optional[str] = Field(default=None, max_length=17)
    is_default: bool = False
    notes: Optional[str] = Field(default=None, max_length=255)


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    ip_address: Optional[str] = Field(default=None, min_length=7, max_length=45)
    mac_address: Optional[str] = Field(default=None, max_length=17)
    is_default: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=255)
    is_online: Optional[bool] = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    ip_address: str
    mac_address: Optional[str] = None
    is_default: bool
    is_online: bool
    notes: Optional[str] = None


class LedConfigurationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config_type: ConfigType
    payload_json: dict[str, Any]
    device_id: Optional[int] = None
    device_ids: Optional[list[int]] = None
    description: Optional[str] = Field(default=None, max_length=255)
    activate: bool = False

    @model_validator(mode="after")
    def normalize_devices(self) -> "LedConfigurationCreate":
        ids = list(self.device_ids or [])
        if self.device_id is not None and self.device_id not in ids:
            ids.append(self.device_id)
        self.device_ids = ids
        return self


class LedConfigurationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    config_type: Optional[ConfigType] = None
    payload_json: Optional[dict[str, Any]] = None
    device_id: Optional[int] = None
    device_ids: Optional[list[int]] = None
    description: Optional[str] = Field(default=None, max_length=255)
    activate: Optional[bool] = None


class LedConfigurationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    config_type: ConfigType
    payload_json: dict[str, Any]
    status: int
    device_id: Optional[int] = None
    device_ids: list[int] = []
    created_by: Optional[int] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    applied_at: Optional[datetime] = None

    @classmethod
    def from_orm_config(cls, config: Any) -> "LedConfigurationOut":
        device_ids = [d.id for d in getattr(config, "devices", []) or []]
        if not device_ids and getattr(config, "device_id", None):
            device_ids = [config.device_id]
        return cls(
            id=config.id,
            name=config.name,
            config_type=config.config_type,
            payload_json=config.payload_json,
            status=config.status,
            device_id=config.device_id or (device_ids[0] if device_ids else None),
            device_ids=device_ids,
            created_by=config.created_by,
            description=config.description,
            created_at=config.created_at,
            updated_at=config.updated_at,
            applied_at=config.applied_at,
        )


class MessageOut(BaseModel):
    detail: str
