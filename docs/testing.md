# SmartHarness — Software Simulation, End-to-End Integration & Reliability Testing

## 1. Scope

This document describes the testing, cross-module integration and validation of the SmartHarness software stack across all five project missions (M1 to M5):

- **M1 & M2 (ECU Simulation & CAN Protocol)**: Four electrical circuits monitored by two independent ECUs (`ECU A` and `ECU B`), fault detection, recovery, sequence management, and Classical CAN 8-byte little-endian frame encoding (`0x080` / `0x081`) aligned with `contracts/can_protocol.md` and `firmware/components/smartharness_can/smartharness_can.c`.
- **M3 (Gateway & MQTT Bridge)**: Virtual CAN communication (`python-can`), frame decoding (`gateway/decoder.py`), CAN-to-MQTT forwarding (`gateway/can_mqtt_bridge.py`), and QoS 1 MQTT publishing with LWT status (`gateway/mqtt_publisher.py`).
- **M4 (Node-RED Dashboard & SQLite Persistence)**: Event validation (`dashboard/lib/validate-event.js`), in-memory state tracking (`dashboard/lib/state.js`), and SQLite persistence with strict `CHECK` constraints (`dashboard/sql/schema.sql`).
- **M5 (End-to-End Integration, Reliability & Network Benchmarks)**: Full software chain verification (`tests/test_integration_chain.py`), real host software latency measurements vs. theoretical lossy Wi-Fi estimates (`tests/network_experiments.py`), reproducible single-command execution (`scripts/run_demo.py`), and multi-job GitHub Actions CI.

> **Hardware Note:** Physical ESP32 transceivers, physical CAN bus electrical arbitration/termination, and electromagnetic interference (EMI) remain scoped to physical hardware validation once all boards are assembled.

## 2. Testing Environment

Testing is executed both locally (Windows / Linux / macOS) and automatically in GitHub Actions CI:

- **Testing frameworks**: Python `unittest` (`tests/`) and Node.js test runner (`dashboard/tests/`)
- **CAN simulation library**: `python-can 4.6.1` (`virtual` bus interface)
- **MQTT transport in E2E tests**: Standard-library TCP Loopback MQTT v3.1.1 Broker (`127.0.0.1` ephemeral socket exchanging binary `CONNECT`, `CONNACK`, `SUBSCRIBE`, `SUBACK`, `PUBLISH`, `PUBACK` packets) + `paho-mqtt` bridge compatibility
- **Database engine**: Python `sqlite3` executing both the integration schema and M4's `dashboard/sql/schema.sql`
- **Integration branch**: `dev` (via `feat/integration-tests`)

## 3. Automated Test Coverage

### 3.1 Circuit, ECU, CAN Protocol & Gateway Validation (`tests/test_validation_*.py`)

- **Circuit & ECU (`test_circuit.py`, `test_ecu.py`, `test_validation_circuit.py`, `test_validation_ecu.py`)**: Verifies initial states, ON/OFF conditions, wire disconnection (`0 mV`), recovery (`3300 mV`), duplicate-event suppression, and `uint16` sequence wraparound.
- **CAN Protocol (`test_validation_can_protocol.py`, `tests/native/*.c`)**: Verifies CAN IDs `0x080` (ECU A) and `0x081` (ECU B), 11-bit standard identifiers, 8-byte payload layout, little-endian `voltage_mv` and `seq`, status flags (`command_on` bit 0, `active` bit 1), and C native host tests (`smartharness_can.c`).
- **Gateway & Bridge (`test_validation_gateway.py`, `test_gateway_mqtt.py`)**: Verifies valid decoding, defensive rejection of malformed frames, and `MQTTPublisher` QoS 1 handling.

### 3.2 Mission 5 End-to-End Chain & Reliability Suite (`tests/test_integration_chain.py`)

`tests/test_integration_chain.py` validates 12 end-to-end and reliability scenarios across the full software chain:

| Test ID | Test Case | Scenario & Policy Verified | Status |
| :--- | :--- | :--- | :---: |
| **`test_01`** | Official CAN Hex Vector | Verifies ECU A circuit 1 disconnection matches `01 01 00 00 03 01 00 01` on ID `0x080` (`contracts/can_protocol.md`). | **PASS** |
| **`test_02`** | Real Virtual CAN -> TCP MQTT -> SQLite | Transmits ECU A & B faults over `can.Bus(interface="virtual")`, decodes at Gateway, publishes over a real TCP Loopback MQTT v3.1.1 socket (`127.0.0.1`), and verifies SQLite persistence. | **PASS** |
| **`test_03`** | Fault Recovery E2E | Verifies wire reconnection (`fault_code=0`, `active=False`, `3300 mV`) traverses Virtual CAN and TCP MQTT into SQLite history. | **PASS** |
| **`test_04`** | Strict CAN v1 `fault_code=2` Alignment | Rejects reserved `fault_code=2` (intermittent) by default in strict CAN v1 mode (matching M2's `smartharness_can.c`), while allowing it only when `allow_future_intermittent_v2=True` is explicitly scoped. | **PASS** |
| **`test_05`** | Command OFF (`command_on=False`) | Confirms `0 mV` when a circuit is switched OFF produces zero false-positive fault events (TC01). | **PASS** |
| **`test_06`** | MQTT QoS 1 Deduplication | Confirms duplicate QoS 1 re-deliveries sharing `(ecu, circuit, seq, fault_code, active)` are filtered before SQLite insertion (TC05). | **PASS** |
| **`test_07`** | Broker Disconnection & Flush | Buffers CAN events while MQTT is offline and flushes them in FIFO order upon reconnection with `smartharness/gateway/status` update (TC06). | **PASS** |
| **`test_08`** | Negative CAN & MQTT Checks | Rejects unknown CAN ID (`0x180`), extended 29-bit ID, wrong DLC (!= 8), wrong protocol version (!= 1), cross-ECU circuit mismatch (`ECU A` + circuit `3`), reserved flag bits (`0xFC`), inconsistent `fault_code`/`active`, and malformed JSON. | **PASS** |
| **`test_09`** | Bounded Gateway Offline Buffer | Enforces `max_buffer_size` via FIFO `DROP_OLDEST` eviction (`buffer_overflow_drops`) so prolonged broker outages cannot exhaust RAM while retaining the newest circuit states. | **PASS** |
| **`test_10`** | Bounded Dedup Cache & ECU Reboot | Enforces `max_dedup_keys` (`OrderedDict`) and detects ECU sequence resets (`seq == 1` after `last_seq > 1`) so post-reboot events are not falsely dropped as duplicates. | **PASS** |
| **`test_11`** | Benchmark Labeling Verification | Asserts that `tests/network_experiments.py` separates `MEASURED_ON_HOST_SOFTWARE_STACK`, `DETERMINISTIC_PROTOCOL_CALCULATION`, and `SIMULATED_THEORETICAL_ESTIMATE`. | **PASS** |
| **`test_12`** | Cross-Module M1–M2–M3–M4 Integration | Connects `simulator.ecu.ECU` (M1) -> `encode_fault` (M2) -> `gateway.can_mqtt_bridge.forward` & `MQTTPublisher` (M3) -> `dashboard/sql/schema.sql` (M4), including SQL `CHECK` constraint enforcement. | **PASS** |

## 4. Network Benchmarks: Real Software Measurements vs. Theoretical Estimates (`tests/network_experiments.py`)

To maintain strict scientific honesty before physical ESP32 testing, `tests/network_experiments.py` separates experimental host measurements (timed with `time.perf_counter_ns()`, zero `time.sleep()`, zero `random`) from theoretical Monte Carlo estimates:

### 4.1 Real Experimental Measurements on Host Software Stack (`MEASURED_ON_HOST_SOFTWARE_STACK`)

- **Pipeline traversal (`ECU.scan` -> `python-can virtual` -> `decode_fault` -> `TCP Loopback MQTT v3.1.1` -> `SQLite INSERT`, 30 iterations)**:
  - Minimum software latency: **~0.29 ms**
  - Median software latency: **~0.46 ms**
  - Mean software latency: **~0.50 ms**
- **Live TCP Loopback Socket Delivery (100 messages per QoS level on `127.0.0.1`)**:
  - **QoS 0 (lossless local loopback)**: **100 / 100** stored in SQLite (median socket time **~0.23 ms**)
  - **QoS 1 (with binary `PUBACK` handshake)**: **100 / 100** stored in SQLite (median socket time **~0.35 ms**)

### 4.2 Deterministic Protocol Payload Sizing (`DETERMINISTIC_PROTOCOL_CALCULATION`)

- **Measured frame sizes**: **8 bytes** per CAN v1 frame (`encode_fault`) and **285 bytes** per enriched MQTT v1 JSON payload (`contracts/mqtt_protocol.md`).
- **60-second comparison (4 circuits @ 10 Hz vs. Event-driven Edge mode)**:
  - **Raw periodic mode**: **2,400 messages** (`19,200 bytes` CAN / `684,000 bytes` MQTT)
  - **Edge event-driven mode** (state every 5 s + 4 fault transitions): **52 messages** (`416 bytes` CAN / `14,820 bytes` MQTT)
  - **Bandwidth reduction**: **-97.8%**

### 4.3 Theoretical Lossy Wi-Fi Estimates (`SIMULATED_THEORETICAL_ESTIMATE`)

- Clearly labeled Monte Carlo model (`seed=42`, 12% packet loss probability per transmission attempt over 100 messages):
  - **[SIMULATED ESTIMATE] QoS 0 (12% loss)**: **85 / 100** unique messages delivered (15 lost, 0 duplicates).
  - **[SIMULATED ESTIMATE] QoS 1 (12% loss + retransmission)**: **100 / 100** unique messages delivered (10 duplicate packets generated by simulated `PUBACK` loss, **0 duplicates** after `EndToEndSoftwareChain` deduplication).

## 5. Reproducible Demonstration Procedure on Any PC (`scripts/run_demo.py`)

Any team member or reviewer can execute the complete test and simulation suite in a single command from the repository root:

```bash
python scripts/run_demo.py
```

This script sequentially runs and verifies:
1. `python -m unittest discover -s tests -v` (all unit, gateway, and E2E integration tests)
2. `python tests/network_experiments.py` (real software measurements + theoretical bandwidth/QoS report)
3. `python -m simulator.main` (original dynamic CAN simulation)
4. `python -m simulator.demo_validation` (expanded 4-fault / 4-recovery validation)

Other manual entry points remain available:
- Graphical electrical engineering lab: `python -m simulator.gui_lab`
- Live CAN-to-MQTT bridge (with Mosquitto): `python -m gateway.can_mqtt_bridge`
- Node-RED dashboard validation: `cd dashboard && npm test`

## 6. Continuous Integration (`.github/workflows/`)

Three automated GitHub Actions workflows validate every push and pull request on `dev`:
- `simulation-validation.yml`: Runs the Python `unittest` discovery suite, `simulator.main`, `simulator.demo_validation`, C native CAN encoder/decoder tests (`tests/native`), and ECU firmware native tests.
- `gateway-validation.yml`: Validates `gateway/` modules and CAN-to-MQTT bridge tests.
- `dashboard-validation.yml`: Validates `dashboard/` Node-RED flows, event validator, and SQLite schema tests.
