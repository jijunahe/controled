from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    """Payload compatible con POST /json/state de WLED."""

    model_config = ConfigDict(extra="allow")

    on: Optional[bool] = True
    bri: Optional[int] = Field(default=128, ge=1, le=255)
    transition: Optional[int] = Field(default=None, ge=0, le=65535)
    seg: Optional[list[dict[str, Any]]] = None


class LedConfigurationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config_type: ConfigType
    payload_json: dict[str, Any]
    device_id: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=255)
    activate: bool = False


class LedConfigurationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    config_type: Optional[ConfigType] = None
    payload_json: Optional[dict[str, Any]] = None
    device_id: Optional[int] = None
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
    created_by: Optional[int] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    applied_at: Optional[datetime] = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    ip_address: str
    is_default: bool
    is_online: bool
    notes: Optional[str] = None


class MessageOut(BaseModel):
    detail: str
