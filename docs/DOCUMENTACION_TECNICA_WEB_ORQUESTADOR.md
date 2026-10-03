# Control LEDs — Documentación técnica (Web + Orquestador)

> Documento orientado a transferencia de conocimiento a otra IA o desarrollador.  
> Alcance: **aplicativo web FastAPI** y **orquestador Python** que controlan **TTGO LoRa32 con WLED + usermod `lora_rx`** (y WLED genérico en claro si no hay llave AES).  
> Referencias de firmware: `WLEDOFICIAL/WLED/docs/ttgo_t32.md` y `WLEDOFICIAL/WLED/usermods/lora_rx/manual-json-lora.md`.

**Repo:** `jijunahe/controled`  
**Rama de trabajo habitual:** `feature/wled-control-system`  
**Dispositivo objetivo principal:** LilyGO TTGO LoRa32 (env `ttgo_t32`) con tira en GPIO 4  
**API HTTP:** `POST http://<IP>/json/state` — en claro o cifrado AES según `WLED_AES_KEY`

---

## 1. Propósito del sistema

Sistema de iluminación inteligente con tres capas:

1. **Panel web + API REST/WebSocket** (FastAPI) — crea/activa configuraciones LED y gestiona dispositivos.
2. **MySQL** (`control_leds`) — fuente de verdad compartida.
3. **Orquestador** (Python en Raspberry Pi) — hace polling de configs con `status = 1` y las aplica por HTTP a uno o varios WLED.

Flujo principal:

```
Usuario (móvil/PC)
    → FastAPI (JWT + panel Jinja)
        → MySQL (led_configurations status=1, destinos N:N)
            → Orquestador (Pi, poll ~2.5s)
                → POST /json/state  body={"aes":"<base64>"}  → TTGO WLED (1..N IPs)
```

Modo musical (baja latencia) **bypassea** el orquestador:

```
Usuario /music → WebSocket /ws/music → FastAPI → POST cifrado/claro → TTGO WLED
```

### Contrato AES / JSON (TTGO `lora_rx`)

Cuando la TTGO tiene llave en `/aes128.key` (32 hex en UI Usermods → `aes_key`):

1. El aplicativo construye un **estado WLED compacto** (solo `on`, `bri`, `ps`, `seg`…).
2. **No** se envían `loop`, `steps`, `duration_ms` (la secuencia la temporiza el orquestador/web).
3. Por **Wi‑Fi/HTTP** el plaintext cifrado es **JSON minificado** (no MessagePack).
4. Sobre binario: `0xA1 | nonce(12) | ciphertext | tag GCM(16)` → Base64.
5. Body HTTP: `{"aes":"<base64>"}`.
6. Por **LoRa** el plaintext sería MessagePack (emisor RF); este orquestador habla **Wi‑Fi**.

Variables:

| Variable | Dónde | Uso |
|---|---|---|
| `WLED_AES_KEY` | `orchestrator/.env` y `backend/.env` | 32 hex; vacío = HTTP en claro |
| `WLED_JSON_PATH` | ambos | default `/json/state` |
| `DRY_RUN` / `WLED_DRY_RUN` | orquestador / backend | no llama al hardware |

Módulos: `orchestrator/wled_aes.py`, `backend/app/services/wled_aes.py`.
---

## 2. Arquitectura de componentes

| Componente | Ubicación en repo | Runtime típico | Rol |
|---|---|---|---|
| Backend web/API | `backend/` | PC/servidor Linux, puerto `8765` | Auth, CRUD, panel, WebSocket musical |
| Orquestador | `orchestrator/` | Raspberry Pi 3 (systemd) | Polling MySQL → WLED |
| Esquema DB | `schema.sql` + `migrations/` | MySQL 8 | Persistencia |
| LoRa demo | `LORA/p1/` | TTGO LoRa32 | **Independiente**; no integra con este stack |

### Separación de responsabilidades

- **Web/API:** escribe estado deseado en DB; no habla con WLED salvo modo musical/WebSocket.
- **Orquestador:** único consumidor “batch” de `status=1` para estáticos/secuencias.
- **WLED:** ejecuta el estado LED real (`on`, `bri`, `seg`, efectos, etc.).

El orquestador **no** se instala en un módulo LoRa32/ESP32: requiere Linux + Python + cliente MySQL + proceso largo.

---

## 3. Estructura de directorios relevante

```
CONTROL LEDS/
├── schema.sql                          # Esquema base MySQL
├── migrations/002_multi_device.sql     # Multi-dispositivo (N:N + varias activas)
├── service.example                     # Unit systemd de ejemplo (orquestador)
├── README.md
├── backend/
│   ├── .env / .env.example
│   ├── requirements.txt
│   └── app/
│       ├── main.py                     # FastAPI app
│       ├── config.py                   # Settings (pydantic)
│       ├── database.py                 # SQLAlchemy engine/session
│       ├── security.py                 # JWT + bcrypt
│       ├── deps.py                     # get_current_user, roles
│       ├── models/                     # ORM
│       ├── schemas/                    # Pydantic I/O
│       ├── services/
│       │   ├── configurations.py       # Activación, conflictos, M2M devices
│       │   ├── devices.py              # CRUD dispositivos
│       │   └── wled_realtime.py        # POST WLED (modo musical)
│       ├── routers/
│       │   ├── auth.py                 # /api/auth/*
│       │   ├── configurations.py       # /api/configurations*, /api/devices*
│       │   ├── web.py                  # HTML panel
│       │   └── realtime.py             # WS /ws/music
│       ├── templates/                  # login, dashboard, devices, music
│       └── static/js/                  # dashboard.js, music.js
└── orchestrator/
    ├── .env / .env.example
    ├── requirements.txt
    ├── orchestrator.py                 # Loop principal + ThreadPool
    ├── settings.py
    ├── db.py                           # MySQL + resolución de IPs
    ├── runner.py                       # Estático/secuencia multi-IP
    └── wled.py                         # Cliente HTTP WLED
```

---

## 4. Modelo de datos MySQL (`control_leds`)

### 4.1 Tablas

| Tabla | Función |
|---|---|
| `users` | Cuentas panel/API (`admin`/`operator`/`viewer`), `password_hash` bcrypt |
| `wled_devices` | Gledopto/WLED: `name`, `ip_address`, `is_default`, notas |
| `led_configurations` | Configs LED: tipo, `payload_json`, `status` (0/1), `device_id` legado |
| `led_configuration_devices` | N:N config ↔ dispositivos (broadcast / multi-target) |
| `led_configuration_logs` | Auditoría: created/activated/applied/apply_failed… |
| `audio_sessions` | Sesiones WebSocket modo musical |

### 4.2 Semántica de `status` en `led_configurations`

| Valor | Significado |
|---|---|
| `1` | Activa / pendiente de aplicación (el orquestador debe procesarla) |
| `0` | Inactiva o ya procesada |

**Importante (post-migración 002):** pueden existir **varias** filas con `status=1` a la vez, si no comparten dispositivos destino. Antes existía `uk_led_one_active` (una sola activa global); se eliminó.

### 4.3 Resolución de destinos (IPs)

Orden de resolución (backend y orquestador alineados):

1. Filas en `led_configuration_devices` para esa config.
2. Si vacío: `led_configurations.device_id` (legado).
3. Si vacío: dispositivo con `is_default = 1`.
4. Si no hay default: `WLED_DEFAULT_IP` del `.env` del orquestador.

### 4.4 Activación con conflictos

Al activar una config C con destinos `{D1, D2, …}`:

- Se ponen en `status=0` otras configs activas cuyo conjunto de destinos **intersecta** con el de C.
- Configs a dispositivos disjuntos pueden quedar activas en paralelo (independientes).

Implementación: `backend/app/services/configurations.py` → `deactivate_conflicting()`.

### 4.5 Tipos de configuración (`config_type`)

Enum: `static` | `sequence` | `playlist` | `audio_reactive`

- **static:** un estado WLED directo en `payload_json`.
- **sequence / playlist:** `payload_json` con `steps[]` y opcional `loop`.
- **audio_reactive:** pensado para modo musical; el camino en tiempo real usa WebSocket, no el poll del orquestador.

---

## 5. Contratos de payload

### 5.1 Estado estático (compatible WLED `/json/state`)

```json
{
  "on": true,
  "bri": 160,
  "transition": 0,
  "seg": [
    {
      "id": 0,
      "fx": 0,
      "sx": 128,
      "ix": 128,
      "col": [[255, 0, 0], [0, 0, 0], [0, 0, 0]]
    }
  ]
}
```

### 5.2 Secuencia temporizada

```json
{
  "loop": true,
  "steps": [
    {
      "duration_ms": 3000,
      "state": {
        "on": true,
        "bri": 160,
        "seg": [{ "id": 0, "fx": 0, "col": [[255, 0, 0], [0, 0, 0], [0, 0, 0]] }]
      }
    },
    {
      "duration_ms": 2000,
      "state": {
        "on": true,
        "bri": 180,
        "seg": [{ "id": 0, "fx": 0, "col": [[0, 80, 255], [0, 0, 0], [0, 0, 0]] }]
      }
    }
  ]
}
```

Reglas del orquestador (`runner.py`):

- Si hay `steps`: ejecuta en orden; duerme `duration_ms` entre pasos (mínimo 100 ms).
- `loop: true` (o tipo sequence/playlist sin `loop` explícito false): repite hasta que `status` deje de ser 1.
- Sin `steps`: un solo POST y luego `status → 0`.
- Claves meta no se envían a WLED: `steps`, `loop`, `mode`, `repeat`, `name`.

### 5.3 Frame WebSocket musical (cliente → servidor)

```json
{ "type": "frame", "on": true, "bri": 200, "fx": 0, "col": [255, 40, 80], "transition": 0 }
```

También acepta `state` completo WLED o `burst` con lista de frames.  
Rate-limit servidor: `MUSIC_MAX_FPS` / `MUSIC_MIN_INTERVAL_MS`.

---

## 6. Aplicativo web (FastAPI)

### 6.1 Stack

- FastAPI + Uvicorn
- SQLAlchemy 2 + PyMySQL
- JWT (`python-jose`) + bcrypt (`passlib`)
- Jinja2 + Tailwind CDN (templates)
- httpx (POST async a WLED en modo musical)

Arranque típico:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Login demo: `admin` / `admin123`  
Docs OpenAPI: `/docs`

### 6.2 Variables de entorno (`backend/.env`)

| Variable | Uso |
|---|---|
| `SECRET_KEY` | Firma JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Expiración token |
| `DB_*` | Conexión MySQL |
| `WLED_DEFAULT_IP` | Fallback IP |
| `WLED_DRY_RUN` | Si `true`, WS musical no llama WLED real |
| `WLED_TIMEOUT_SECONDS` | Timeout HTTP a WLED |
| `MUSIC_MAX_FPS` / `MUSIC_MIN_INTERVAL_MS` | Throttle frames |

### 6.3 Autenticación

- `POST /api/auth/login` → `{ access_token, token_type }` + cookie `httponly` `access_token`.
- Endpoints API: Bearer o cookie.
- Roles: `admin`, `operator` (escritura), `viewer` (lectura).
- Web HTML: cookie; rutas protegidas redirigen a `/login`.

### 6.4 Rutas HTML (panel)

| Ruta | Función |
|---|---|
| `/login` | Login formulario |
| `/dashboard` | Crear/activar/borrar configs; multi-select dispositivos |
| `/devices` | CRUD Gledopto (nombre, IP, default) |
| `/music` | Modo musical micrófono / simulador BPM |

### 6.5 API REST principal

Prefijo `/api`. Casi todo requiere auth.

**Auth**

| Método | Ruta | Notas |
|---|---|---|
| POST | `/api/auth/login` | JWT + cookie |
| POST | `/api/auth/logout` | Borra cookie |
| GET | `/api/auth/me` | Usuario actual |

**Configuraciones**

| Método | Ruta | Notas |
|---|---|---|
| GET | `/api/configurations` | Filtros `status`, `config_type` |
| GET | `/api/configurations/active` | Lista de activas (`status=1`) |
| GET | `/api/configurations/{id}` | Detalle |
| POST | `/api/configurations` | Body: name, config_type, payload_json, `device_ids[]`, activate |
| PUT | `/api/configurations/{id}` | Update parcial + activate opcional |
| POST | `/api/configurations/{id}/activate` | Activa con lógica de conflicto |
| DELETE | `/api/configurations/{id}` | Borra |

**Dispositivos**

| Método | Ruta | Notas |
|---|---|---|
| GET | `/api/devices` | Lista |
| POST | `/api/devices` | Alta |
| PUT | `/api/devices/{id}` | Update; un solo `is_default=1` |
| DELETE | `/api/devices/{id}` | Baja |

**Health**

| GET | `/api/health` | Sin auth |

### 6.6 WebSocket musical `/ws/music`

- Auth: query `?token=<JWT>` o cookie `access_token`.
- Query opcional: `device_id`, `source` (`websocket` \| `mic_wled` \| `playlist_sim`).
- Al conectar: pausa cola orquestador (`status=0` en activas), crea `audio_sessions`.
- Mensajes cliente: `hello`, `frame`, `burst`, `ping`, `stop`.
- Mensajes servidor: `ready`, `ack`, `pong`, `error`, `stopped`.
- UI (`/music`): Web Audio (mic) o simulador BPM; envía frames ~22 fps cliente.

---

## 7. Orquestador (Raspberry Pi)

### 7.1 Stack

- Python 3 + venv
- `pymysql`, `requests`, `python-dotenv`
- Opcional: systemd (`service.example` / `controled-orchestrator.service`)

### 7.2 Variables (`orchestrator/.env`)

| Variable | Uso |
|---|---|
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL (suele ser IP del PC, no localhost de la Pi) |
| `WLED_DEFAULT_IP` | Fallback si no hay device |
| `WLED_TIMEOUT_SECONDS` | Timeout HTTP |
| `POLL_INTERVAL_SECONDS` | Ciclo de poll (default 2.5) |
| `DRY_RUN` | `true` = no llama WLED (solo log `[DRY_RUN]`); `false` = POST real |

**Crítico:** con `DRY_RUN=true` los logs muestran `[DRY_RUN] POST…` y **no** `WLED OK` / `WLED unreachable`.

### 7.3 Módulos

| Archivo | Responsabilidad |
|---|---|
| `orchestrator.py` | Loop, señales SIGINT/SIGTERM, `ThreadPoolExecutor` (hasta 8 workers) |
| `db.py` | `fetch_all_active()`, resolución IPs, `mark_applied` / `mark_failed_and_release`, logs |
| `runner.py` | Normaliza steps, loop, POST multi-IP en paralelo, sleep interruptible |
| `wled.py` | `POST http://{ip}/json/state` |
| `settings.py` | Carga `.env` |

### 7.4 Algoritmo del loop

Cada ~`POLL_INTERVAL_SECONDS`:

1. Limpia futures terminados.
2. `fetch_all_active()` → todas las configs `status=1`.
3. Por cada config sin worker activo → `executor.submit(runner.apply, cfg)`.
4. Duerme el intervalo (interruptible).

`runner.apply(config)`:

1. Normaliza a lista de pasos.
2. Por cada paso: si ya no está activa → aborta.
3. POST del `state` a **todas** las IPs destino (threads).
4. Espera `duration_ms` (chequeando `status` cada ≤0.5 s).
5. Si no hay loop → `mark_applied` (`status=0`, `applied_at`).
6. Si loop → repite hasta desactivación o fallo de red (en loop el fallo deja `status=1` para reintento).

### 7.5 Observabilidad actual

- Logs stdout/journald: inicio, apply, DRY_RUN/WLED OK/error, excepciones MySQL.
- Tabla `led_configuration_logs` (`applied`, `apply_failed`, …).
- **No hay** endpoint `/health` del orquestador ni métricas Prometheus.
- Campos `wled_devices.is_online` / `last_seen_at` existen pero **no se actualizan** automáticamente aún.

Ver logs en Pi:

```bash
journalctl -u controled-orchestrator -f
```

### 7.6 systemd (referencia)

Plantilla en `service.example`. Requisitos típicos:

- `User=` = usuario real de la Pi (ej. `walter`, no `pi` si no existe).
- Rutas absolutas correctas (Linux es case-sensitive: `CONTROL-LEDS` ≠ `CONTROl-LEDS`).
- `ExecStart` apunta al Python del `.venv` y a `orchestrator.py` absoluto.
- Errores comunes: `217/USER` (usuario inválido), `203/EXEC` (ruta/binario inexistente).

---

## 8. Despliegue de referencia

### 8.1 MySQL (servidor / PC de desarrollo)

- DB: `control_leds`
- Usuario app: `controled` (local y remoto `%` si la Pi conecta por LAN)
- `bind-address = 0.0.0.0` si hay clientes remotos
- Migración multi-device: `migrations/002_multi_device.sql`

### 8.2 Backend web

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ajustar
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Acceso LAN ejemplo: `http://<IP_PC>:8765/login`

### 8.3 Orquestador en Raspberry

```bash
cd orchestrator   # dentro del clone del repo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# DB_HOST=<IP_PC>, WLED_DEFAULT_IP=<IP_Gledopto>, DRY_RUN=false
python orchestrator.py
# o systemd enable --now controled-orchestrator
```

---

## 9. Flujos de usuario (comportamiento esperado)

### A) Estático a un dispositivo

1. Crear dispositivo en `/devices` con IP real.
2. En `/dashboard`, crear config `static`, marcar ese dispositivo, activar.
3. Orquestador ve `status=1`, POST una vez, `status=0`.

### B) Misma info a varios (broadcast)

1. Marcar varios `device_ids` en la config.
2. Orquestador hace fan-out del mismo `state` a todas las IPs.

### C) Independiente en paralelo

1. Config A → dispositivo 1, activa.
2. Config B → dispositivo 2, activa.
3. Ambas pueden quedar `status=1`; workers distintos las aplican.

### D) Secuencia con tiempos

1. Tipo `sequence`, pasos color+duración, `loop` opcional.
2. Orquestador recorre steps; con loop sigue hasta activar otra config conflictiva o desactivar.

### E) Modo musical

1. `/music` → Conectar → Mic o Simulador.
2. Frames por WS; FastAPI POST directo a WLED.
3. Cola del orquestador se pausa al abrir la sesión WS.

---

## 10. Invariantes y restricciones para una IA que mantenga el código

1. **No** enviar a WLED claves meta (`steps`, `loop`, etc.).
2. **No** asumir una sola config `status=1` global (multi-device).
3. Al activar, **siempre** desactivar solo configs con destinos en conflicto.
4. Mantener sincronizado `device_id` legado con el primer elemento de `device_ids` cuando sea posible.
5. Orquestador y backend deben resolver IPs con la misma prioridad (M2M → legado → default → env).
6. `DRY_RUN` / `WLED_DRY_RUN` en `true` implica sin I/O real a hardware.
7. Modo musical y orquestador no deben pelear: WS limpia `status=1` al iniciar sesión.
8. No portar el orquestador a ESP32/LoRa32; es proceso Linux.
9. Credenciales van en `.env` (gitignored); no commitear secretos.
10. Puerto web de referencia en este entorno: **8765** (8000/8088 pueden estar ocupados por Docker).

---

## 11. Credenciales y datos de desarrollo (no producción)

| Recurso | Valor de referencia |
|---|---|
| Usuario panel | `admin` / `admin123` |
| Usuario MySQL app | `controled` / `controled_dev_1251` |
| DB | `control_leds` |
| JWT demo | vía `SECRET_KEY` en `backend/.env` |

Cambiar secretos antes de exponer a redes no confiables.

---

## 12. Relación con otros módulos del repo

| Carpeta | Relación |
|---|---|
| `LORA/p1` | Firmware LoRa TTGO independiente (LED GPIO25). **No** habla con MySQL/orquestador/WLED Gledopto. |
| `WLEDOFICIAL/` | Código fuente WLED upstream; no es dependencia runtime de este stack. |

Posible evolución futura (no implementada): bridge gateway LoRa ↔ órdenes del orquestador/WLED.

---

## 13. Checklist de diagnóstico rápido

| Síntoma | Causas típicas |
|---|---|
| Panel no abre desde el móvil | Uvicorn en `127.0.0.1` (usar `--host 0.0.0.0`); distinta Wi‑Fi |
| Orquestador no aplica | `status` no es 1; Pi sin ruta a MySQL; servicio caído |
| Solo logs `[DRY_RUN]` | `DRY_RUN=true` en orquestador |
| `203/EXEC` systemd | Ruta Python/venv incorrecta o case del path |
| `217/USER` systemd | `User=` inexistente |
| WLED no cambia | IP mal en `wled_devices`; timeout; Gledopto offline; dry-run |
| Dos configs pelean | Comparten `device_id`/IPs → activación desactiva la otra |

---

## 14. Archivos clave para lectura prioritaria por una IA

1. `backend/app/main.py`
2. `backend/app/services/configurations.py`
3. `backend/app/routers/configurations.py`
4. `backend/app/routers/realtime.py`
5. `backend/app/routers/web.py`
6. `orchestrator/orchestrator.py`
7. `orchestrator/runner.py`
8. `orchestrator/db.py`
9. `schema.sql` + `migrations/002_multi_device.sql`
10. `README.md`

---

*Última actualización alineada al estado del repo en la rama `feature/wled-control-system` (web v0.4 + orquestador multi-device).*
