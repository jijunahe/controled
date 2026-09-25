from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_optional_user
from app.models import LedConfiguration, User, WledDevice
from app.security import create_access_token, verify_password
from app.services import configurations as cfg_service


def _require_user(user: User | None) -> User | RedirectResponse:
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return user

router = APIRouter(tags=["web"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Efectos WLED frecuentes para el formulario
WLED_EFFECTS = [
    (0, "Solid"),
    (1, "Blink"),
    (2, "Breathe"),
    (3, "Wipe"),
    (5, "Color Wipe"),
    (9, "Scan"),
    (12, "Fade"),
    (15, "Theater"),
    (23, "Rainbow"),
    (27, "Android"),
    (38, "Fire 2012"),
    (42, "Aurora"),
    (43, "Noise 1"),
    (46, "Plasma"),
    (57, "Lightning"),
    (71, "Pacifica"),
    (75, "Sunrise"),
    (101, "Phased"),
    (115, "Blends"),
]


def _build_payload(
    *,
    on: bool,
    bri: int,
    fx: int,
    sx: int,
    ix: int,
    color_hex: str,
) -> dict:
    color_hex = color_hex.lstrip("#")
    if len(color_hex) != 6:
        color_hex = "FF0000"
    r = int(color_hex[0:2], 16)
    g = int(color_hex[2:4], 16)
    b = int(color_hex[4:6], 16)
    return {
        "on": on,
        "bri": bri,
        "seg": [
            {
                "id": 0,
                "fx": fx,
                "sx": sx,
                "ix": ix,
                "col": [[r, g, b], [0, 0, 0], [0, 0, 0]],
            }
        ],
    }


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
    active = next((c for c in configs if c.status == 1), None)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": auth,
            "configs": configs,
            "devices": devices,
            "active": active,
            "effects": WLED_EFFECTS,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("err"),
        },
    )


@router.post("/dashboard/configurations")
def create_from_form(
    name: str = Form(...),
    config_type: str = Form("static"),
    description: str = Form(""),
    device_id: str = Form(""),
    bri: int = Form(128),
    fx: int = Form(0),
    sx: int = Form(128),
    ix: int = Form(128),
    color: str = Form("#ff0000"),
    on: str | None = Form(None),
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

    resolved_device_id = int(device_id) if device_id.strip().isdigit() else None
    payload = _build_payload(
        on=on is not None,
        bri=max(1, min(255, bri)),
        fx=fx,
        sx=max(0, min(255, sx)),
        ix=max(0, min(255, ix)),
        color_hex=color,
    )
    cfg_service.create_configuration(
        db,
        name=name.strip(),
        config_type=config_type,
        payload_json=payload,
        user=auth,
        device_id=resolved_device_id,
        description=description.strip() or None,
        activate=activate is not None,
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
