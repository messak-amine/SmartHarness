
# SmartHarness — CAN Protocol

Protocol version: 1

## CAN configuration

- Protocol: Classical CAN
- Identifier: 11-bit standard
- Target hardware bitrate: 250 kbit/s
- Maximum payload: 8 bytes
- Multi-byte integers: little-endian

Note: The Python virtual CAN simulator does not reproduce
physical bus timing or electrical characteristics.

## CAN identifiers

| CAN ID | Purpose |
|--------|---------|
| 0x080 | ECU A fault events |
| 0x081 | ECU B fault events |
| 0x180 | ECU A telemetry |
| 0x181 | ECU B telemetry |
| 0x220 | Diagnostic request |
| 0x221 | ECU A diagnostic response |
| 0x222 | ECU B diagnostic response |
| 0x300 | ECU A heartbeat |
| 0x301 | ECU B heartbeat |

Only fault-event frames are implemented in v0.1.
Payload formats for the other message types must be
finalized before those features are implemented.

## Circuit identifiers

| ID | Circuit | ECU |
|----|---------|-----|
| 1 | Headlights | A |
| 2 | Indicators | A |
| 3 | Brake lights | B |
| 4 | Ventilation | B |

## Fault codes

- 0: Fault resolved
- 1: Disconnection
- 2: Intermittent fault (future implementation)

## Fault-event payload (8 bytes)

| Byte | Description |
|------|-------------|
| 0 | Circuit ID |
| 1 | Fault code |
| 2-3 | Voltage in millivolts (uint16 LE) |
| 4 | Status flags |
| 5-6 | Sequence number (uint16 LE) |
| 7 | Protocol version (0x01) |

Status flags:
- Bit 0: Command ON
- Bit 1: Fault active
- Bits 2-7: Reserved, set to zero

Sequence numbers are maintained separately by each ECU.
They increment on diagnostic events and wrap after 65535.

## Example

ECU A reports a disconnection on circuit 1.

CAN ID: 0x080

Payload (hex):
01 01 00 00 03 01 00 01

Meaning:
- Circuit 1 (headlights)
- Fault code 1 (disconnection)
- Voltage 0 mV
- Command ON
- Fault active
- Sequence 1
- Protocol version 1

## Implementation status

v0.1:
- Basic simulated fault detection
- Fault-event encoding
- Virtual CAN transmission
- Gateway decoding

Not yet implemented:
- Intermittent fault detection
- Periodic telemetry
- Heartbeats
- Diagnostic requests and responses
- Physical CAN hardware
