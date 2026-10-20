# SmartHarness — Software Simulation Testing & Validation

## 1. Scope

This document describes the testing and validation of the SmartHarness Python software simulation.

The simulation includes:

- Four electrical circuits monitored by two independent simulated ECUs.
- Fault detection, recovery and event sequence management.
- Classical CAN fault-event encoding using standard 11-bit identifiers and 8-byte payloads.
- Virtual CAN communication using `python-can`.
- Gateway decoding of diagnostic frames.
- An experimental electrical diagnostics laboratory with simulated voltage, current, power and advanced fault scenarios.
- A graphical engineering demonstration.

The project remains a **software simulation**. Physical ESP32 communication, electrical CAN arbitration, bus termination, electromagnetic interference, MQTT, Node-RED and SQLite have not been validated.

## 2. Testing Environment

Testing was performed locally on Windows using Visual Studio Code and a Python virtual environment.

- Testing framework: Python `unittest`
- CAN simulation library: `python-can 4.6.1`
- Test directory: `tests/`
- Working branch: `feat/simulation-tests`
- Integration target: `develop`

## 3. Automated Test Coverage

### Circuit and ECU validation

Tests cover circuit initialization, ON/OFF conditions, simulated voltage, wire disconnection, fault detection, recovery, duplicate-event prevention, multiple faults and independent ECU behavior.

Sequence-number incrementing and uint16 wraparound are also verified.

### CAN protocol validation

Tests verify CAN IDs `0x080` and `0x081`, standard 11-bit identifiers, 8-byte payloads, fault codes, bit flags, voltage encoding, little-endian sequence numbers and protocol version.

### Gateway validation

Tests cover valid fault and recovery decoding, unknown CAN identifiers, extended frames, unsupported protocol versions and invalid payload lengths.

### Integration validation

Tests verify the software chain:

Circuit → ECU → CAN Encoder → Virtual CAN → Gateway Decoder

Scenarios include simultaneous faults, individual recoveries, multiple faults within one ECU and repeated scans without duplicate events.

### Experimental Engineering Lab

Additional tests cover simulated electrical behavior, including:

- Open circuit and recovery.
- Short circuit and simulated protection.
- Overload and undervoltage.
- Intermittent contact.
- Diagnostic debounce.
- Protection reset conditions.
- Independent ECU diagnostic state.
- Deterministic simulated noise.
- Compatibility with the existing CAN fault-event contract.

Advanced electrical diagnostic categories remain local to the experimental simulation unless explicitly supported by the shared CAN contract.

## 4. How to Run the Tests

From the SmartHarness repository root, activate the Python virtual environment and execute:

`python -m unittest discover -s tests -v`

To execute the original software simulation:

`python -m simulator.main`

To execute the expanded demonstration:

`python -m simulator.demo_validation`

To launch the graphical engineering laboratory:

`python -m simulator.gui_lab`

## 5. Observed Test Results

**Verified on the development PC — October 18, 2026**

| Metric | Observed result |
|---|---|
| Automated tests executed | 69 |
| Successful tests | 69 |
| Failures | 0 |
| Errors | 0 |
| Execution time | 0.456 seconds |
| Final result | OK |

The complete test suite ran successfully with the project's installed Python dependencies.

These results demonstrate successful execution of the covered software scenarios. They do not establish exhaustive system correctness or hardware reliability.

## 6. Observed Simulation Results

The original simulation successfully demonstrated normal operation, fault injection and recovery for ECU A and ECU B.

The expanded demonstration produced:

- Four healthy circuits with no new diagnostic events.
- Four simulated disconnections producing four fault events.
- No duplicate events during persistent faults.
- Four recoveries generated after reconnection.
- No duplicate events after returning to normal operation.

**Observed summary:** 4 faults and 4 recoveries.

The diagnostic events were encoded, transported using virtual CAN and decoded by the gateway.

## 7. Engineering Lab Limitations

The advanced laboratory uses simplified mathematical models of electrical behavior.

Voltage, current and power values are simulated, not measured using physical sensors.

The short-circuit protection and intermittent-contact scenarios are software models and have not been validated against real electrical circuits.

The existing CAN protocol is preserved. New experimental fault categories are not assigned unofficial CAN identifiers or fault codes.

## 8. Open Engineering Decisions

The current ECU implementation preserves the active fault state when a circuit is switched OFF. This behavior is documented by tests, but the intended production policy requires team agreement.

Additional strict CAN validation remains subject to review, including invalid circuit assignments, reserved flag bits, unsupported fault codes, contradictory flags, remote frames and other unsupported CAN frame types.

No incompatible protocol changes have been applied to the original simulator.

## 9. Future Validation

Further work may include:

- Team-approved stricter CAN gateway validation.
- Testing on ESP32 microcontrollers and a physical low-voltage CAN network.
- Verification of physical electrical measurements.
- MQTT communication and Node-RED supervision.
- SQLite diagnostic event history.
- Reliability tests on the final hardware prototype.

## 10. GitHub Integration

All changes should be reviewed through a Pull Request.

Source branch: `feat/simulation-tests`

Target branch: `develop`

The original simulation foundation must remain backward compatible, and shared CAN/MQTT contracts must not be changed without team approval.