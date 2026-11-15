from pathlib import Path
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.catalog import PATTERN_CATALOG, QUICK_EFFECTS, catalog_groups
from app.models import LedConfiguration, LedPreset, User, WledDevice
from app.presets_catalog import PRESET_CATALOG
from app.database import get_db
from app.deps import get_optional_user
from app.services import heartbeat as heartbeat_service
from app.services import simulation as simulation_service
from app.services import schedule as schedule_service
from app.services.schedule import DAY_LABELS
from app.security import create_access_token, verify_password
from app.services import configurations as cfg_service
from app.services import devices as device_service
from app.services.lora_air import color_for_editor


def _preset_view(db: Session) -> list[dict]:
    catalog = [{"id": pid, "name": name, "kind": kind} for pid, name, kind in PRESET_CATALOG]
    try:
        rows = db.query(LedPreset).order_by(LedPreset.id.asc()).all()
        if not rows:
            for item in catalog:
                db.add(LedPreset(id=item["id"], name=item["name"], kind=item["kind"]))
            db.commit()
            rows = db.query(LedPreset).order_by(LedPreset.id.asc()).all()
        return [{"id": row.id, "name": row.name, "kind": row.kind} for row in rows]
    except SQLAlchemyError:
        db.rollback()
        return catalog


def _schedule_view(db: Session) -> dict:
    try:
        paused = schedule_service.is_paused(db)
        schedule = schedule_service.load_schedule(db)
        return {
            "paused": paused,
            "schedule": schedule,
            "enabled": bool(schedule and schedule.enabled),
            "rows": schedule_service.interval_rows(schedule),
            "note": schedule_service.describe_now(paused, schedule),
            "error": None,
        }
    except SQLAlchemyError:
        db.rollback()
        return {
            "paused": False,
            "schedule": None,
            "enabled": False,
            "rows": [],
            "note": "",
            "error": "Falta crear las tablas del horario en la base de datos.",
        }


def _operator(user: User | None) -> User | RedirectResponse:
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return RedirectResponse(
            url="/dashboard?err=Sin+permisos",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return auth


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
    nodes_online = 0
    try:
        nodes_online = sum(1 for beat in heartbeat_service.list_beats(db) if beat["alive"])
    except SQLAlchemyError:
        db.rollback()
    editing = None
    edit_boot = None
    edit_raw = request.query_params.get("edit")
    if edit_raw and edit_raw.isdigit():
        editing = db.get(LedConfiguration, int(edit_raw))
        if editing is not None:
            source = editing.payload_json if isinstance(editing.payload_json, dict) else {}
            if editing.config_type == "static":
                try:
                    source = color_for_editor(source)
                except (ValueError, TypeError):
                    source = {}
            edit_boot = {
                "id": editing.id,
                "name": editing.name,
                "description": editing.description or "",
                "type": "color" if editing.config_type == "static" else "playlist",
                "payload": source,
            }
    schedule_view = _schedule_view(db)
    if schedule_view["error"]:
        playing = {"on": False, "name": "—", "via": "Sin horario"}
    else:
        playing = schedule_service.playing_now(
            db, schedule_view["paused"], schedule_view["schedule"]
        )
    presets = _preset_view(db)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": auth,
            "configs": configs,
            "nodes_online": nodes_online,
            "playing": playing,
            "effects": WLED_EFFECTS,
            "editing": editing,
            "edit_boot": edit_boot,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("err"),
            "pattern_groups": catalog_groups(),
            "pattern_catalog": PATTERN_CATALOG,
            "quick_effects": QUICK_EFFECTS,
            "day_labels": DAY_LABELS,
            "schedule": schedule_view["schedule"],
            "schedule_rows": schedule_view["rows"],
            "schedule_enabled": schedule_view["enabled"],
            "paused": schedule_view["paused"],
            "schedule_note": schedule_view["note"],
            "schedule_error": schedule_view["error"],
            "schedule_choices": (
                db.query(LedConfiguration).order_by(LedConfiguration.name.asc()).all()
            ),
            "presets": presets,
            "preset_by_id": {item["id"]: item["name"] for item in presets},
        },
    )


@router.get("/devices", response_class=HTMLResponse)
def devices_page(
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


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


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    schedule_view = _schedule_view(db)
    editing = None
    edit_raw = request.query_params.get("edit")
    if edit_raw and edit_raw.isdigit():
        edit_id = int(edit_raw)
        editing = next((row for row in schedule_view["rows"] if row["id"] == edit_id), None)
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "user": auth,
            "day_labels": DAY_LABELS,
            "schedule": schedule_view["schedule"],
            "schedule_rows": schedule_view["rows"],
            "schedule_enabled": schedule_view["enabled"],
            "schedule_note": schedule_view["note"],
            "schedule_error": schedule_view["error"],
            "schedule_choices": (
                db.query(LedConfiguration).order_by(LedConfiguration.name.asc()).all()
            ),
            "editing": editing,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("err"),
        },
    )


@router.get("/simulacion", response_class=HTMLResponse)
def simulation_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    return templates.TemplateResponse(
        "simulacion.html",
        {
            "request": request,
            "user": auth,
            "scene": simulation_service.current_scene(db),
        },
    )


@router.get("/simulacion/datos")
def simulation_data(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    return JSONResponse(simulation_service.current_scene(db))


@router.get("/vida", response_class=HTMLResponse)
def vida_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    beats: list[dict] = []
    heartbeat_error = None
    try:
        beats = heartbeat_service.list_beats(db)
    except SQLAlchemyError:
        db.rollback()
        heartbeat_error = "Falta crear la tabla del bit de vida en la base de datos."
    return templates.TemplateResponse(
        "vida.html",
        {
            "request": request,
            "user": auth,
            "beats": beats,
            "heartbeat_error": heartbeat_error,
        },
    )


@router.get("/music", response_class=HTMLResponse)
def music_page(
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


def _form_error(message: str, edit_id: int | None = None, *, next_path: str = "/dashboard") -> RedirectResponse:
    target = next_path + "?err=" + quote(message[:180])
    if edit_id is not None:
        target += f"&edit={edit_id}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)


def _payload_from_form(effect_type: str, sequence_json: str, color_json: str) -> tuple[str, dict]:
    if effect_type == "color":
        parsed = json.loads(color_json) if color_json.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("el efecto de color no es válido")
        return "static", parsed
    parsed = json.loads(sequence_json) if sequence_json.strip() else {}
    if not isinstance(parsed, dict):
        raise ValueError("la secuencia no es válida")
    return "playlist", parsed


@router.post("/dashboard/configurations")
def create_from_form(
    name: str = Form(...),
    effect_type: str = Form("playlist"),
    sequence_json: str = Form(""),
    color_json: str = Form(""),
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
        config_type, payload = _payload_from_form(effect_type, sequence_json, color_json)
        cfg_service.create_configuration(
            db,
            name=name.strip(),
            config_type=config_type,
            payload_json=payload,
            user=auth,
            description=description.strip() or None,
            activate=activate is not None,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return _form_error(str(exc))

    return RedirectResponse(
        url="/dashboard?msg=Configuraci%C3%B3n+creada",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/configurations/{config_id}/update")
def update_from_form(
    config_id: int,
    name: str = Form(...),
    effect_type: str = Form("playlist"),
    sequence_json: str = Form(""),
    color_json: str = Form(""),
    description: str = Form(""),
    activate: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _require_user(user)
    if isinstance(auth, RedirectResponse):
        return auth
    if auth.role == "viewer":
        return _form_error("Sin permisos", config_id)
    config = db.get(LedConfiguration, config_id)
    if not config:
        return _form_error("No encontrada")
    try:
        config_type, payload = _payload_from_form(effect_type, sequence_json, color_json)
        cfg_service.update_configuration(
            db,
            config,
            user=auth,
            name=name.strip(),
            config_type=config_type,
            payload_json=payload,
            description=description.strip() or None,
            activate=True if activate is not None else None,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return _form_error(str(exc), config_id)
    return RedirectResponse(
        url="/dashboard?msg=Configuraci%C3%B3n+actualizada",
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


@router.post("/dashboard/configurations/{config_id}/deactivate")
def deactivate_from_form(
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
    cfg_service.update_configuration(db, config, user=auth, activate=False)
    return RedirectResponse(
        url="/dashboard?msg=Configuraci%C3%B3n+desactivada",
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


@router.post("/dashboard/power/off")
def power_off(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _operator(user)
    if isinstance(auth, RedirectResponse):
        return auth
    try:
        schedule_service.set_paused(db, True)
    except SQLAlchemyError:
        db.rollback()
        return _form_error("No se pudo guardar el apagado")
    return RedirectResponse(
        url="/dashboard?msg=Luces+apagadas.+El+horario+queda+en+pausa",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/power/on")
def power_on(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _operator(user)
    if isinstance(auth, RedirectResponse):
        return auth
    try:
        schedule_service.set_paused(db, False)
    except SQLAlchemyError:
        db.rollback()
        return _form_error("No se pudo encender")
    return RedirectResponse(
        url="/dashboard?msg=Horario+reanudado",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/schedule/enabled")
def schedule_enabled(
    enabled: str = Form("0"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _operator(user)
    if isinstance(auth, RedirectResponse):
        return auth
    try:
        schedule_service.set_enabled(db, enabled == "1")
    except SQLAlchemyError:
        db.rollback()
        return _form_error("No se pudo cambiar el horario", next_path="/schedule")
    text = "Horario+activado" if enabled == "1" else "Horario+en+modo+manual"
    return RedirectResponse(
        url=f"/schedule?msg={text}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/schedule/intervals")
def schedule_add_interval(
    start_time: str = Form(...),
    end_time: str = Form(...),
    configuration_id: int = Form(...),
    day_0: str | None = Form(None),
    day_1: str | None = Form(None),
    day_2: str | None = Form(None),
    day_3: str | None = Form(None),
    day_4: str | None = Form(None),
    day_5: str | None = Form(None),
    day_6: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _operator(user)
    if isinstance(auth, RedirectResponse):
        return auth
    days = [
        index
        for index, flag in enumerate((day_0, day_1, day_2, day_3, day_4, day_5, day_6))
        if flag
    ]
    try:
        schedule_service.add_interval(
            db,
            days=days,
            start=schedule_service.parse_clock(start_time),
            end=schedule_service.parse_clock(end_time),
            configuration_id=configuration_id,
        )
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "No se pudo guardar el intervalo"
        return _form_error(message, next_path="/schedule")
    return RedirectResponse(
        url="/schedule?msg=Horario+agregado",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/schedule/intervals/{interval_id}")
def schedule_update_interval(
    interval_id: int,
    start_time: str = Form(...),
    end_time: str = Form(...),
    configuration_id: int = Form(...),
    day_0: str | None = Form(None),
    day_1: str | None = Form(None),
    day_2: str | None = Form(None),
    day_3: str | None = Form(None),
    day_4: str | None = Form(None),
    day_5: str | None = Form(None),
    day_6: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _operator(user)
    if isinstance(auth, RedirectResponse):
        return auth
    days = [
        index
        for index, flag in enumerate((day_0, day_1, day_2, day_3, day_4, day_5, day_6))
        if flag
    ]
    try:
        schedule_service.update_interval(
            db,
            interval_id,
            days=days,
            start=schedule_service.parse_clock(start_time),
            end=schedule_service.parse_clock(end_time),
            configuration_id=configuration_id,
        )
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "No se pudo guardar el horario"
        return _form_error(message, edit_id=interval_id, next_path="/schedule")
    return RedirectResponse(
        url="/schedule?msg=Horario+actualizado",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/schedule/intervals/{interval_id}/enabled")
def schedule_interval_enabled(
    interval_id: int,
    enabled: str = Form("0"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _operator(user)
    if isinstance(auth, RedirectResponse):
        return auth
    try:
        schedule_service.set_interval_enabled(db, interval_id, enabled == "1")
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "No se pudo cambiar el horario"
        return _form_error(message, next_path="/schedule")
    text = "Horario+activado" if enabled == "1" else "Horario+desactivado"
    return RedirectResponse(
        url=f"/schedule?msg={text}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/dashboard/schedule/intervals/{interval_id}/delete")
def schedule_delete_interval(
    interval_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    auth = _operator(user)
    if isinstance(auth, RedirectResponse):
        return auth
    try:
        schedule_service.delete_interval(db, interval_id)
    except SQLAlchemyError:
        db.rollback()
        return _form_error("No se pudo eliminar el horario", next_path="/schedule")
    return RedirectResponse(
        url="/schedule?msg=Horario+eliminado",
        status_code=status.HTTP_303_SEE_OTHER,
    )
