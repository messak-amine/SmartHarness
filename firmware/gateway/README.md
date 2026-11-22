
## Gateway deliverables

- `src/main.cpp`: Wi-Fi/MQTT reconnect, QoS 1, RAM queue, CAN simulation or TWAI.
- `include/protocol.h`: shared fault decoder and contract JSON formatter.
- `protocol_test.cpp`: host decoder tests, executed by GitHub Actions with g++.
- `platformio.ini`: reproducible ESP32 DevKit build targets `esp32-sim` and `esp32-can`.

Read [the French guide](../../docs/partie3-gateway-mqtt.md) for setup, upload,
configuration, PC broker access from LAN, and known delivery limits.
Copy `include/gateway_config.example.h` to `include/gateway_config.h` before hardware use.
The default placeholders compile but cannot connect to a real Wi-Fi network.
