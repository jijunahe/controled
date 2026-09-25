from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import auth, configurations, web

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="API y panel para control WLED (Gledopto GL-C-016WL-D)",
    version="0.2.0",
)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth.router)
app.include_router(configurations.router)
app.include_router(web.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}
