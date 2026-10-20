# SmartHarness — Experimental Electrical Engineering Lab

**Scope:** optional advanced *software-only* experiment, built alongside the team's initial `Circuit → ECU → CAN → Gateway` prototype. It is **not** a change to the official CAN or MQTT protocol, and it does not replace the initial simulator or the existing tests.

## Start (Windows, VS Code Git Bash)

At the root of the existing `SmartHarness` repository and with the `.venv` activated:

```bash
python -m pip install -r requirements.txt
python -m simulator.gui_lab
```

If you downloaded a ZIP, extract its contents *inside the SmartHarness repository root*. The ZIP contains **only new paths**:

- `simulator/electrical_lab.py` — reproducible low-voltage resistive model, local classifier, event/state histories, and original-contract CAN adapter.
- `simulator/lab_visuals.py` — animated, on-screen lights/signals/fan.
- `simulator/gui_lab.py` — interactive UI, charts, logging, 8 guided scenarios, CSV export, regression-test launcher.
- `tests/test_electrical_lab.py` — 17 new deterministic pure-model tests.
- `tests/test_electrical_bridge.py` — 4 new CAN virtual compatibility tests.
- `docs/engineering_lab.md` — this document.

**The archive does not replace** `simulator/circuit.py`, `simulator/ecu.py`, `simulator/can_protocol.py`, `gateway/decoder.py`, the contracts, or any of your 48 previously passing tests. Don't commit this optional lab until the team reviews the proposed simulation assumptions.

## What changes technically?

Before, the circuits produced 0 or 3300 mV and the ECU could only identify a disconnected wire from a threshold. This experimental module estimates a *synthetic* voltage and current under several load types and runs a more detailed **local** state machine:

- Healthy resistive load.
- Open wire: current 0 mA and load-side available voltage shown as 0 mV.
- Short circuit: highly reduced load resistance and excess modeled current.
- Overload: increased current, below the modeled short threshold.
- Undervoltage: lowered synthetic supply voltage.
- Intermittent contact: deterministic alternating connectivity.
- Protection trip: a **simulated** electronic/fuse-style latch requiring fault removal and reset.

The UI has three tabs: **Circuits & Controls**, **Measurements & Graphs**, and **History & CAN**. Try a scenario from the right-hand selector; use the pause/step buttons to discuss each state. It can export local and virtual-CAN diagnostic logs to CSV.

## Explicit model assumptions — not physical specifications

The model assumes a simplified 3.3 V DC source, 0.25 Ω source resistance, and constant resistive loads (8, 12, 10, 9 Ω). For a connected load, idealized current is `I = Vsource / (Rsource + Rload)`, and load-side voltage is `Vload = I * Rload`. Power is `P = Vload * I`.

Simulated fault parameters:

| Parameter | Educational value |
| --- | ---: |
| Under-voltage source | 2.2 V |
| Overload resistance | 2.5 Ω |
| Short resistance | 0.15 Ω |
| Undervoltage classification below | 2700 mV |
| Overload classification at or above | 750 mA |
| Short classification at or above | 2000 mA |
| Open classification at or below | 50 mA |
| Synthetic protection trips at or above | 2500 mA for 3 scans |
| Local diagnostic debounce | 2 consecutive 0.5 s scans |
| Intermittent period | Alternates every 4 scans |

Model order is **protection → short → overload → open → undervoltage → normal**. Fault transitions are debounced. OFF circuits hold their previous stable classification until scanning resumes, consistent with the *current* baseline ECU's skip-OFF policy, which remains subject to team review. The synthetic trip is **not** a real automotive fuse time-current characteristic. The model does not cover heat, battery dynamics, inductive fans, body-controller logic, PWM, or physical current limiting. Its high short-circuit current values must never be recreated on real circuits without appropriate protection.

## CAN contract compatibility: particularly important

**Official 11-bit CAN ID `0x080` for ECU A, `0x081` for ECU B and 8-byte version-1 payload remain unchanged.** The `BaselineCANBridge` uses the *existing* `Circuit`, `ECU`, `encode_fault()` and `decode_fault()` for actual simulated *wire-open* and *wire-recovery* events over `python-can`'s virtual bus.

The new fault classes `SHORT`, `OVERLOAD`, `UNDERVOLTAGE` and `TRIPPED` are **NOT transmitted as new CAN fault codes**. They appear only as **experimental local diagnostics** in a separate GUI table. CAN code 2 remains reserved. Distinguish **local diagnostics** from **real virtual CAN messages** when demonstrating the system. The local debouncer may take 2 scans, while the original ECU's open-wire CAN detection still happens on the first scan; they are separate algorithms by design.

The circuit "Indicators" remains one channel, so its two lights are synchronized, not true independent left/right indicators. Rotation speed and vehicle artwork are illustrative only.

## Validation / execution evidence

Run the full suite after extraction:

```bash
python -m unittest discover -s tests -v
python -m simulator.main
python -m simulator.demo_validation
python -m simulator.gui_lab
```


### Observed Results — Windows, October 18, 2026

The full automated test suite was executed locally
using the project's Python virtual environment
and python-can 4.6.1.

- Total automated tests: 69
- Passed: 69
- Failures: 0
- Errors: 0
- Execution time: 0.456 seconds
- Final unittest result: OK

The original simulator was also rerun successfully,
confirming normal operation, ECU A/B fault detection,
and recovery events.

The 69 tests include 48 baseline and validation tests
plus 21 tests for the experimental Engineering Lab.

### Validation Limitations

The results validate the covered software scenarios
and virtual CAN communication.

Physical ESP32 hardware, CAN arbitration timing,
electrical protection, MQTT, Node-RED and SQLite
have not been validated.

Advanced electrical fault classifications remain
experimental and local to the Engineering Lab.


## Suggested teacher demonstration (~3 minutes)

1. Show all four normal circuits and one voltage/current trace.
2. Run **Court-circuit + protection**, pause to explain current spike, short classification after two scans and simulated protection trip; remove short and rearm.
3. Run **Panne intermittente**, explaining alternating readings, filtered local events, and why repeated scans don't flood the log.
4. Run **Déconnexion et récupération** and point to the CAN table: ID `0x080`, 8-byte payload, code 1 then code 0. **Contrast** with the other fault types, which are local-only at this stage.
5. Show the tests within the GUI/VS Code Test Explorer and state what is *not* verified until hardware arrives.

## Engineering decisions to review as a team

Before integrating any of these advanced fault categories into the actual shared communication protocol: agree on voltage/current measurement architecture, thresholds, transient handling, short-circuit protection strategy, fault-code assignments, gateway validation policy, and MQTT representation. Those decisions should be approved by the team coordinator rather than silently changing the v0.1 contracts.
