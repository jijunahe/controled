from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import WledDevice


def clear_other_defaults(db: Session, *, except_id: int | None = None) -> None:
    query = db.query(WledDevice).filter(WledDevice.is_default.is_(True))
    if except_id is not None:
        query = query.filter(WledDevice.id != except_id)
    query.update({WledDevice.is_default: False}, synchronize_session=False)


def create_device(
    db: Session,
    *,
    name: str,
    ip_address: str,
    mac_address: str | None = None,
    is_default: bool = False,
    notes: str | None = None,
) -> WledDevice:
    if is_default:
        clear_other_defaults(db)
    # Si es el primero, forzar default
    count = db.query(WledDevice).count()
    if count == 0:
        is_default = True

    device = WledDevice(
        name=name.strip(),
        ip_address=ip_address.strip(),
        mac_address=mac_address,
        is_default=is_default,
        notes=notes,
    )
    db.add(device)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("IP o datos duplicados") from exc
    db.refresh(device)
    return device


def update_device(
    db: Session,
    device: WledDevice,
    *,
    name: str | None = None,
    ip_address: str | None = None,
    mac_address: str | None = None,
    is_default: bool | None = None,
    notes: str | None = None,
    is_online: bool | None = None,
) -> WledDevice:
    if name is not None:
        device.name = name.strip()
    if ip_address is not None:
        device.ip_address = ip_address.strip()
    if mac_address is not None:
        device.mac_address = mac_address
    if notes is not None:
        device.notes = notes
    if is_online is not None:
        device.is_online = is_online
    if is_default is True:
        clear_other_defaults(db, except_id=device.id)
        device.is_default = True
    elif is_default is False:
        device.is_default = False

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("IP o datos duplicados") from exc
    db.refresh(device)
    return device


def delete_device(db: Session, device: WledDevice) -> None:
    was_default = device.is_default
    db.delete(device)
    db.commit()
    if was_default:
        next_dev = db.query(WledDevice).order_by(WledDevice.id.asc()).first()
        if next_dev:
            next_dev.is_default = True
            db.commit()
