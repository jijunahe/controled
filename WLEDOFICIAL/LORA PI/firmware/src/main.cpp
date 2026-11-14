// Modem USB → LoRa para TTGO LoRa32 V2.1.6.
// La Raspberry envía la trama ya cifrada. Esta placa la pone en el aire sin tocarla.
// La radio coincide con el usermod lora_rx: 915 MHz, 125 kHz, SF9, 4/7, sync 0x12, CRC.
//
// Petición (little-endian):
//   A5 5A | cmd | [len u16 | payload | crc16] 
//   cmd 0x01 ping
//   cmd 0x02 transmitir. crc16 es CRC-16/CCITT-FALSE del payload.
//   cmd 0x03 igual que transmitir y, después, escuchar 2.4 s.
//            Cada trama recibida sale hacia el USB antes de la respuesta:
//            A5 5A | 0x04 | len u16 | payload | crc16
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
constexpr uint8_t kCmdPoll = 0x03;
constexpr uint8_t kCmdUplink = 0x04;
constexpr uint32_t kListenMs = 2400;
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

void emitUplink(const uint8_t *data, uint16_t len) {
  if (len == 0 || len > kMaxPayload) {
    return;
  }
  const uint16_t crc = crc16(data, len);
  const uint8_t header[5] = {
      0xA5, 0x5A, kCmdUplink, static_cast<uint8_t>(len & 0xFF), static_cast<uint8_t>(len >> 8)};
  Serial.write(header, sizeof(header));
  Serial.write(data, len);
  const uint8_t tail[2] = {static_cast<uint8_t>(crc & 0xFF), static_cast<uint8_t>(crc >> 8)};
  Serial.write(tail, sizeof(tail));
  Serial.flush();
}

void listenReplies() {
  showStatus("USB a LoRa", "escuchando", "bit de vida");
  const uint32_t start = millis();
  uint8_t heard = 0;
  while (static_cast<uint32_t>(millis() - start) < kListenMs) {
    const uint32_t left = kListenMs - static_cast<uint32_t>(millis() - start);
    if (left < 20) {
      break;
    }
    uint8_t buf[kMaxPayload];
    const int16_t state = radio.receive(buf, sizeof(buf), left);
    if (state == RADIOLIB_ERR_RX_TIMEOUT) {
      continue;
    }
    if (state != RADIOLIB_ERR_NONE) {
      delay(20);
      continue;
    }
    const size_t len = radio.getPacketLength();
    if (len > 0 && len <= kMaxPayload && buf[0] == '{') {
      emitUplink(buf, static_cast<uint16_t>(len));
      heard++;
    }
  }
  char line[24];
  snprintf(line, sizeof(line), "avisos %u", heard);
  showStatus("USB a LoRa", "bit de vida", line);
}

void transmitPayload(bool listen) {
  const uint8_t cmd = listen ? kCmdPoll : kCmdTx;
  if (!radioReady) {
    reply(cmd, kStatusRadio, -1);
    showStatus("USB a LoRa", "radio apagada", "sin envio");
    return;
  }
  if (rxLen == 0 || rxLen > kMaxPayload) {
    reply(cmd, kStatusLen, 0);
    return;
  }
  const uint16_t expect = crc16(rxBuf, rxLen);
  if (expect != rxCrc) {
    reply(cmd, kStatusCrc, 0);
    showStatus("USB a LoRa", "CRC incorrecto", "no se envio");
    return;
  }

  digitalWrite(kLedPin, HIGH);
  showStatus("USB a LoRa", listen ? "preguntando..." : "enviando...", String(rxLen).c_str());
  const int16_t state = radio.transmit(rxBuf, rxLen);
  digitalWrite(kLedPin, LOW);

  if (state != RADIOLIB_ERR_NONE) {
    reply(cmd, kStatusRadio, state);
    showStatus("USB a LoRa", "error de radio", String(state).c_str());
    return;
  }

  packetsSent++;
  if (listen) {
    listenReplies();
  }
  reply(cmd, kStatusOk, static_cast<int16_t>(packetsSent));
  if (!listen) {
    char count[24];
    snprintf(count, sizeof(count), "paquetes %u", packetsSent);
    char sizeLine[24];
    snprintf(sizeLine, sizeof(sizeLine), "%u bytes en el aire", rxLen);
    showStatus("USB a LoRa", sizeLine, count);
  }
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
      } else if (byte == kCmdTx || byte == kCmdPoll) {
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
        reply(rxCmd, kStatusLen, static_cast<int16_t>(rxLen));
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
      transmitPayload(rxCmd == kCmdPoll);
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
