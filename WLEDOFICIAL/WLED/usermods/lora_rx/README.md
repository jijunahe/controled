# LoRa RX Usermod con Sincronización

Usermod para WLED que recibe comandos de playlist vía LoRa con soporte para **ejecución sincronizada** en múltiples dispositivos.

## Problema que resuelve

Cuando el orquestador envía un comando por LoRa a múltiples TTGO32, cada dispositivo lo ejecuta en el momento que lo recibe. Debido a variaciones en:
- Tiempo de propagación del mensaje
- Tiempo de procesamiento del microcontrolador

Los dispositivos pueden ejecutar el mismo efecto con **hasta 1 segundo de diferencia**, lo cual es muy notable en playlists con efectos.

## Solución: Protocolo de dos fases

1. **Fase 1 (PREPARE)**: El orquestador envía el comando completo con un ID de secuencia. Los receptores **almacenan pero NO ejecutan**.

2. **Fase 2 (EXECUTE)**: Después de un delay configurable (ej. 300ms), el orquestador envía un comando "ejecutar". **Todos los receptores ejecutan simultáneamente**.

## Formato de mensajes

### Modo Legacy (sin sincronización)
```json
{"playlist": 5}
```
El receptor ejecuta inmediatamente al recibir.

### Modo Sincronizado
**Fase 1 - PREPARE:**
```json
{"playlist": 5, "sync": 1, "seq": 12345}
```

**Fase 2 - EXECUTE:**
```json
{"exec": 12345}
```

## Instalación

### 1. Copiar el usermod
Copia `usermod_lora_rx.h` a tu carpeta `wled00/` o `usermods/`.

### 2. Registrar en usermods_list.cpp
```cpp
#include "../usermods/lora_rx/usermod_lora_rx.h"
// ...
usermods.add(new LoRaRxUsermod());
```

### 3. Configurar pines (platformio_override.ini)
```ini
build_flags = 
  -D LORA_RX_CS=18
  -D LORA_RX_DIO0=26
  -D LORA_RX_RST=23
  -D LORA_RX_FREQUENCY=915.0
```

### 4. Añadir dependencia RadioLib
```ini
lib_deps =
  jgromes/RadioLib@^6.4.0
```

## Configuración del Orquestador

En el archivo `.env` del orquestador:

```bash
# Habilitar sincronización
LORA_SYNC_ENABLED=true

# Delay entre PREPARE y EXECUTE (ms)
# Aumentar si hay receptores lejanos
LORA_SYNC_DELAY_MS=300
```

## Configuración de radio

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| Frecuencia | 915 MHz | Banda ISM (ajustar según región) |
| Ancho de banda | 125 kHz | |
| Spreading Factor | 9 | |
| Coding Rate | 4/7 | |
| Sync Word | 0x12 | |
| CRC | Habilitado | |

## Estadísticas (Info panel WLED)

El usermod muestra en el panel de información:
- **RX**: Paquetes recibidos
- **EX**: Playlists ejecutadas
- **SY**: Ejecuciones sincronizadas
- **Last**: Tiempo desde último paquete y RSSI
- **Pending**: Comando pendiente de ejecutar (si hay)

## Timeout

Si un comando PREPARE no recibe su EXECUTE correspondiente en 5 segundos, se descarta automáticamente para evitar ejecuciones fantasma.

## Compatibilidad

- TTGO LoRa32 V2.1.6
- Otros ESP32 con módulo SX1276/SX1278
- WLED 0.14+

## Solución de problemas

### Los dispositivos aún no están sincronizados
- Aumentar `LORA_SYNC_DELAY_MS` (probar 400-500ms)
- Verificar que todos los receptores tienen el firmware actualizado
- Comprobar la calidad de señal LoRa (RSSI en el panel)

### No se ejecutan los comandos
- Verificar que `LORA_SYNC_ENABLED=true` en el orquestador
- Comprobar que la radio está funcionando (panel Info)
- Revisar los logs del orquestador

### Ejecuciones duplicadas
- Verificar que no hay receptores con firmware legacy mezclados
