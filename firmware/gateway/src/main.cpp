#include <Arduino.h>
#include <WiFi.h>
#include <AsyncMqttClient.h>
#include <driver/twai.h>
#include <atomic>
#include "protocol.h"
#if __has_include("gateway_config.h")
#include "gateway_config.h"
#else
#include "gateway_config.example.h"
#endif

AsyncMqttClient mqtt;
std::atomic<bool> mqttReady{false};
QueueHandle_t acknowledgements;
Fault pending[64];
size_t head = 0, count = 0;
uint16_t inflight = 0;
uint32_t wifiAttempt = 0, mqttAttempt = 0;
bool canReady = false;
const char* statusTopic = "smartharness/gateway/status";

void acceptFrame(uint32_t id, const uint8_t* data, size_t len, bool ext=false, bool rtr=false) {
    Fault f;
    if (!decodeFault(id, data, len, ext, rtr, false, f)) {
        Serial.println("Rejected CAN frame"); return;
    }
    if (count == 64) { Serial.println("ERROR: event lost, queue full"); return; }
    pending[(head + count) % 64] = f;
    ++count;
}

void setup() {
    Serial.begin(115200);
    acknowledgements = xQueueCreate(8, sizeof(uint16_t));
    if (!acknowledgements) { Serial.println("Fatal: ACK queue allocation"); abort(); }
    char clientId[40];
    snprintf(clientId, sizeof(clientId), "smartharness-%llx", ESP.getEfuseMac());
    mqtt.setClientId(clientId);
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    if (strlen(MQTT_USERNAME)) mqtt.setCredentials(MQTT_USERNAME, MQTT_PASSWORD);
    mqtt.setWill(statusTopic, 1, true, "{\"status\":\"offline\"}");
    mqtt.onConnect([](bool sessionPresent) {
        mqttReady = true;
        mqtt.publish(statusTopic, 1, true, "{\"status\":\"online\"}");
    });
    mqtt.onDisconnect([](AsyncMqttClientDisconnectReason reason) { mqttReady = false; });
    mqtt.onPublish([](uint16_t packetId) { xQueueSend(acknowledgements, &packetId, 0); });
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
#if !SIMULATED_CAN
    twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)CAN_TX_PIN, (gpio_num_t)CAN_RX_PIN, TWAI_MODE_NORMAL);
    twai_timing_config_t timing = TWAI_TIMING_CONFIG_250KBITS();
    twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
    canReady = twai_driver_install(&general, &timing, &filter) == ESP_OK && twai_start() == ESP_OK;
    Serial.println(canReady ? "TWAI ready, 250 kbit/s" : "TWAI initialization failed");
#else
    Serial.println("Simulated CAN: fault/recovery, all four circuits");
#endif
}

void loop() {
    uint32_t now = millis();
    if (WiFi.status() != WL_CONNECTED) {
        if (now - wifiAttempt >= 10000) { wifiAttempt = now; WiFi.reconnect(); }
    } else if (!mqttReady && now - mqttAttempt >= 5000) {
        mqttAttempt = now; mqtt.connect();
    }
    uint16_t ack;
    while (xQueueReceive(acknowledgements, &ack, 0) == pdTRUE) {
        if (inflight && ack == inflight) { head = (head + 1) % 64; --count; inflight = 0; }
    }
    // On disconnect keep the head event; resend after reconnect (duplicates possible).
    if (!mqttReady) inflight = 0;
#if SIMULATED_CAN
    static uint32_t lastSample = 0;
    static uint16_t sequence[2] = {0, 0};
    static uint8_t step = 0;
    if (now - lastSample >= 2000) {
        lastSample = now;
        uint8_t circuit = step % 4 + 1;
        bool active = step < 4;
        uint16_t seq = ++sequence[circuit > 2];
        uint16_t voltage = active ? 0 : 3300;
        uint8_t data[8] = {circuit, uint8_t(active ? 1 : 0), uint8_t(voltage), uint8_t(voltage >> 8),
                           uint8_t(active ? 3 : 1), uint8_t(seq), uint8_t(seq >> 8), 1};
        acceptFrame(circuit <= 2 ? 0x80 : 0x81, data, 8);
        step = (step + 1) % 8;
    }
#else
    if (canReady) {
        twai_message_t message;
        for (int i = 0; i < 16 && twai_receive(&message, 0) == ESP_OK; ++i)
            acceptFrame(message.identifier, message.data, message.data_length_code, message.extd, message.rtr);
        twai_status_info_t status;
        if (twai_get_status_info(&status) == ESP_OK) {
            if (status.state == TWAI_STATE_BUS_OFF) {
                Serial.println("CAN bus-off: recovery requested"); twai_initiate_recovery();
            } else if (status.state == TWAI_STATE_STOPPED) twai_start();
        }
    }
#endif
    if (mqttReady && !inflight && count) {
        char payload[180], topic[40];
        faultJson(pending[head], payload, sizeof(payload));
        snprintf(topic, sizeof(topic), "smartharness/ecu/%c/faults", pending[head].ecu == 'A' ? 'a' : 'b');
        inflight = mqtt.publish(topic, 1, false, payload);
        if (inflight) Serial.println(payload);
    }
    delay(2);
}
