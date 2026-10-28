/*
  ESP32-S3 AIoT Assistant - RGB LED firmware
  Board: ESP32-S3 DevKit with onboard addressable RGB LED on GPIO 48
  Libraries required:
    - ArduinoJson (Benoit Blanchon)
    - Adafruit NeoPixel

  IMPORTANT:
    1. Update WIFI_SSID and WIFI_PASSWORD.
    2. Set SERVER_BASE to your PC's LAN IPv4 address, port 8000.
    3. DEVICE_TOKEN must exactly match DEVICE_TOKEN in server/.env.
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>

// ---------- CONFIGURATION: EDIT THESE VALUES ----------
const char* WIFI_SSID = "NAMA_WIFI";
const char* WIFI_PASSWORD = "PASSWORD_WIFI";

// Example only. Replace with your PC's current IPv4 address.
const char* SERVER_BASE = "http://GANTI_DENGAN_IP_PC:8000";

// Must match DEVICE_TOKEN in server/.env exactly.
const char* DEVICE_TOKEN = "GANTI_DENGAN_DEVICE_TOKEN_DARI_ENV";
// -----------------------------------------------------

constexpr uint8_t RGB_LED_PIN = 48;
constexpr uint16_t RGB_LED_COUNT = 1;
constexpr uint8_t LED_BRIGHTNESS = 40;

constexpr unsigned long HEARTBEAT_INTERVAL_MS = 10000;
constexpr unsigned long POLL_INTERVAL_MS = 2000;
constexpr unsigned long DEFAULT_PULSE_MS = 1000;
constexpr unsigned long BLINK_INTERVAL_MS = 500;

Adafruit_NeoPixel rgb(RGB_LED_COUNT, RGB_LED_PIN, NEO_GRB + NEO_KHZ800);

unsigned long lastHeartbeatMs = 0;
unsigned long lastPollMs = 0;
unsigned long lastEffectStepMs = 0;
unsigned long pulseEndsAtMs = 0;

bool ledOn = false;
bool blinkEnabled = false;
bool pulseEnabled = false;
bool blinkPhaseOn = false;

String deviceId = "esp32-s3";

String endpoint(const char* path) {
  String base = SERVER_BASE;
  while (base.endsWith("/")) {
    base.remove(base.length() - 1);
  }
  return base + path;
}

void setRgb(bool on) {
  ledOn = on;
  if (on) {
    // Cyan-blue RGB color. Change values if you prefer another color.
    rgb.setPixelColor(0, rgb.Color(0, 120, 255));
  } else {
    rgb.setPixelColor(0, rgb.Color(0, 0, 0));
  }
  rgb.show();
}

bool postJson(const String& path, JsonDocument& doc, String* responseBody = nullptr) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }

  HTTPClient http;
  http.setTimeout(4000);

  if (!http.begin(endpoint(path.c_str()))) {
    return false;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  String body;
  serializeJson(doc, body);
  int code = http.POST(body);

  if (responseBody != nullptr && code > 0) {
    *responseBody = http.getString();
  }

  http.end();
  return code >= 200 && code < 300;
}

void sendCommandResult(const String& commandId, bool success, const String& message) {
  StaticJsonDocument<384> doc;
  doc["command_id"] = commandId;
  doc["success"] = success;
  doc["message"] = message;

  if (!postJson("/api/commands/result", doc)) {
    Serial.println("[WARN] Gagal mengirim hasil perintah ke server.");
  }
}

void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  StaticJsonDocument<384> doc;
  doc["device_id"] = deviceId;
  doc["ip"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  doc["uptime_ms"] = millis();
  doc["led"] = ledOn;

  bool ok = postJson("/api/heartbeat", doc);
  Serial.println(ok ? "[HEARTBEAT] OK" : "[HEARTBEAT] Gagal");
}

void stopEffects() {
  blinkEnabled = false;
  pulseEnabled = false;
  blinkPhaseOn = false;
  pulseEndsAtMs = 0;
}

void handleCommand(const String& commandId, const String& action, unsigned long durationMs) {
  Serial.printf("[COMMAND] action=%s id=%s\n", action.c_str(), commandId.c_str());

  bool success = true;
  String resultMessage = "Perintah berhasil dijalankan.";

  if (action == "led_on") {
    stopEffects();
    setRgb(true);
  } else if (action == "led_off") {
    stopEffects();
    setRgb(false);
  } else if (action == "pulse") {
    stopEffects();
    setRgb(true);
    pulseEnabled = true;
    unsigned long pulseDuration = durationMs > 0 ? durationMs : DEFAULT_PULSE_MS;
    pulseEndsAtMs = millis() + pulseDuration;
  } else if (action == "blink") {
    pulseEnabled = false;
    pulseEndsAtMs = 0;
    blinkEnabled = true;
    blinkPhaseOn = true;
    lastEffectStepMs = millis();
    setRgb(true);
  } else if (action == "stop_blink") {
    stopEffects();
    setRgb(false);
  } else {
    success = false;
    resultMessage = "Aksi tidak dikenal oleh firmware: " + action;
  }

  sendCommandResult(commandId, success, resultMessage);
}

void pollCommand() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  HTTPClient http;
  http.setTimeout(4000);

  if (!http.begin(endpoint("/api/commands/next"))) {
    return;
  }

  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  int code = http.GET();

  if (code == 200) {
    String response = http.getString();
    StaticJsonDocument<768> doc;
    DeserializationError error = deserializeJson(doc, response);

    if (!error) {
      JsonVariant command = doc["command"];
      if (!command.isNull()) {
        String commandId = command["id"] | "";
        String action = command["action"] | "";
        unsigned long durationMs = command["duration_ms"] | 0UL;

        if (commandId.length() > 0 && action.length() > 0) {
          http.end();
          handleCommand(commandId, action, durationMs);
          return;
        }
      }
    } else {
      Serial.printf("[WARN] JSON perintah tidak valid: %s\n", error.c_str());
    }
  } else if (code < 0) {
    Serial.printf("[WARN] Polling gagal: %s\n", http.errorToString(code).c_str());
  }

  http.end();
}

void updateLedEffects() {
  unsigned long now = millis();

  if (pulseEnabled && (long)(now - pulseEndsAtMs) >= 0) {
    pulseEnabled = false;
    setRgb(false);
  }

  if (blinkEnabled && now - lastEffectStepMs >= BLINK_INTERVAL_MS) {
    lastEffectStepMs = now;
    blinkPhaseOn = !blinkPhaseOn;
    setRgb(blinkPhaseOn);
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Menghubungkan ke Wi-Fi");
  unsigned long startedAt = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 20000) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WiFi] Terhubung.");
    Serial.print("[WiFi] IP ESP32: ");
    Serial.println(WiFi.localIP());
    Serial.print("[Server] ");
    Serial.println(SERVER_BASE);
  } else {
    Serial.println("[WiFi] Belum terhubung. Akan mencoba lagi.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  rgb.begin();
  rgb.setBrightness(LED_BRIGHTNESS);
  setRgb(false);

  connectWiFi();

  lastHeartbeatMs = millis() - HEARTBEAT_INTERVAL_MS;
  lastPollMs = millis() - POLL_INTERVAL_MS;
}

void loop() {
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED) {
    static unsigned long lastReconnectAttemptMs = 0;
    if (now - lastReconnectAttemptMs >= 5000) {
      lastReconnectAttemptMs = now;
      Serial.println("[WiFi] Mencoba menghubungkan kembali...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
  } else {
    if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
      lastHeartbeatMs = now;
      sendHeartbeat();
    }

    if (now - lastPollMs >= POLL_INTERVAL_MS) {
      lastPollMs = now;
      pollCommand();
    }
  }

  updateLedEffects();
  delay(5);
}
