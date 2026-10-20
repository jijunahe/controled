// Receptor LoRa con sincronización para TTGO LoRa32 V2.1.6 + WLED
// Recibe comandos de playlist y los ejecuta de forma sincronizada con otros receptores.
//
// Protocolo de sincronización de dos fases:
//   Fase 1 (PREPARE): {"playlist":N,"sync":1,"seq":123}
//           El receptor almacena el comando pero NO lo ejecuta.
//   Fase 2 (EXECUTE): {"exec":123}
//           El receptor ejecuta el comando almacenado si seq coincide.
//
// Modo legacy (sin sync): {"playlist":N}
//           Ejecuta inmediatamente (comportamiento original).
//
// Radio: 915 MHz, 125 kHz BW, SF9, CR 4/7, sync 0x12, CRC habilitado.

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <RadioLib.h>
#include <SPI.h>
#include <WiFi.h>
#include <Wire.h>

// ============================================================================
// Configuración de pines TTGO LoRa32 V2.1.6
// ============================================================================
constexpr uint8_t kLedPin = 25;
constexpr uint8_t kRadioCs = 18;
constexpr uint8_t kRadioDio0 = 26;
constexpr uint8_t kRadioRst = 23;
constexpr uint8_t kRadioSck = 5;
constexpr uint8_t kRadioMiso = 19;
constexpr uint8_t kRadioMosi = 27;
constexpr uint8_t kOledSda = 21;
constexpr uint8_t kOledScl = 22;

// ============================================================================
// Configuración de red y WLED
// ============================================================================
// IMPORTANTE: Cambiar estos valores según tu red
#ifndef WIFI_SSID
  #define WIFI_SSID "TU_SSID"
#endif
#ifndef WIFI_PASS
  #define WIFI_PASS "TU_PASSWORD"
#endif
#ifndef WLED_IP
  #define WLED_IP "127.0.0.1"  // localhost si WLED corre en este mismo ESP32
#endif

const char* wifiSsid = WIFI_SSID;
const char* wifiPass = WIFI_PASS;
const char* wledIp = WLED_IP;

// ============================================================================
// Constantes del protocolo
// ============================================================================
constexpr size_t kMaxPayload = 255;
constexpr uint32_t kSyncTimeout = 5000;  // Timeout para recibir EXECUTE después de PREPARE

// ============================================================================
// Hardware
// ============================================================================
SX1276 radio = new Module(kRadioCs, kRadioDio0, kRadioRst, RADIOLIB_NC);
Adafruit_SSD1306 display(128, 64, &Wire, -1);

bool displayReady = false;
bool radioReady = false;
bool wifiConnected = false;

// ============================================================================
// Estado de sincronización
// ============================================================================
struct SyncState {
  bool pending;           // Hay un comando pendiente de ejecutar
  uint16_t seq;           // ID de secuencia del comando pendiente
  int playlist;           // Playlist a ejecutar
  uint32_t receivedAt;    // Timestamp de recepción (para timeout)
} syncState = {false, 0, 0, 0};

// ============================================================================
// Estadísticas
// ============================================================================
uint32_t packetsReceived = 0;
uint32_t packetsExecuted = 0;
uint32_t syncExecutions = 0;

// ============================================================================
// Funciones de display
// ============================================================================
void showStatus(const char* line1, const char* line2 = "", const char* line3 = "", const char* line4 = "") {
  if (!displayReady) return;
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  if (line2[0]) display.println(line2);
  if (line3[0]) display.println(line3);
  if (line4[0]) display.println(line4);
  display.display();
}

void showSyncStatus() {
  if (!displayReady) return;
  
  char line1[32], line2[32], line3[32], line4[32];
  snprintf(line1, sizeof(line1), "LoRa Receptor SYNC");
  snprintf(line2, sizeof(line2), "RX:%lu EX:%lu SY:%lu", packetsReceived, packetsExecuted, syncExecutions);
  snprintf(line3, sizeof(line3), "WiFi: %s", wifiConnected ? "OK" : "NO");
  
  if (syncState.pending) {
    snprintf(line4, sizeof(line4), "PEND: pl=%d seq=%u", syncState.playlist, syncState.seq);
  } else {
    snprintf(line4, sizeof(line4), "Esperando...");
  }
  
  showStatus(line1, line2, line3, line4);
}

// ============================================================================
// Conexión WiFi
// ============================================================================
void connectWiFi() {
  WiFi.begin(wifiSsid, wifiPass);
  showStatus("LoRa Receptor", "Conectando WiFi...");
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    attempts++;
  }
  
  wifiConnected = (WiFi.status() == WL_CONNECTED);
  if (wifiConnected) {
    char ip[32];
    snprintf(ip, sizeof(ip), "IP: %s", WiFi.localIP().toString().c_str());
    showStatus("LoRa Receptor", "WiFi conectado", ip);
  } else {
    showStatus("LoRa Receptor", "WiFi FALLIDO", "Continuando sin red");
  }
  delay(1000);
}

// ============================================================================
// Ejecutar playlist en WLED
// ============================================================================
bool executePlaylist(int playlist) {
  if (!wifiConnected) {
    Serial.printf("[WLED] Sin WiFi, no se puede ejecutar playlist %d\n", playlist);
    return false;
  }
  
  HTTPClient http;
  char url[64];
  snprintf(url, sizeof(url), "http://%s/json/state", wledIp);
  
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  
  char body[32];
  snprintf(body, sizeof(body), "{\"ps\":%d}", playlist);
  
  int httpCode = http.POST(body);
  http.end();
  
  if (httpCode == 200) {
    Serial.printf("[WLED] Playlist %d ejecutada OK\n", playlist);
    packetsExecuted++;
    return true;
  } else {
    Serial.printf("[WLED] Error HTTP %d al ejecutar playlist %d\n", httpCode, playlist);
    return false;
  }
}

// ============================================================================
// Procesar paquete LoRa recibido
// ============================================================================
void processPacket(uint8_t* data, size_t len) {
  packetsReceived++;
  digitalWrite(kLedPin, HIGH);
  
  // Parsear JSON
  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, data, len);
  
  if (error) {
    Serial.printf("[RX] Error JSON: %s\n", error.c_str());
    digitalWrite(kLedPin, LOW);
    return;
  }
  
  // Caso 1: Comando EXECUTE (fase 2 de sincronización)
  if (doc.containsKey("exec")) {
    uint16_t execSeq = doc["exec"].as<uint16_t>();
    
    if (syncState.pending && syncState.seq == execSeq) {
      Serial.printf("[SYNC] EXECUTE seq=%u, ejecutando playlist %d\n", execSeq, syncState.playlist);
      executePlaylist(syncState.playlist);
      syncState.pending = false;
      syncExecutions++;
    } else if (syncState.pending) {
      Serial.printf("[SYNC] EXECUTE seq=%u ignorado (esperaba %u)\n", execSeq, syncState.seq);
    } else {
      Serial.printf("[SYNC] EXECUTE seq=%u ignorado (sin comando pendiente)\n", execSeq);
    }
    
    digitalWrite(kLedPin, LOW);
    showSyncStatus();
    return;
  }
  
  // Caso 2: Comando con playlist
  if (doc.containsKey("playlist")) {
    int playlist = doc["playlist"].as<int>();
    bool isSync = doc["sync"].as<int>() == 1;
    uint16_t seq = doc["seq"].as<uint16_t>();
    
    if (isSync) {
      // Modo sincronizado: PREPARE (fase 1)
      syncState.pending = true;
      syncState.seq = seq;
      syncState.playlist = playlist;
      syncState.receivedAt = millis();
      Serial.printf("[SYNC] PREPARE playlist=%d seq=%u\n", playlist, seq);
    } else {
      // Modo legacy: ejecutar inmediatamente
      Serial.printf("[LEGACY] Ejecutando playlist %d inmediatamente\n", playlist);
      executePlaylist(playlist);
    }
  }
  
  digitalWrite(kLedPin, LOW);
  showSyncStatus();
}

// ============================================================================
// Setup
// ============================================================================
void setup() {
  Serial.begin(115200);
  pinMode(kLedPin, OUTPUT);
  digitalWrite(kLedPin, LOW);
  
  // Inicializar display OLED
  Wire.begin(kOledSda, kOledScl);
  displayReady = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  showStatus("LoRa Receptor", "Iniciando...");
  
  // Conectar WiFi
  connectWiFi();
  
  // Inicializar radio LoRa
  showStatus("LoRa Receptor", "Iniciando radio", "915.0 MHz SF9");
  
  SPI.begin(kRadioSck, kRadioMiso, kRadioMosi, kRadioCs);
  int16_t state = radio.begin(915.0, 125.0, 9, 7, 0x12, 10, 8, 0);
  
  radioReady = (state == RADIOLIB_ERR_NONE);
  if (!radioReady) {
    char err[32];
    snprintf(err, sizeof(err), "Error: %d", state);
    showStatus("LoRa Receptor", "Radio FALLIDA", err);
    Serial.printf("[RADIO] Fallo al inicializar: %d\n", state);
    return;
  }
  
  radio.setCRC(true);
  Serial.println("[RADIO] Radio LoRa lista");
  showSyncStatus();
}

// ============================================================================
// Loop principal
// ============================================================================
void loop() {
  if (!radioReady) {
    delay(1000);
    return;
  }
  
  // Verificar timeout de comandos pendientes
  if (syncState.pending) {
    uint32_t elapsed = millis() - syncState.receivedAt;
    if (elapsed > kSyncTimeout) {
      Serial.printf("[SYNC] Timeout para seq=%u, descartando\n", syncState.seq);
      syncState.pending = false;
      showSyncStatus();
    }
  }
  
  // Recibir paquetes LoRa
  uint8_t buffer[kMaxPayload];
  size_t len = sizeof(buffer);
  
  int16_t state = radio.receive(buffer, len);
  
  if (state == RADIOLIB_ERR_NONE) {
    len = radio.getPacketLength();
    Serial.printf("[RX] Paquete de %u bytes, RSSI=%.1f dBm\n", len, radio.getRSSI());
    processPacket(buffer, len);
  } else if (state != RADIOLIB_ERR_RX_TIMEOUT) {
    Serial.printf("[RX] Error: %d\n", state);
  }
  
  // Actualizar display periódicamente
  static uint32_t lastDisplay = 0;
  if (millis() - lastDisplay > 2000) {
    showSyncStatus();
    lastDisplay = millis();
  }
}
