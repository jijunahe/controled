# Firmware Receptor LoRa con Sincronización

Firmware para TTGO LoRa32 V2.1.6 que recibe comandos de playlist por LoRa y los envía a un WLED vía HTTP.

## Características

- **Sincronización de dos fases**: Todos los receptores ejecutan simultáneamente
- **Modo legacy compatible**: Funciona con orquestadores sin sincronización
- **Display OLED**: Muestra estadísticas y estado en tiempo real
- **Timeout automático**: Descarta comandos pendientes después de 5 segundos

## Configuración

### 1. Credenciales WiFi

Editar `platformio.ini` o compilar con flags:

```bash
pio run -e ttgo-lora32-v21 \
  -DWIFI_SSID=\"MiRed\" \
  -DWIFI_PASS=\"MiPassword\" \
  -DWLED_IP=\"192.168.1.100\"
```

### 2. Compilar y subir

```bash
cd firmware_receptor
pio run -e ttgo-lora32-v21 -t upload
```

### 3. Monitor serial

```bash
pio device monitor -b 115200
```

## Protocolo de sincronización

### Modo Legacy (compatible con versiones anteriores)
```json
{"playlist": 5}
```
Ejecuta inmediatamente al recibir.

### Modo Sincronizado

**Fase 1 - PREPARE:**
```json
{"playlist": 5, "sync": 1, "seq": 12345}
```
El receptor almacena el comando pero NO lo ejecuta.

**Fase 2 - EXECUTE:**
```json
{"exec": 12345}
```
El receptor ejecuta el comando almacenado.

## Display OLED

El display muestra:
- **Línea 1**: "LoRa Receptor SYNC"
- **Línea 2**: RX (recibidos) / EX (ejecutados) / SY (sincronizados)
- **Línea 3**: Estado WiFi
- **Línea 4**: Comando pendiente o "Esperando..."

## Solución de problemas

### No conecta WiFi
- Verificar SSID y contraseña
- Comprobar que la red está en rango
- El firmware reintenta 20 veces antes de continuar sin WiFi

### No ejecuta comandos
- Verificar que la IP del WLED es correcta
- Comprobar que el WLED está encendido y en la misma red
- Revisar el monitor serial para errores HTTP

### Los dispositivos no están sincronizados
- Aumentar `LORA_SYNC_DELAY_MS` en el orquestador (probar 400-500ms)
- Verificar que todos los receptores tienen el mismo firmware
- Comprobar la calidad de señal LoRa

## Configuración de radio

| Parámetro | Valor |
|-----------|-------|
| Frecuencia | 915 MHz |
| Ancho de banda | 125 kHz |
| Spreading Factor | 9 |
| Coding Rate | 4/7 |
| Sync Word | 0x12 |
| CRC | Habilitado |

Estos valores deben coincidir con el transmisor (`WLEDOFICIAL/LORA PI/firmware/`).
