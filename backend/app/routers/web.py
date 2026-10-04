from pathlib import Path
import json

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_optional_user
from app.models import LedConfiguration, User, WledDevice
from app.security import create_access_token, verify_password
from app.services import configurations as cfg_service
from app.services import devices as device_service


def _require_user(user: User | None) -> User | RedirectResponse:
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return user

router = APIRouter(tags=["web"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Efectos documentados para TTGO / lora_rx (manual-json-lora.md)
WLED_EFFECTS = [
    (0, "Solid"),
    (1, "Blink"),
    (2, "Breathe"),
    (3, "Wipe"),
    (4, "Wipe Random"),
    (5, "Random Colors"),
    (6, "Sweep"),
    (7, "Dynamic"),
    (8, "Colorloop"),
    (9, "Rainbow"),
    (10, "Scan"),
    (11, "Scan Dual"),
    (12, "Fade"),
    (13, "Theater"),
    (14, "Theater Rainbow"),
    (15, "Running"),
]


def _hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
    color_hex = color_hex.lstrip("#")
    if len(color_hex) != 6:
        color_hex = "FF0000"
    return (
        int(color_hex[0:2], 16),
        int(color_hex[2:4], 16),
        int(color_hex[4:6], 16),
    )


def _build_segment(
    *,
    seg_id: int,
    fx: int,
    sx: int,
    ix: int,
    color_hex: str,
    start: int | None = None,
    stop: int | None = None,
) -> dict:
    r, g, b = _hex_to_rgb(color_hex)
    seg: dict = {"id": max(0, min(31, seg_id)), "fx": fx, "col": [[r, g, b]]}
    if start is not None:
        seg["start"] = max(0, int(start))
    if stop is not None:
        seg["stop"] = max(0, int(stop))
    if fx != 0:
        seg["sx"] = sx
    if ix not in (0, 128):
        seg["ix"] = ix
    return seg


def _build_payload(
    *,
    on: bool,
    bri: int,
    fx: int,
    sx: int,
    ix: int,
    color_hex: str,
    zones_raw: list[dict] | None = None,
) -> dict:
    # Contrato TTGO: JSON compacto. Varias zonas = varios seg con start/stop.
    # Máx. 5 segmentos de un color por paquete LoRa/AES.
    if zones_raw:
        segs: list[dict] = []
        for idx, zone in enumerate(zones_raw[:5]):
            try:
                start = int(zone.get("start", 0))
                stop = int(zone.get("stop", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Zona {idx}: start/stop inválidos") from exc
            if stop <= start:
                raise ValueError(f"Zona {idx}: stop debe ser mayor que start")
            try:
                z_fx = int(zone.get("fx", fx))
            except (TypeError, ValueError):
                z_fx = fx
            try:
                z_sx = int(zone.get("sx", sx))
            except (TypeError, ValueError):
                z_sx = sx
            color = str(zone.get("color", color_hex))
            segs.append(
                _build_segment(
                    seg_id=idx,
                    fx=z_fx,
                    sx=max(0, min(255, z_sx)),
                    ix=ix,
                    color_hex=color,
                    start=start,
                    stop=stop,
                )
            )
        if not segs:
            raise ValueError("Se requiere al menos una zona")
        return {"on": on, "bri": bri, "seg": segs}

    seg = _build_segment(
        seg_id=0, fx=fx, sx=sx, ix=ix, color_hex=color_hex
    )
    return {"on": on, "bri": bri, "seg": [seg]}


def _build_sequence_payload(
    *,
    steps_raw: list[dict],
    loop: bool,
    on: bool,
    default_bri: int,
    default_fx: int,
    default_sx: int,
    default_ix: int,
) -> dict:
    steps: list[dict] = []
    for step in steps_raw:
        color = str(step.get("color", "#ff0000"))
        try:
            duration_sec = float(step.get("duration_sec", 3))
        except (TypeError, ValueError):
            duration_sec = 3.0
        duration_ms = max(100, int(duration_sec * 1000))
        try:
            bri = int(step.get("bri", default_bri))
        except (TypeError, ValueError):
            bri = default_bri
        try:
            fx = int(step.get("fx", default_fx))
        except (TypeError, ValueError):
            fx = default_fx
        zones = step.get("zones")
        state = _build_payload(
            on=on,
            bri=max(1, min(255, bri)),
            fx=fx,
            sx=default_sx,
            ix=default_ix,
            color_hex=color,
            zones_raw=zones if isinstance(zones, list) else None,
        )
        steps.append({"duration_ms": duration_ms, "state": state})
    if not steps:
        raise ValueError("La secuencia requiere al menos un paso")
    return {"loop": loop, "steps": steps}


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash) or not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Usuario o contraseña incorrectos"},
            status_code=401,
        )

    token = create_access_token(
        subject=user.username,
        extra_claims={"role": user.role, "uid": user.id},
    )
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/",
    )
    return response


@router.post("/logout")
def logout_web():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token", path="/")
    return response


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth

    configs = (
        db.query(LedConfiguration).order_by(LedConfiguration.id.desc()).limit(50).all()
    )
    devices = db.query(WledDevice).order_by(WledDevice.id.asc()).all()
    actives = [c for c in configs if c.status == 1]
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": auth,
            "configs": configs,
            "devices": devices,
            "actives": actives,
            "effects": WLED_EFFECTS,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("err"),
        },
    )


@router.get("/devices", response_class=HTMLResponse)
def devices_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    devices = db.query(WledDevice).order_by(WledDevice.id.asc()).all()
    return templates.TemplateResponse(
        "devices.html",
        {
            "request": request,
            "user": auth,
            "devices": devices,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("err"),
        },
    )


@router.post("/devices")
def create_device_form(
    name: str = Form(...),
    ip_address: str = Form(...),
    notes: str = Form(""),
    is_default: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return RedirectResponse(
            url="/devices?err=Sin+permisos",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        device_service.create_device(
            db,
            name=name,
            ip_address=ip_address,
            is_default=is_default is not None,
            notes=notes.strip() or None,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/devices?err={str(exc).replace(' ', '+')[:80]}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url="/devices?msg=Dispositivo+creado",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/devices/{device_id}/update")
def update_device_form(
    device_id: int,
    name: str = Form(...),
    ip_address: str = Form(...),
    notes: str = Form(""),
    is_default: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return RedirectResponse(
            url="/devices?err=Sin+permisos",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    device = db.get(WledDevice, device_id)
    if not device:
        return RedirectResponse(
            url="/devices?err=No+encontrado",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        device_service.update_device(
            db,
            device,
            name=name,
            ip_address=ip_address,
            is_default=is_default is not None,
            notes=notes.strip() or None,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/devices?err={str(exc).replace(' ', '+')[:80]}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url="/devices?msg=Actualizado",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/devices/{device_id}/delete")
def delete_device_form(
    device_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return RedirectResponse(
            url="/devices?err=Sin+permisos",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    device = db.get(WledDevice, device_id)
    if device:
        device_service.delete_device(db, device)
    return RedirectResponse(
        url="/devices?msg=Eliminado",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/music", response_class=HTMLResponse)
def music_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    devices = db.query(WledDevice).order_by(WledDevice.id.asc()).all()
    return templates.TemplateResponse(
        "music.html",
        {
            "request": request,
            "user": auth,
            "devices": devices,
        },
    )


@router.post("/dashboard/configurations")
def create_from_form(
    name: str = Form(...),
    sequence_json: str = Form(""),
    description: str = Form(""),
    activate: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return RedirectResponse(
            url="/dashboard?err=Sin+permisos",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        parsed = json.loads(sequence_json) if sequence_json.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("la secuencia no es válida")
        payload = cfg_service.require_playlist_sequence(parsed)
        cfg_service.create_configuration(
            db,
            name=name.strip(),
            config_type="playlist",
            payload_json=payload,
            user=auth,
            description=description.strip() or None,
            activate=activate is not None,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return RedirectResponse(
            url=f"/dashboard?err={str(exc).replace(' ', '+')[:120]}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        url="/dashboard?msg=Configuraci%C3%B3n+creada",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/configurations/{config_id}/activate")
def activate_from_form(
    config_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return RedirectResponse(
            url="/dashboard?err=Sin+permisos",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    config = db.get(LedConfiguration, config_id)
    if not config:
        return RedirectResponse(
            url="/dashboard?err=No+encontrada",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    cfg_service.activate_configuration(db, config, actor=auth.username)
    db.commit()
    return RedirectResponse(
        url="/dashboard?msg=Configuraci%C3%B3n+activada",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/configurations/{config_id}/delete")
def delete_from_form(
    config_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return RedirectResponse(
            url="/dashboard?err=Sin+permisos",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    config = db.get(LedConfiguration, config_id)
    if config:
        cfg_service.delete_configuration(db, config, auth)
    return RedirectResponse(
        url="/dashboard?msg=Eliminada",
        status_code=status.HTTP_303_SEE_OTHER,
    )
