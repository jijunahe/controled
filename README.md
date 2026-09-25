# Control LEDs

Sistema de iluminación inteligente con **Gledopto GL-C-016WL-D (WLED)** y Raspberry Pi 3.

## Fases

1. Esquema MySQL (`schema.sql`) ✅
2. Backend FastAPI + JWT + panel web ✅
3. Orquestador (polling MySQL → WLED HTTP API) ✅
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

### Secuencias (colores con tiempo)

En el panel elige tipo **sequence** o **playlist**, agrega pasos (color + duración en segundos) y opcionalmente **Repetir en bucle**.

Payload ejemplo:

```json
{
  "loop": true,
  "steps": [
    {
      "duration_ms": 3000,
      "state": { "on": true, "bri": 160, "seg": [{ "id": 0, "fx": 0, "col": [[255,0,0],[0,0,0],[0,0,0]] }] }
    },
    {
      "duration_ms": 5000,
      "state": { "on": true, "bri": 180, "seg": [{ "id": 0, "fx": 0, "col": [[0,0,255],[0,0,0],[0,0,0]] }] }
    }
  ]
}
```

## Orquestador (fase 3) — Raspberry Pi

```bash
cd orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Editar WLED_DEFAULT_IP y poner DRY_RUN=false cuando el Gledopto esté en red
python orchestrator.py
```

Comportamiento:

1. Polling cada ~2.5 s a MySQL buscando `status = 1`
2. Envía `payload_json` a `http://<IP>/json/state`
3. Estático / secuencia sin loop: al terminar → `status = 0`
4. Secuencia con `loop: true`: repite hasta que actives otra configuración

Servicio systemd (opcional): ver `orchestrator/controled-orchestrator.service`.
