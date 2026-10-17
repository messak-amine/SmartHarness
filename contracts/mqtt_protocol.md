
# SmartHarness — MQTT Protocol

Protocol version: 1

## Architecture

ECU A / ECU B
       |
       v
   CAN Bus
       |
       v
     Gateway
       |
       v
 MQTT Broker (Mosquitto)
       |
       v
 Node-RED Dashboard / SQLite

The ECUs detect faults locally.
The gateway translates CAN messages into JSON.
The dashboard displays and stores diagnostic information.

## Broker

- Broker: Mosquitto
- Location: Local computer
- Default port: 1883
- Topic prefix: smartharness/

## MQTT Topics

| Topic | Purpose | QoS |
|-------|---------|-----|
| smartharness/ecu/a/faults | ECU A fault events | 1 |
| smartharness/ecu/b/faults | ECU B fault events | 1 |
| smartharness/ecu/a/telemetry | ECU A measurements | 0 |
| smartharness/ecu/b/telemetry | ECU B measurements | 0 |
| smartharness/diagnostics/request | Diagnostic requests | 1 |
| smartharness/diagnostics/response | Diagnostic responses | 1 |
| smartharness/gateway/status | Gateway connection status | 1 |

## Fault Event JSON

Example topic:

smartharness/ecu/a/faults

Example payload:

```json
{
  "ecu": "A",
  "circuit": 1,
  "fault_code": 1,
  "active": true,
  "voltage_mv": 0,
  "command_on": true,
  "seq": 1
}
```

## Fault Codes

- 0: Fault resolved
- 1: Disconnection
- 2: Intermittent fault

Fault code 2 is reserved for future implementation.

## Circuit Identifiers

- 1: Headlights (ECU A)
- 2: Indicators (ECU A)
- 3: Brake lights (ECU B)
- 4: Ventilation (ECU B)

## Communication Rules

1. Each ECU detects faults independently.
2. Fault events are transmitted over CAN.
3. The gateway decodes CAN events into JSON.
4. The gateway publishes JSON to the corresponding MQTT topic.
5. The dashboard subscribes to MQTT topics.
6. SQLite stores diagnostic events.

QoS 1 provides at-least-once delivery between MQTT
clients and the broker. Duplicate messages are possible.

Future implementations must identify and handle duplicates.
Sequence numbers alone are insufficient after an ECU restart;
a boot/session identifier will also be required.

## Implementation Status

SmartHarness v0.1:
- JSON format defined
- CAN-to-JSON decoding implemented
- Diagnostic JSON displayed in terminal

Not yet implemented:
- MQTT broker connection
- MQTT message publication
- MQTT subscriptions
- Node-RED dashboard
- SQLite integration
- Diagnostic request/response
- Reconnection and duplicate handling
```
