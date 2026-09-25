from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import LedConfiguration, User, WledDevice
from app.schemas import (
    DeviceOut,
    LedConfigurationCreate,
    LedConfigurationOut,
    LedConfigurationUpdate,
    MessageOut,
)
from app.services import configurations as cfg_service

router = APIRouter(prefix="/api", tags=["configurations"])


@router.get("/configurations", response_model=list[LedConfigurationOut])
def list_configurations(
    status_filter: Optional[int] = Query(default=None, alias="status", ge=0, le=1),
    config_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[LedConfiguration]:
    query = db.query(LedConfiguration).order_by(LedConfiguration.id.desc())
    if status_filter is not None:
        query = query.filter(LedConfiguration.status == status_filter)
    if config_type:
        query = query.filter(LedConfiguration.config_type == config_type)
    return query.all()


@router.get("/configurations/active", response_model=Optional[LedConfigurationOut])
def get_active_configuration(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Optional[LedConfiguration]:
    return (
        db.query(LedConfiguration)
        .filter(LedConfiguration.status == 1)
        .order_by(LedConfiguration.updated_at.desc())
        .first()
    )


@router.get("/configurations/{config_id}", response_model=LedConfigurationOut)
def get_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> LedConfiguration:
    config = db.get(LedConfiguration, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    return config


@router.post(
    "/configurations",
    response_model=LedConfigurationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_configuration(
    body: LedConfigurationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> LedConfiguration:
    if body.device_id is not None and not db.get(WledDevice, body.device_id):
        raise HTTPException(status_code=400, detail="Dispositivo no encontrado")
    if not isinstance(body.payload_json, dict):
        raise HTTPException(status_code=400, detail="payload_json debe ser un objeto")

    return cfg_service.create_configuration(
        db,
        name=body.name,
        config_type=body.config_type.value,
        payload_json=body.payload_json,
        user=user,
        device_id=body.device_id,
        description=body.description,
        activate=body.activate,
    )


@router.put("/configurations/{config_id}", response_model=LedConfigurationOut)
def update_configuration(
    config_id: int,
    body: LedConfigurationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> LedConfiguration:
    config = db.get(LedConfiguration, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    if body.device_id is not None and not db.get(WledDevice, body.device_id):
        raise HTTPException(status_code=400, detail="Dispositivo no encontrado")

    return cfg_service.update_configuration(
        db,
        config,
        user=user,
        name=body.name,
        config_type=body.config_type.value if body.config_type else None,
        payload_json=body.payload_json,
        device_id=body.device_id,
        description=body.description,
        activate=body.activate,
    )


@router.post("/configurations/{config_id}/activate", response_model=LedConfigurationOut)
def activate_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> LedConfiguration:
    config = db.get(LedConfiguration, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    cfg_service.activate_configuration(db, config, actor=user.username)
    db.commit()
    db.refresh(config)
    return config


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
