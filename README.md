# Control LEDs

Sistema de iluminación inteligente con **Gledopto GL-C-016WL-D (WLED)** y Raspberry Pi 3.

## Fases

1. Esquema MySQL (`schema.sql`) ✅
2. Backend FastAPI + JWT + panel web ✅
3. Orquestador (polling MySQL → WLED HTTP API)
4. WebSockets modo musical / audio-reactivo

## Base de datos

```bash
sudo mysql < schema.sql
```

Usuario de aplicación (desarrollo): `controled` / ver `backend/.env.example`.

## Backend (fase 2)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ajustar si hace falta
uvicorn app.main:app --reload --host 0.0.0.0 --port 8765
```

> Nota: en este equipo los puertos 8000/8088 suelen estar ocupados por Docker; usa `8765` u otro libre.

- Panel: http://localhost:8765/
- API docs: http://localhost:8765/docs
- Login demo: `admin` / `admin123`

### Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/auth/login` | JWT + cookie |
| GET | `/api/auth/me` | Usuario actual |
| GET/POST | `/api/configurations` | Listar / crear |
| PUT/DELETE | `/api/configurations/{id}` | Actualizar / borrar |
| POST | `/api/configurations/{id}/activate` | `status=1` (resto a 0) |
| GET | `/api/devices` | Dispositivos WLED |
