# CONTROL LEDS

Sistema de iluminación inteligente con Gledopto GL-C-016WL-D (WLED) y Raspberry Pi 3.

## Fases

1. Esquema MySQL (`schema.sql`)
2. Backend FastAPI + JWT + panel web
3. Orquestador (polling MySQL → WLED HTTP API)
4. WebSockets modo musical / audio-reactivo

## Base de datos

```bash
sudo mysql < schema.sql
```

Base: `control_leds`
