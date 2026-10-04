// Modem USB → LoRa para TTGO LoRa32 V2.1.6.
// La Raspberry envía la trama ya cifrada. Esta placa la pone en el aire sin tocarla.
// La radio coincide con el usermod lora_rx: 915 MHz, 125 kHz, SF9, 4/7, sync 0x12, CRC.
//
// Petición (little-endian):
//   A5 5A | cmd | [len u16 | payload | crc16] 
//   cmd 0x01 ping
//   cmd 0x02 transmitir. crc16 es CRC-16/CCITT-FALSE del payload.
// Respuesta:
//   A5 5A | cmd|0x80 | status | detail i16
//   status 0 ok, 1 crc, 2 longitud, 3 radio, 4 orden desconocida

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <RadioLib.h>
#include <SPI.h>
#include <Wire.h>

constexpr uint8_t kLedPin = 25;
constexpr uint8_t kRadioCs = 18;
constexpr uint8_t kRadioDio0 = 26;
constexpr uint8_t kRadioRst = 23;
constexpr uint8_t kRadioSck = 5;
constexpr uint8_t kRadioMiso = 19;
constexpr uint8_t kRadioMosi = 27;
constexpr uint8_t kOledSda = 21;
constexpr uint8_t kOledScl = 22;

constexpr uint8_t kCmdPing = 0x01;
constexpr uint8_t kCmdTx = 0x02;
constexpr uint8_t kStatusOk = 0;
constexpr uint8_t kStatusCrc = 1;
constexpr uint8_t kStatusLen = 2;
constexpr uint8_t kStatusRadio = 3;
constexpr uint8_t kStatusCmd = 4;
constexpr size_t kMaxPayload = 255;
constexpr uint32_t kFrameTimeoutMs = 800;

SX1276 radio = new Module(kRadioCs, kRadioDio0, kRadioRst, RADIOLIB_NC);
Adafruit_SSD1306 display(128, 64, &Wire, -1);

bool displayReady = false;
bool radioReady = false;
uint16_t packetsSent = 0;

enum class RxState : uint8_t { Magic0, Magic1, Cmd, LenLo, LenHi, Payload, CrcLo, CrcHi };

RxState rxState = RxState::Magic0;
uint8_t rxCmd = 0;
uint16_t rxLen = 0;
uint16_t rxGot = 0;
uint16_t rxCrc = 0;
uint32_t rxDeadline = 0;
uint8_t rxBuf[kMaxPayload];

uint16_t crc16(const uint8_t *data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= static_cast<uint16_t>(data[i]) << 8;
    for (uint8_t bit = 0; bit < 8; bit++) {
      if (crc & 0x8000) {
        crc = static_cast<uint16_t>((crc << 1) ^ 0x1021);
      } else {
        crc <<= 1;
      }
    }
  }
  return crc;
}

void showStatus(const char *line1, const char *line2, const char *line3) {
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

void reply(uint8_t cmd, uint8_t status, int16_t detail) {
  uint8_t frame[6] = {
      0xA5,
      0x5A,
      static_cast<uint8_t>(cmd | 0x80),
      status,
      static_cast<uint8_t>(detail & 0xFF),
      static_cast<uint8_t>((detail >> 8) & 0xFF),
  };
  Serial.write(frame, sizeof(frame));
  Serial.flush();
}

void resetRx() {
  rxState = RxState::Magic0;
  rxGot = 0;
  rxLen = 0;
  rxCrc = 0;
}

void transmitPayload() {
  if (!radioReady) {
    reply(kCmdTx, kStatusRadio, -1);
    showStatus("USB a LoRa", "radio apagada", "sin envio");
    return;
  }
  if (rxLen == 0 || rxLen > kMaxPayload) {
    reply(kCmdTx, kStatusLen, 0);
    return;
  }
  const uint16_t expect = crc16(rxBuf, rxLen);
  if (expect != rxCrc) {
    reply(kCmdTx, kStatusCrc, 0);
    showStatus("USB a LoRa", "CRC incorrecto", "no se envio");
    return;
  }

  digitalWrite(kLedPin, HIGH);
  showStatus("USB a LoRa", "enviando...", String(rxLen).c_str());
  const int16_t state = radio.transmit(rxBuf, rxLen);
  digitalWrite(kLedPin, LOW);

  if (state != RADIOLIB_ERR_NONE) {
    reply(kCmdTx, kStatusRadio, state);
    showStatus("USB a LoRa", "error de radio", String(state).c_str());
    return;
  }

  packetsSent++;
  reply(kCmdTx, kStatusOk, static_cast<int16_t>(packetsSent));
  char count[24];
  snprintf(count, sizeof(count), "paquetes %u", packetsSent);
  char sizeLine[24];
  snprintf(sizeLine, sizeof(sizeLine), "%u bytes en el aire", rxLen);
  showStatus("USB a LoRa", sizeLine, count);
}

void handleByte(uint8_t byte) {
  switch (rxState) {
    case RxState::Magic0:
      if (byte == 0xA5) {
        rxState = RxState::Magic1;
        rxDeadline = millis() + kFrameTimeoutMs;
      }
      break;
    case RxState::Magic1:
      rxState = byte == 0x5A ? RxState::Cmd : RxState::Magic0;
      if (byte == 0xA5) {
        rxState = RxState::Magic1;
      }
      break;
    case RxState::Cmd:
      rxCmd = byte;
      if (byte == kCmdPing) {
        reply(kCmdPing, radioReady ? kStatusOk : kStatusRadio, 1);
        resetRx();
      } else if (byte == kCmdTx) {
        rxState = RxState::LenLo;
      } else {
        reply(byte, kStatusCmd, 0);
        resetRx();
      }
      break;
    case RxState::LenLo:
      rxLen = byte;
      rxState = RxState::LenHi;
      break;
    case RxState::LenHi:
      rxLen |= static_cast<uint16_t>(byte) << 8;
      if (rxLen == 0 || rxLen > kMaxPayload) {
        reply(kCmdTx, kStatusLen, static_cast<int16_t>(rxLen));
        resetRx();
      } else {
        rxGot = 0;
        rxState = RxState::Payload;
      }
      break;
    case RxState::Payload:
      rxBuf[rxGot++] = byte;
      if (rxGot >= rxLen) {
        rxState = RxState::CrcLo;
      }
      break;
    case RxState::CrcLo:
      rxCrc = byte;
      rxState = RxState::CrcHi;
      break;
    case RxState::CrcHi:
      rxCrc |= static_cast<uint16_t>(byte) << 8;
      transmitPayload();
      resetRx();
      break;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(kLedPin, OUTPUT);
  digitalWrite(kLedPin, LOW);

  Wire.begin(kOledSda, kOledScl);
  displayReady = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  showStatus("USB a LoRa", "iniciando radio", "915.0 MHz");

  SPI.begin(kRadioSck, kRadioMiso, kRadioMosi, kRadioCs);
  // Misma PHY que lora_rx::begin(915). Potencia 17 dBm, el receptor no depende de ella.
  const int16_t state = radio.begin(915.0, 125.0, 9, 7, 0x12, 17, 8, 0);
  radioReady = state == RADIOLIB_ERR_NONE;
  if (!radioReady) {
    showStatus("USB a LoRa", "fallo SX1276", String(state).c_str());
    return;
  }
  radio.setCRC(true);
  showStatus("USB a LoRa", "915.0  SF9", "esperando USB");
}

void loop() {
  if (rxState != RxState::Magic0 && static_cast<int32_t>(millis() - rxDeadline) >= 0) {
    resetRx();
  }
  while (Serial.available() > 0) {
    handleByte(static_cast<uint8_t>(Serial.read()));
    rxDeadline = millis() + kFrameTimeoutMs;
  }
}
