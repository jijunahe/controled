#ifndef DEVICE_ROLE
#define DEVICE_ROLE 0
#endif

#ifndef NODE_ID
#define NODE_ID 0
#endif

#ifndef RF_FREQUENCY
#define RF_FREQUENCY 915.0
#endif

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <RadioLib.h>
#include <SPI.h>
#include <Wire.h>
#if DEVICE_ROLE == 0
#include <WebServer.h>
#include <WiFi.h>
#endif

constexpr uint8_t gatewayRole = 0;
constexpr uint8_t ledPin = 25;
constexpr uint8_t radioCsPin = 18;
constexpr uint8_t radioDio0Pin = 26;
constexpr uint8_t radioResetPin = 23;
constexpr uint8_t radioSckPin = 5;
constexpr uint8_t radioMisoPin = 19;
constexpr uint8_t radioMosiPin = 27;
constexpr uint8_t oledSdaPin = 21;
constexpr uint8_t oledSclPin = 22;
constexpr uint8_t oledAddress = 0x3C;
constexpr int oledWidth = 128;
constexpr int oledHeight = 64;
constexpr char gatewaySsid[] = "TTGO-LoRa-Gateway";
constexpr char gatewayPassword[] = "LoRa915test";

SX1276 radio = new Module(radioCsPin, radioDio0Pin, radioResetPin, RADIOLIB_NC);
Adafruit_SSD1306 display(oledWidth, oledHeight, &Wire, -1);
#if DEVICE_ROLE == 0
WebServer webServer(80);
#endif

volatile bool radioEvent = false;
bool displayReady = false;
uint32_t nextSequence = 1;
uint32_t pendingSequence = 0;
uint32_t ackDeadline = 0;
uint8_t pendingNode = 0;
bool waitingForAck = false;

void showStatus(const String &line1, const String &line2, const String &line3) {
  if (!displayReady) {
    return;
  }
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  display.println(line2);
  display.println(line3);
  display.display();
}

void onRadioEvent() {
  radioEvent = true;
}

void startRadioReceive() {
  radioEvent = false;
  radio.startReceive();
}

void processGatewayPacket() {
  String packet;
  int state = radio.readData(packet);
  if (state == RADIOLIB_ERR_NONE) {
    unsigned int node = 0;
    unsigned long sequence = 0;
    char result[12] = {};
    if (sscanf(packet.c_str(), "A,%u,%lu,%11s", &node, &sequence, result) == 3) {
      if (waitingForAck && node == pendingNode && sequence == pendingSequence) {
        Serial.printf("Nodo %u: %s (seq %lu)\r\n", node, result, sequence);
        showStatus("Gateway LoRa", String("Nodo ") + node + ": " + result,
                   String("Secuencia ") + sequence);
        waitingForAck = false;
      }
    } else {
      Serial.printf("Paquete no reconocido: %s\r\n", packet.c_str());
    }
  } else {
    Serial.printf("Error al leer LoRa: %d\r\n", state);
  }
  startRadioReceive();
}

bool sendGatewayCommand(const String &line) {
  unsigned int node = 0;
  char command[12] = {};
  char argument[12] = {};
  bool broadcast = line.startsWith("ALL ");
  int fields = 0;
  if (broadcast) {
    fields = sscanf(line.c_str(), "ALL %11s %11s", command, argument);
  } else {
    fields = sscanf(line.c_str(), "%u %11s %11s", &node, command, argument);
    if (node < 1 || node > 2) {
      fields = 0;
    }
  }
  bool validLedCommand = strcmp(command, "LED") == 0 &&
                         fields == (broadcast ? 2 : 3) &&
                         (strcmp(argument, "ON") == 0 || strcmp(argument, "OFF") == 0);
  if ((broadcast && !validLedCommand) ||
      (!broadcast && fields < 2 && fields != 3) ||
      (!broadcast && strcmp(command, "PING") != 0 && !validLedCommand)) {
    Serial.println("Formato: 1 PING | 1 LED ON/OFF | ALL LED ON/OFF");
    return false;
  }
  if (waitingForAck) {
    Serial.println("Espera la respuesta pendiente antes de enviar otra orden.");
    return false;
  }

  char packet[64] = {};
  uint32_t sequence = nextSequence++;
  if (strcmp(command, "PING") == 0) {
    snprintf(packet, sizeof(packet), "C,%u,%lu,PING", node, sequence);
  } else {
    snprintf(packet, sizeof(packet), "C,%u,%lu,LED,%s", node, sequence, argument);
  }

  radio.standby();
  int state = radio.transmit(packet);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("Error al transmitir: %d\r\n", state);
    showStatus("Error LoRa", "No se pudo enviar", String("Codigo ") + state);
    startRadioReceive();
    return false;
  }

  if (broadcast) {
    Serial.printf("Difusion enviada a ambos nodos: %s\r\n", packet);
    showStatus("Gateway LoRa", "Orden a ambos nodos", String("LED ") + argument);
    startRadioReceive();
    return true;
  }

  pendingNode = node;
  pendingSequence = sequence;
  ackDeadline = millis() + 5000;
  waitingForAck = true;
  Serial.printf("Enviado a nodo %u: %s\r\n", node, packet);
  showStatus("Gateway LoRa", String("Enviado a nodo ") + node,
             String("Secuencia ") + sequence);
  startRadioReceive();
  return true;
}

#if DEVICE_ROLE == 0
void handleWebRoot() {
  static const char page[] PROGMEM = R"rawliteral(
<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gateway LoRa</title><style>
:root{color-scheme:light;--ink:#17302b;--muted:#61736e;--paper:#f3f6f2;--line:#d5dfd9;--green:#176b50;--red:#a43e36}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#e8f0eb,#f8f8f2);color:var(--ink);font:16px system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:28px 18px}header{border-bottom:1px solid var(--line);padding:10px 0 22px}
h1{font-size:25px;margin:0 0 6px}p{color:var(--muted);margin:0}.nodes{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin-top:20px}
section{background:#fff;border:1px solid var(--line);border-radius:8px;padding:18px}h2{font-size:18px;margin:0 0 16px}
.all{grid-column:1/-1}
.actions{display:flex;gap:10px}button{flex:1;border:0;border-radius:5px;padding:12px;color:white;background:var(--green);font:inherit;font-weight:650;cursor:pointer}
button.off{background:var(--red)}button:disabled{opacity:.55;cursor:wait}#status{min-height:24px;margin-top:18px;color:var(--muted)}
</style></head><body><main><header><h1>Gateway LoRa</h1><p>Control del LED integrado de cada nodo</p></header>
<div class="nodes"><section><h2>Nodo 1</h2><div class="actions"><button onclick="send(1,'ON',this)">Encender</button><button class="off" onclick="send(1,'OFF',this)">Apagar</button></div></section>
<section><h2>Nodo 2</h2><div class="actions"><button onclick="send(2,'ON',this)">Encender</button><button class="off" onclick="send(2,'OFF',this)">Apagar</button></div></section>
<section class="all"><h2>Ambos nodos</h2><div class="actions"><button onclick="send('all','ON',this)">Encender ambos</button><button class="off" onclick="send('all','OFF',this)">Apagar ambos</button></div></section></div>
<p id="status" role="status">Conecta ambos nodos para enviar órdenes.</p></main><script>
async function send(node,state,button){const status=document.getElementById('status');button.disabled=true;status.textContent=node==='all'?'Enviando orden a ambos nodos...':'Enviando orden al nodo '+node+'...';
try{const r=await fetch('/api/led?node='+node+'&state='+state);const d=await r.json();status.textContent=r.ok?d.message:'Error: '+d.message}
catch(e){status.textContent='No se pudo contactar al gateway'}finally{button.disabled=false}}
</script></body></html>)rawliteral";
  webServer.send(200, "text/html; charset=utf-8", page);
}

void handleWebLed() {
  if (!webServer.hasArg("node") || !webServer.hasArg("state")) {
    webServer.send(400, "application/json", "{\"message\":\"Faltan node/state\"}");
    return;
  }

  String node = webServer.arg("node");
  String state = webServer.arg("state");
  node.trim();
  state.toUpperCase();
  if ((node != "1" && node != "2" && node != "all") ||
      (state != "ON" && state != "OFF")) {
    webServer.send(400, "application/json", "{\"message\":\"Orden no valida\"}");
    return;
  }

  if (waitingForAck) {
    webServer.send(409, "application/json", "{\"message\":\"Espera la respuesta LoRa pendiente\"}");
    return;
  }

  String command = node == "all" ? "ALL LED " + state : node + " LED " + state;
  if (!sendGatewayCommand(command)) {
    webServer.send(503, "application/json", "{\"message\":\"No se pudo enviar la orden LoRa\"}");
    return;
  }

  String destination = node == "all" ? "ambos nodos" : "nodo " + node;
  webServer.send(202, "application/json", "{\"message\":\"Orden enviada a " + destination + "\"}");
}

void startGatewayWeb() {
  WiFi.mode(WIFI_AP);
  if (!WiFi.softAP(gatewaySsid, gatewayPassword)) {
    Serial.println("No se pudo iniciar el punto de acceso Wi-Fi.");
    showStatus("Gateway LoRa", "Error al iniciar", "Wi-Fi AP");
    return;
  }

  webServer.on("/", HTTP_GET, handleWebRoot);
  webServer.on("/api/led", HTTP_GET, handleWebLed);
  webServer.onNotFound([]() {
    webServer.send(404, "application/json", "{\"message\":\"Ruta no encontrada\"}");
  });
  webServer.begin();
  IPAddress address = WiFi.softAPIP();
  Serial.printf("Wi-Fi: %s | clave: %s | pagina: http://%s\r\n",
                gatewaySsid, gatewayPassword, address.toString().c_str());
  showStatus("Gateway LoRa", "Wi-Fi listo", address.toString());
}
#endif

void processNodePacket() {
  String packet;
  int state = radio.readData(packet);
  if (state == RADIOLIB_ERR_NONE) {
    unsigned int target = 0;
    unsigned long sequence = 0;
    char command[16] = {};
    char argument[16] = {};
    int fields = sscanf(packet.c_str(), "C,%u,%lu,%15[^,],%15s",
                        &target, &sequence, command, argument);
    bool broadcast = target == 0;
    if ((target == NODE_ID || broadcast) && (fields == 3 || fields == 4)) {
      const char *result = "OK";
      if (strcmp(command, "LED") == 0 && fields == 4) {
        if (strcmp(argument, "ON") == 0) {
          digitalWrite(ledPin, HIGH);
        } else if (strcmp(argument, "OFF") == 0) {
          digitalWrite(ledPin, LOW);
        } else {
          result = "ERR";
        }
      } else if (strcmp(command, "PING") != 0 || fields != 3) {
        result = "ERR";
      }

      if (broadcast) {
        Serial.printf("Difusion recibida: %s %s\r\n", command, argument);
        showStatus(String("Nodo ") + NODE_ID, "Difusion recibida",
                   String(command) + " " + argument);
      } else {
        char reply[48] = {};
        snprintf(reply, sizeof(reply), "A,%u,%lu,%s", NODE_ID, sequence, result);
        radio.standby();
        delay(100);
        int txState = radio.transmit(reply);
        if (txState != RADIOLIB_ERR_NONE) {
          Serial.printf("Error al responder: %d\r\n", txState);
        } else {
          Serial.printf("Orden %s, respuesta %s\r\n", command, result);
          showStatus(String("Nodo ") + NODE_ID, String(command) + " " + argument,
                     String("Respuesta: ") + result);
        }
      }
    }
  } else {
    Serial.printf("Error al leer LoRa: %d\r\n", state);
  }
  startRadioReceive();
}

void setup() {
  Serial.begin(115200);
  Wire.begin(oledSdaPin, oledSclPin);
  displayReady = display.begin(SSD1306_SWITCHCAPVCC, oledAddress);
  showStatus("TTGO LoRa32", "Iniciando radio", "915 MHz");

  pinMode(ledPin, OUTPUT);
  digitalWrite(ledPin, LOW);

  SPI.begin(radioSckPin, radioMisoPin, radioMosiPin, radioCsPin);
  int state = radio.begin(RF_FREQUENCY);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("No se pudo iniciar SX1276: %d\r\n", state);
    showStatus("Error SX1276", "No se pudo iniciar", String("Codigo ") + state);
    while (true) {
      delay(1000);
    }
  }

  radio.setDio0Action(onRadioEvent, RISING);
  startRadioReceive();

  if (DEVICE_ROLE == gatewayRole) {
    Serial.printf("Gateway LoRa listo en %.1f MHz.\r\n", RF_FREQUENCY);
    Serial.println("Escribe: 1 PING, 1 LED ON/OFF, 2 PING, 2 LED ON/OFF, ALL LED ON/OFF");
    showStatus("Gateway LoRa", String(RF_FREQUENCY, 1) + " MHz", "Listo por USB");
  #if DEVICE_ROLE == 0
    startGatewayWeb();
  #endif
  } else {
    Serial.printf("Nodo %u listo en %.1f MHz.\r\n", NODE_ID, RF_FREQUENCY);
    showStatus(String("Nodo ") + NODE_ID, String(RF_FREQUENCY, 1) + " MHz",
               "Esperando orden");
  }
}

void loop() {
  if (radioEvent) {
    if (DEVICE_ROLE == gatewayRole) {
      processGatewayPacket();
    } else {
      processNodePacket();
    }
  }

  if (DEVICE_ROLE == gatewayRole) {
#if DEVICE_ROLE == 0
    webServer.handleClient();
#endif
    if (Serial.available()) {
      String line = Serial.readStringUntil('\n');
      line.trim();
      line.toUpperCase();
      if (!line.isEmpty()) {
        sendGatewayCommand(line);
      }
    }
    if (waitingForAck && static_cast<int32_t>(millis() - ackDeadline) >= 0) {
      Serial.printf("Sin respuesta del nodo %u (seq %lu).\r\n", pendingNode,
                    pendingSequence);
      showStatus("Gateway LoRa", String("Nodo ") + pendingNode + " sin respuesta",
                 String("Secuencia ") + pendingSequence);
      waitingForAck = false;
    }
  }
}