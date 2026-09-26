from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import LedConfiguration, User, WledDevice
from app.schemas import (
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
    LedConfigurationCreate,
    LedConfigurationOut,
    LedConfigurationUpdate,
    MessageOut,
)
from app.services import configurations as cfg_service
from app.services import devices as device_service

router = APIRouter(prefix="/api", tags=["configurations"])


def _to_out(config: LedConfiguration) -> LedConfigurationOut:
    return LedConfigurationOut.from_orm_config(config)


@router.get("/configurations", response_model=list[LedConfigurationOut])
def list_configurations(
    status_filter: Optional[int] = Query(default=None, alias="status", ge=0, le=1),
    config_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[LedConfigurationOut]:
    query = db.query(LedConfiguration).order_by(LedConfiguration.id.desc())
    if status_filter is not None:
        query = query.filter(LedConfiguration.status == status_filter)
    if config_type:
        query = query.filter(LedConfiguration.config_type == config_type)
    return [_to_out(c) for c in query.all()]


@router.get("/configurations/active", response_model=list[LedConfigurationOut])
def get_active_configurations(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[LedConfigurationOut]:
    rows = (
        db.query(LedConfiguration)
        .filter(LedConfiguration.status == 1)
        .order_by(LedConfiguration.updated_at.desc())
        .all()
    )
    return [_to_out(c) for c in rows]


@router.get("/configurations/{config_id}", response_model=LedConfigurationOut)
def get_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> LedConfigurationOut:
    config = db.get(LedConfiguration, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    return _to_out(config)


@router.post(
    "/configurations",
    response_model=LedConfigurationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_configuration(
    body: LedConfigurationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> LedConfigurationOut:
    if not isinstance(body.payload_json, dict):
        raise HTTPException(status_code=400, detail="payload_json debe ser un objeto")
    try:
        config = cfg_service.create_configuration(
            db,
            name=body.name,
            config_type=body.config_type.value,
            payload_json=body.payload_json,
            user=user,
            device_id=body.device_id,
            device_ids=body.device_ids,
            description=body.description,
            activate=body.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(config)


@router.put("/configurations/{config_id}", response_model=LedConfigurationOut)
def update_configuration(
    config_id: int,
    body: LedConfigurationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> LedConfigurationOut:
    config = db.get(LedConfiguration, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    try:
        config = cfg_service.update_configuration(
            db,
            config,
            user=user,
            name=body.name,
            config_type=body.config_type.value if body.config_type else None,
            payload_json=body.payload_json,
            device_id=body.device_id,
            device_ids=body.device_ids,
            description=body.description,
            activate=body.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(config)


@router.post("/configurations/{config_id}/activate", response_model=LedConfigurationOut)
def activate_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> LedConfigurationOut:
    config = db.get(LedConfiguration, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    cfg_service.activate_configuration(db, config, actor=user.username)
    db.commit()
    db.refresh(config)
    return _to_out(config)


@router.delete("/configurations/{config_id}", response_model=MessageOut)
def delete_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> MessageOut:
    config = db.get(LedConfiguration, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    cfg_service.delete_configuration(db, config, user)
    return MessageOut(detail="Configuración eliminada")


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[WledDevice]:
    return db.query(WledDevice).order_by(WledDevice.id.asc()).all()


@router.post(
    "/devices",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_device(
    body: DeviceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
) -> WledDevice:
    try:
        return device_service.create_device(
            db,
            name=body.name,
            ip_address=body.ip_address,
            mac_address=body.mac_address,
            is_default=body.is_default,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/devices/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: int,
    body: DeviceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
) -> WledDevice:
    device = db.get(WledDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    try:
        return device_service.update_device(
            db,
            device,
            name=body.name,
            ip_address=body.ip_address,
            mac_address=body.mac_address,
            is_default=body.is_default,
            notes=body.notes,
            is_online=body.is_online,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/devices/{device_id}", response_model=MessageOut)
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
) -> MessageOut:
    device = db.get(WledDevice, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    device_service.delete_device(db, device)
    return MessageOut(detail="Dispositivo eliminado")
