from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import LedConfiguration, LedConfigurationLog, User, WledDevice


def _add_log(
    db: Session,
    *,
    configuration_id: int,
    action: str,
    actor: str,
    previous_status: Optional[int] = None,
    new_status: Optional[int] = None,
    device_id: Optional[int] = None,
    payload_snapshot: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    db.add(
        LedConfigurationLog(
            configuration_id=configuration_id,
            device_id=device_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            payload_snapshot=payload_snapshot,
            error_message=error_message,
            actor=actor,
        )
    )


def resolve_target_device_ids(
    db: Session, config: LedConfiguration
) -> list[int]:
    """Dispositivos destino: M2M, luego device_id legado, luego default."""
    ids = [d.id for d in (config.devices or [])]
    if ids:
        return ids
    if config.device_id:
        return [config.device_id]
    default = (
        db.query(WledDevice)
        .filter(WledDevice.is_default.is_(True))
        .order_by(WledDevice.id.asc())
        .first()
    )
    return [default.id] if default else []


def set_config_devices(
    db: Session, config: LedConfiguration, device_ids: Optional[list[int]]
) -> None:
    if device_ids is None:
        return
    unique_ids = list(dict.fromkeys(device_ids))
    devices = []
    if unique_ids:
        devices = (
            db.query(WledDevice).filter(WledDevice.id.in_(unique_ids)).all()
        )
        found = {d.id for d in devices}
        missing = set(unique_ids) - found
        if missing:
            raise ValueError(f"Dispositivos no encontrados: {sorted(missing)}")
    config.devices = devices
    config.device_id = devices[0].id if devices else None


def deactivate_conflicting(
    db: Session,
    config: LedConfiguration,
    *,
    except_id: Optional[int] = None,
) -> int:
    """
    Desactiva configs activas que compartan al menos un dispositivo destino.
    Así se pueden correr configs independientes en paralelo.
    """
    targets = set(resolve_target_device_ids(db, config))
    query = db.query(LedConfiguration).filter(LedConfiguration.status == 1)
    if except_id is not None:
        query = query.filter(LedConfiguration.id != except_id)
    deactivated = 0
    for other in query.all():
        other_targets = set(resolve_target_device_ids(db, other))
        # Si ambos sin destino explícito, chocan en el default
        if not targets and not other_targets:
            overlap = True
        else:
            overlap = bool(targets & other_targets)
        if overlap:
            other.status = 0
            deactivated += 1
    return deactivated


def activate_configuration(
    db: Session,
    config: LedConfiguration,
    actor: str,
) -> LedConfiguration:
    previous = config.status
    deactivate_conflicting(db, config, except_id=config.id)
    config.status = 1
    _add_log(
        db,
        configuration_id=config.id,
        action="activated",
        actor=actor,
        previous_status=previous,
        new_status=1,
        device_id=config.device_id,
        payload_snapshot=config.payload_json,
    )
    db.flush()
    return config


def create_configuration(
    db: Session,
    *,
    name: str,
    config_type: str,
    payload_json: dict[str, Any],
    user: User,
    device_id: Optional[int] = None,
    device_ids: Optional[list[int]] = None,
    description: Optional[str] = None,
    activate: bool = False,
) -> LedConfiguration:
    ids = list(device_ids or [])
    if device_id is not None and device_id not in ids:
        ids.append(device_id)

    config = LedConfiguration(
        name=name,
        config_type=config_type,
        payload_json=payload_json,
        status=0,
        created_by=user.id,
        description=description,
    )
    db.add(config)
    db.flush()
    set_config_devices(db, config, ids)

    if activate:
        activate_configuration(db, config, actor=user.username)
    else:
        _add_log(
            db,
            configuration_id=config.id,
            action="created",
            actor=user.username,
            previous_status=None,
            new_status=0,
            device_id=config.device_id,
            payload_snapshot=payload_json,
        )

    if activate:
        _add_log(
            db,
            configuration_id=config.id,
            action="created",
            actor=user.username,
            previous_status=None,
            new_status=1,
            device_id=config.device_id,
            payload_snapshot=payload_json,
        )

    db.commit()
    db.refresh(config)
    return config


def update_configuration(
    db: Session,
    config: LedConfiguration,
    *,
    user: User,
    name: Optional[str] = None,
    config_type: Optional[str] = None,
    payload_json: Optional[dict[str, Any]] = None,
    device_id: Optional[int] = None,
    device_ids: Optional[list[int]] = None,
    description: Optional[str] = None,
    activate: Optional[bool] = None,
) -> LedConfiguration:
    previous_status = config.status

    if name is not None:
        config.name = name
    if config_type is not None:
        config.config_type = config_type
    if payload_json is not None:
        config.payload_json = payload_json
    if description is not None:
        config.description = description

    if device_ids is not None or device_id is not None:
        ids = list(device_ids) if device_ids is not None else [d.id for d in config.devices]
        if device_id is not None and device_id not in ids:
            ids.append(device_id)
        if device_ids is not None:
            ids = list(device_ids)
            if device_id is not None and device_id not in ids:
                ids.append(device_id)
        set_config_devices(db, config, ids)

    if activate is True:
        activate_configuration(db, config, actor=user.username)
    elif activate is False:
        config.status = 0
        _add_log(
            db,
            configuration_id=config.id,
            action="deactivated",
            actor=user.username,
            previous_status=previous_status,
            new_status=0,
            device_id=config.device_id,
        )

    _add_log(
        db,
        configuration_id=config.id,
        action="updated",
        actor=user.username,
        previous_status=previous_status,
        new_status=config.status,
        device_id=config.device_id,
        payload_snapshot=config.payload_json,
    )

    db.commit()
    db.refresh(config)
    return config


def delete_configuration(db: Session, config: LedConfiguration, user: User) -> None:
    config_id = config.id
    _add_log(
        db,
        configuration_id=config_id,
        action="deleted",
        actor=user.username,
        previous_status=config.status,
        new_status=None,
        device_id=config.device_id,
        payload_snapshot=config.payload_json,
    )
    db.delete(config)
    db.commit()
