from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import LedConfiguration, LedConfigurationLog, User


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


def deactivate_all(db: Session, *, except_id: Optional[int] = None) -> int:
    """Pone status=0 en configuraciones activas (opcionalmente excluye una)."""
    query = db.query(LedConfiguration).filter(LedConfiguration.status == 1)
    if except_id is not None:
        query = query.filter(LedConfiguration.id != except_id)
    return query.update({LedConfiguration.status: 0}, synchronize_session=False)


def activate_configuration(
    db: Session,
    config: LedConfiguration,
    actor: str,
) -> LedConfiguration:
    """Activa una configuración (status=1) y desactiva el resto."""
    previous = config.status
    deactivate_all(db, except_id=config.id)
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
    description: Optional[str] = None,
    activate: bool = False,
) -> LedConfiguration:
    if activate:
        deactivate_all(db)

    config = LedConfiguration(
        name=name,
        config_type=config_type,
        payload_json=payload_json,
        status=1 if activate else 0,
        device_id=device_id,
        created_by=user.id,
        description=description,
    )
    db.add(config)
    db.flush()

    _add_log(
        db,
        configuration_id=config.id,
        action="created",
        actor=user.username,
        previous_status=None,
        new_status=config.status,
        device_id=device_id,
        payload_snapshot=payload_json,
    )
    if activate:
        _add_log(
            db,
            configuration_id=config.id,
            action="activated",
            actor=user.username,
            previous_status=0,
            new_status=1,
            device_id=device_id,
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
    if device_id is not None:
        config.device_id = device_id
    if description is not None:
        config.description = description

    if activate is True:
        deactivate_all(db, except_id=config.id)
        config.status = 1
    elif activate is False:
        config.status = 0

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
    if activate is True and previous_status != 1:
        _add_log(
            db,
            configuration_id=config.id,
            action="activated",
            actor=user.username,
            previous_status=previous_status,
            new_status=1,
            device_id=config.device_id,
            payload_snapshot=config.payload_json,
        )
    elif activate is False and previous_status == 1:
        _add_log(
            db,
            configuration_id=config.id,
            action="deactivated",
            actor=user.username,
            previous_status=previous_status,
            new_status=0,
            device_id=config.device_id,
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
