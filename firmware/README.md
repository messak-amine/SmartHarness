
# SmartHarness — Embedded CAN Components

This directory contains the embedded communication modules developed for SmartHarness.

## Components

### smartharness_can

Hardware-independent C library for encoding, decoding and validating SmartHarness CAN fault events.

- ECU A: CAN ID `0x080`, circuits 1 and 2
- ECU B: CAN ID `0x081`, circuits 3 and 4
- Classical CAN, 11-bit identifiers
- Payload: 8 bytes
- Protocol version: 1

### smartharness_twai

ESP-IDF component for ESP32 TWAI communication.

Functions:
- `sh_twai_start()` — initialize and enable the controller
- `sh_twai_send()` — submit a validated CAN fault frame
- `sh_twai_receive()` — receive frames through a FreeRTOS queue
- `sh_twai_stop()` — disable and release resources

Configured bitrate: 250 kbit/s.

The current implementation is intended for single-caller use. Concurrent access, queue overflow behavior and recovery from bus errors require further validation.

## Testing

Four native C test programs are available in `tests/native/`.

The `examples/can_smoke` application validates ESP32 firmware compilation with ESP-IDF.

Build the example:

```powershell
cd firmware/examples/can_smoke
idf.py set-target esp32
idf.py build
```

## Validation Status

- Native CAN encoding/decoding tests: passed
- ESP32 firmware compilation: passed
- TWAI initialization, transmission and reception: compiled
- Physical CAN communication: not yet tested

## Hardware Requirements

Real CAN communication requires ESP32 boards, compatible CAN transceivers, appropriate bus termination, common grounding and a safe low-voltage supply.

This prototype must not be connected directly to a vehicle wiring harness or automotive 12 V installation.
