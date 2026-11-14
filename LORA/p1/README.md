# Gateway y nodos LoRa — TTGO LoRa32 v1.6

Firmware de PlatformIO en `src/main.cpp`. Un mismo código se compila en tres roles: un gateway y dos nodos. El gateway enciende o apaga el LED integrado (GPIO 25) de cada nodo, o de ambos a la vez, por radio LoRa a 915 MHz.

Hacen falta tres placas TTGO LoRa32 v1.6, una por entorno.

## Entornos de compilación

Definidos en `platformio.ini`. El entorno por defecto es `gateway`.

| Entorno | Rol | Identidad | Comando |
|---|---|---|---|
| `gateway` | Gateway | nodo 0 | `pio run -e gateway -t upload` |
| `node1` | Nodo | nodo 1 | `pio run -e node1 -t upload` |
| `node2` | Nodo | nodo 2 | `pio run -e node2 -t upload` |

Placa configurada: `ttgo-lora32-v1` (ESP32, Arduino). La v1.6 usa los mismos 4 MB de flash. Los pines de radio, OLED y LED están fijos en el código, así que no dependen de los valores por defecto de esa definición de placa.

`upload_port` y `monitor_port` están en `COM5` (Windows). En Linux hay que apuntarlos al puerto real, por ejemplo `/dev/ttyUSB0`. El monitor serie va a 115200 baudios.

La radio de la placa tiene que ser la variante de **915 MHz**. El mismo modelo se vende en 433 y 868 MHz, y el circuito de RF no es intercambiable.

## Pines en la TTGO LoRa32 v1.6

| Función | GPIO |
|---|---|
| LoRa SCK | 5 |
| LoRa MISO | 19 |
| LoRa MOSI | 27 |
| LoRa CS | 18 |
| LoRa RST | 23 |
| LoRa DIO0 | 26 |
| OLED SDA (dirección 0x3C) | 21 |
| OLED SCL | 22 |
| LED integrado | 25 |

La OLED es una SSD1306 de 128×64. El reset de la pantalla no está cableado a un GPIO (`-1`).

## Qué hace cada rol

El gateway acepta órdenes por el monitor serie y por una página web. Las reenvía por LoRa y muestra el resultado en la OLED.

Órdenes de serie (se convierten a mayúsculas):

```
1 PING
1 LED ON
1 LED OFF
2 PING
2 LED ON
2 LED OFF
ALL LED ON
ALL LED OFF
```

`PING` comprueba que el nodo responde. `LED ON` / `LED OFF` cambian el GPIO 25. `ALL` llega a los dos nodos.

Cada nodo escucha la radio, ejecuta la orden si va dirigida a él (o si es difusión) y, en una orden individual, contesta. En difusión aplica el LED y no contesta, para que las dos respuestas no choquen en el aire.

## Wi-Fi

Solo el gateway usa Wi-Fi. Los nodos solo hablan por LoRa.

El firmware arranca un punto de acceso propio. No se une a la red de casa.

| Dato | Valor |
|---|---|
| Modo | `WIFI_AP` |
| SSID | `TTGO-LoRa-Gateway` |
| Clave | `LoRa915test` |
| Página | `http://192.168.4.1` (IP habitual del softAP) |
| API | `GET /api/led?node=1\|2\|all&state=ON\|OFF` |

El teléfono o el PC se conectan a esa red y abren la página. Hay botones para el nodo 1, el nodo 2 y ambos.

El ESP32 de la v1.6 puede unirse a una red de **2,4 GHz** (no a 5 GHz). Para usar la red de casa hay que cambiar el firmware del gateway a modo estación, con el SSID y la clave del router. La página quedaría en la IP que asigne el router, y el control de los nodos seguiría siendo por LoRa.

La página responde «orden enviada» cuando el radio ya transmitió. El `OK`, el `ERR` o el silencio del nodo se ven en el monitor serie y en la OLED del gateway, no en el navegador.

Mientras hay una respuesta individual pendiente (hasta 5 segundos), el gateway rechaza otra orden, tanto por serie como por la web.

## Cómo se envían los datos LoRa

Cada orden es un solo paquete de texto. El SX1276 lo modula en LoRa y `radio.transmit()` espera a que salga completo. No hay flujo continuo ni partición de mensajes largos.

El gateway arma el paquete, pasa la radio a reposo, transmite y vuelve a escuchar:

- `C,<destino>,<secuencia>,PING`
- `C,<destino>,<secuencia>,LED,ON`
- `C,<destino>,<secuencia>,LED,OFF`

El destino `0` es la difusión (`ALL`). Ejemplo: `C,1,3,LED,ON` (orden, nodo 1, secuencia 3, LED encendido).

El nodo, si la orden es para él, espera unos 100 ms y contesta:

- `A,<nodo>,<secuencia>,OK`
- `A,<nodo>,<secuencia>,ERR`

Ejemplo: `A,1,3,OK`. El gateway solo acepta esa respuesta si el nodo y la secuencia coinciden con la orden que está esperando.

`radio.begin()` recibe únicamente la frecuencia (915.0 MHz). El resto queda en los valores por defecto de RadioLib 7 para el SX1276:

| Parámetro | Valor |
|---|---|
| Ancho de banda | 125 kHz |
| Factor de dispersión | 9 |
| Codificación | 4/7 |
| Potencia | 10 dBm |
| Preámbulo | 8 símbolos |
| Palabra de sincronización | `0x12` (red privada) |
| CRC | activo |

Con esa configuración, un paquete corto como `C,1,3,LED,ON` ocupa unos 200 ms en el aire.

## Cuánta información cabe

| Límite | Tamaño |
|---|---|
| Lo que envía esta aplicación hoy | unos 12 a 20 bytes |
| Búfer de la orden en el gateway | 64 bytes |
| Búfer de la respuesta en el nodo | 48 bytes |
| Comando y argumento que acepta el analizador | 11 caracteres cada uno |
| Máximo del SX1276 en modo LoRa | 255 bytes por paquete |

El tope útil de este firmware está por debajo de 255 bytes: aunque el búfer admite 64, el comando y el argumento se recortan a 11 caracteres. 255 bytes es el máximo de un paquete del chip. Para más datos hay que repartirlos en varios envíos y rearmarlos en el receptor; este programa no lo hace.

A más bytes, más tiempo en el aire. 255 bytes con la configuración actual tardan cerca de 1,7 s. Subir el factor de dispersión alarga el alcance y también ese tiempo, así que caben menos paquetes por minuto.

## Límites del diseño actual

- La interrupción de recepción (`onRadioEvent`) no está en IRAM. En el gateway, con el Wi-Fi activo, puede coincidir con un acceso a la flash y reiniciar la placa. En los nodos el riesgo es menor.
- La difusión no confirma que los nodos hayan recibido la orden. Si un nodo está apagado o fuera de alcance, la web igual indica que se envió.
- El enlace LoRa va en claro, sin filtro de red. Cualquier radio en 915 MHz, con los mismos parámetros, puede enviar `LED ON` / `LED OFF`. La clave Wi-Fi solo protege la página del gateway.
