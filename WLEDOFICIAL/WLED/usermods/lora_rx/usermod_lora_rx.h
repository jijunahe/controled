#pragma once

#include "wled.h"
#include <RadioLib.h>
#include <ArduinoJson.h>

/*
 * Usermod: LoRa Receiver with Synchronization Protocol
 * 
 * Receives playlist commands via LoRa and applies them to WLED.
 * Supports synchronized execution across multiple receivers.
 * 
 * Protocol:
 *   Legacy mode:     {"playlist":N}          -> execute immediately
 *   Sync mode:
 *     Phase 1 PREPARE: {"playlist":N,"sync":1,"seq":123}  -> store, don't execute
 *     Phase 2 EXECUTE: {"exec":123}                       -> execute stored command
 * 
 * Radio config: 915 MHz, 125 kHz BW, SF9, CR 4/7, sync 0x12, CRC enabled
 * Compatible with TTGO LoRa32 V2.1.6
 */

#ifndef LORA_RX_CS
  #define LORA_RX_CS 18
#endif
#ifndef LORA_RX_DIO0
  #define LORA_RX_DIO0 26
#endif
#ifndef LORA_RX_RST
  #define LORA_RX_RST 23
#endif
#ifndef LORA_RX_FREQUENCY
  #define LORA_RX_FREQUENCY 915.0
#endif
#ifndef LORA_RX_BANDWIDTH
  #define LORA_RX_BANDWIDTH 125.0
#endif
#ifndef LORA_RX_SF
  #define LORA_RX_SF 9
#endif
#ifndef LORA_RX_CR
  #define LORA_RX_CR 7
#endif
#ifndef LORA_RX_SYNC_WORD
  #define LORA_RX_SYNC_WORD 0x12
#endif

class LoRaRxUsermod : public Usermod {
  private:
    static constexpr size_t kMaxPayload = 255;
    static constexpr uint32_t kSyncTimeoutMs = 5000;
    static constexpr uint32_t kReceiveTimeoutMs = 100;

    SX1276* radio = nullptr;
    bool radioReady = false;
    bool enabled = true;
    
    uint32_t packetsReceived = 0;
    uint32_t packetsExecuted = 0;
    uint32_t syncExecutions = 0;
    uint32_t lastPacketTime = 0;
    int16_t lastRssi = 0;
    
    struct SyncState {
      bool pending;
      uint16_t seq;
      int16_t playlist;
      uint32_t receivedAt;
    } syncState = {false, 0, -1, 0};
    
    uint8_t rxBuffer[kMaxPayload];
    
    void initRadio() {
      if (radio != nullptr) {
        delete radio;
      }
      
      radio = new SX1276(new Module(LORA_RX_CS, LORA_RX_DIO0, LORA_RX_RST, RADIOLIB_NC));
      
      int16_t state = radio->begin(
        LORA_RX_FREQUENCY,
        LORA_RX_BANDWIDTH,
        LORA_RX_SF,
        LORA_RX_CR,
        LORA_RX_SYNC_WORD,
        10,  // power (not used for RX)
        8,   // preamble length
        0    // gain
      );
      
      if (state == RADIOLIB_ERR_NONE) {
        radio->setCRC(true);
        radioReady = true;
        DEBUG_PRINTLN(F("[LoRa_RX] Radio initialized OK"));
      } else {
        radioReady = false;
        DEBUG_PRINTF("[LoRa_RX] Radio init failed: %d\n", state);
      }
    }
    
    void executePlaylist(int16_t playlist) {
      if (playlist < 0 || playlist > 250) {
        DEBUG_PRINTF("[LoRa_RX] Invalid playlist: %d\n", playlist);
        return;
      }
      
      applyPreset(playlist);
      packetsExecuted++;
      DEBUG_PRINTF("[LoRa_RX] Executed playlist %d\n", playlist);
    }
    
    void processPacket(size_t len) {
      packetsReceived++;
      lastPacketTime = millis();
      lastRssi = radio->getRSSI();
      
      StaticJsonDocument<256> doc;
      DeserializationError error = deserializeJson(doc, rxBuffer, len);
      
      if (error) {
        DEBUG_PRINTF("[LoRa_RX] JSON error: %s\n", error.c_str());
        return;
      }
      
      // Case 1: EXECUTE command (sync phase 2)
      if (doc.containsKey("exec")) {
        uint16_t execSeq = doc["exec"].as<uint16_t>();
        
        if (syncState.pending && syncState.seq == execSeq) {
          DEBUG_PRINTF("[LoRa_RX] SYNC EXECUTE seq=%u -> playlist %d\n", 
                       execSeq, syncState.playlist);
          executePlaylist(syncState.playlist);
          syncState.pending = false;
          syncExecutions++;
        } else {
          DEBUG_PRINTF("[LoRa_RX] EXECUTE seq=%u ignored (pending=%d, expected=%u)\n",
                       execSeq, syncState.pending, syncState.seq);
        }
        return;
      }
      
      // Case 2: Playlist command
      if (doc.containsKey("playlist")) {
        int16_t playlist = doc["playlist"].as<int16_t>();
        bool isSync = doc["sync"].as<int>() == 1;
        uint16_t seq = doc["seq"].as<uint16_t>();
        
        if (isSync) {
          // Sync mode: PREPARE (phase 1)
          syncState.pending = true;
          syncState.seq = seq;
          syncState.playlist = playlist;
          syncState.receivedAt = millis();
          DEBUG_PRINTF("[LoRa_RX] SYNC PREPARE playlist=%d seq=%u\n", playlist, seq);
        } else {
          // Legacy mode: execute immediately
          DEBUG_PRINTF("[LoRa_RX] LEGACY playlist=%d\n", playlist);
          executePlaylist(playlist);
        }
        return;
      }
      
      // Case 3: Direct preset (ps field like WLED API)
      if (doc.containsKey("ps")) {
        int16_t preset = doc["ps"].as<int16_t>();
        DEBUG_PRINTF("[LoRa_RX] Direct preset ps=%d\n", preset);
        executePlaylist(preset);
      }
    }

  public:
    void setup() override {
      initRadio();
    }

    void loop() override {
      if (!radioReady || !enabled) return;
      
      // Check sync timeout
      if (syncState.pending) {
        uint32_t elapsed = millis() - syncState.receivedAt;
        if (elapsed > kSyncTimeoutMs) {
          DEBUG_PRINTF("[LoRa_RX] Sync timeout for seq=%u\n", syncState.seq);
          syncState.pending = false;
        }
      }
      
      // Non-blocking receive
      size_t len = sizeof(rxBuffer);
      int16_t state = radio->receive(rxBuffer, len);
      
      if (state == RADIOLIB_ERR_NONE) {
        len = radio->getPacketLength();
        if (len > 0 && len <= kMaxPayload) {
          DEBUG_PRINTF("[LoRa_RX] Packet %u bytes, RSSI=%.1f\n", len, radio->getRSSI());
          processPacket(len);
        }
      }
    }

    void addToJsonInfo(JsonObject& root) override {
      JsonObject user = root["u"];
      if (user.isNull()) user = root.createNestedObject("u");

      JsonArray loraArr = user.createNestedArray(F("LoRa RX"));
      
      if (!radioReady) {
        loraArr.add(F("Radio Error"));
        return;
      }
      
      char info[64];
      snprintf(info, sizeof(info), "RX:%lu EX:%lu SY:%lu", 
               packetsReceived, packetsExecuted, syncExecutions);
      loraArr.add(info);
      
      if (lastPacketTime > 0) {
        uint32_t ago = (millis() - lastPacketTime) / 1000;
        snprintf(info, sizeof(info), "Last: %lus ago, RSSI=%d", ago, lastRssi);
        loraArr.add(info);
      }
      
      if (syncState.pending) {
        snprintf(info, sizeof(info), "Pending: pl=%d seq=%u", 
                 syncState.playlist, syncState.seq);
        loraArr.add(info);
      }
    }

    void addToConfig(JsonObject& root) override {
      JsonObject top = root.createNestedObject(FPSTR("lora_rx"));
      top[F("enabled")] = enabled;
    }

    bool readFromConfig(JsonObject& root) override {
      JsonObject top = root[FPSTR("lora_rx")];
      if (top.isNull()) return false;
      
      enabled = top[F("enabled")] | true;
      return true;
    }

    uint16_t getId() override { return USERMOD_ID_LORA_RX; }
};

#ifndef USERMOD_ID_LORA_RX
  #define USERMOD_ID_LORA_RX 42001
#endif
