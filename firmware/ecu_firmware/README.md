
# SmartHarness — ESP32 ECU Firmware

Embedded firmware for distributed automotive wiring harness fault detection, developed with ESP-IDF.

## Overview

The firmware supports two configurable ESP32 ECU nodes:

| ECU | Monitored Circuits |
|-----|--------------------|
| ECU A | Headlights (1), Indicators (2) |
| ECU B | Brake Lights (3), Ventilation (4) |

The ECU role is selected using ESP-IDF Kconfig.

## Features

- Configurable ECU A/B firmware architecture
- Simulated sensor voltage acquisition (0–3300 mV)
- Open-circuit fault detection with sample confirmation
- Automatic fault recovery detection
- Intermittent fault classification
- Independent fault monitoring per circuit
- Diagnostic event generation with sequence tracking
- CAN v1 frame encoding and round-trip compatibility using the shared codec
- Native C unit tests

## Firmware Structure

```text
firmware/ecu_firmware/
├── main/
│   ├── ecu_firmware.c
│   ├── sensor_sim.c / .h
│   ├── fault_detector.c / .h
│   ├── ecu_events.c / .h
│   ├── ecu_can_adapter.c / .h
│   ├── Kconfig.projbuild
│   └── CMakeLists.txt
├── tests/
│   ├── test_sensor_sim.c
│   ├── test_fault_detector.c
│   ├── test_ecu_events.c
│   ├── test_ecu_can_adapter.c
│   ├── run_tests.ps1
│   └── run_tests.sh
└── README.md
```

## Fault Detection

The software detects faults using configurable monitoring parameters:

- Open-circuit threshold: 2500 mV
- Fault confirmation: 3 consecutive invalid samples
- Recovery confirmation: 3 consecutive valid samples
- Intermittent detection: repeated confirmed faults within 30 seconds

These parameters are currently evaluated using simulated sensor inputs and require hardware calibration.

## CAN Diagnostic Interface

The ECU firmware prepares diagnostic events for the shared CAN communication layer.

| Parameter | Value |
|-----------|-------|
| ECU A Event ID | 0x080 |
| ECU B Event ID | 0x081 |
| Identifier Format | Standard 11-bit |
| Payload Length | 8 bytes |
| Protocol Version | 0x01 |

Fault codes:
- `0`: Recovery
- `1`: Open circuit
- `2`: Intermittent fault (local classification only; sent as code `1` with CAN v1)

The diagnostic interface follows the project CAN contract defined in `contracts/can_protocol.md`.

The application generates a diagnostic event, converts it with `ecu_can_adapter.c`,
then encodes it with the existing `smartharness_can` component. It logs the
resulting CAN frame, but does **not transmit it on a physical bus**.

**Compatibility decision (temporary):** CAN v1 code `2` is reserved and the
shared encoder rejects it. Local intermittent code `2` is **mapped to wire code
`1`** (disconnection), while the local code stays `2` in logs. The receiver
cannot distinguish these two cases yet. Do **not** add code `2` to physical CAN
until Membre 2/3 approve and update the codec/gateway/contract together.
TWAI driver startup, GPIO pin allocation and bus TX require future hardware integration.

## Build

Requirements:
- ESP-IDF v5.5.6
- ESP32 target

```bash
cd firmware/ecu_firmware
idf.py set-target esp32
idf.py menuconfig
idf.py build
```

Select ECU A or ECU B in the project configuration before building.

## Testing

Run native C unit tests:

Windows PowerShell:

```powershell
.\firmware\ecu_firmware\tests\run_tests.ps1
```

Linux:

```bash
bash firmware/ecu_firmware/tests/run_tests.sh
```

Latest local validation:
- Native C tests: 52 previously passed locally; additional cross-component tests run with the updated runner
- Project Python regression tests: 69 passed

## Integration Status

Implemented:
- ECU role configuration
- Simulated sensor acquisition
- Fault detection and recovery
- Intermittent fault classification
- Diagnostic event preparation and CAN v1 encoding (software only)
- Native software testing

Pending:
- Hardware ADC/GPIO integration
- Physical TWAI/CAN transmission integration
- Gateway interoperability validation
- Physical ESP32 testing

## Project

Part of the SmartHarness distributed automotive wiring harness monitoring system.

## Software integration validation

From the repository root, run `bash firmware/ecu_firmware/tests/run_tests.sh`
(or the PowerShell variant above). The script now also compiles ECU application
sources together with the shared CAN v1 codec. GitHub Actions runs the same
suite in the `ecu-native` job. Run ESP-IDF builds **for both Kconfig roles** on
an ESP-IDF v5.5.6 installation; native GCC is not a substitute for those builds.

The demo's elapsed time is taken from `esp_timer_get_time()` instead of
incrementing a counter for each loop iteration. Sensor inputs are still mock
values, with an intentionally simulated disconnected circuit. Thresholds must
be calibrated with actual hardware later.
