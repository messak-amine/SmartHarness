"""Expanded SmartHarness software-only demo; no ESP32 or physical CAN required.

Run: python -m simulator.demo_validation
"""

import json

import can

from gateway.decoder import decode_fault
from simulator.can_protocol import encode_fault
from simulator.circuit import Circuit
from simulator.ecu import ECU


def main():
    circuits = [
        Circuit(1, "Headlights"),
        Circuit(2, "Indicators"),
        Circuit(3, "Brake Lights"),
        Circuit(4, "Ventilation"),
    ]
    for circuit in circuits:
        circuit.command_on = True

    ecu_a = ECU("A", circuits[:2])
    ecu_b = ECU("B", circuits[2:])
    observed = []

    with (
        can.Bus(channel="smartharness_extended_demo", interface="virtual") as bus_a,
        can.Bus(channel="smartharness_extended_demo", interface="virtual") as bus_b,
        can.Bus(channel="smartharness_extended_demo", interface="virtual") as gateway,
    ):
        def scan(label):
            print("\n===", label, "===")
            count = 0
            for ecu, sender in ((ecu_a, bus_a), (ecu_b, bus_b)):
                for event in ecu.scan():
                    sender.send(encode_fault(event))
                    frame = gateway.recv(timeout=1.0)
                    if frame is None:
                        raise RuntimeError("Missing virtual CAN frame at gateway")
                    diagnosis = decode_fault(frame)
                    observed.append(diagnosis)
                    print(f"CAN 0x{frame.arbitration_id:03X} ->", json.dumps(diagnosis))
                    count += 1
            if count == 0:
                print("No new events (expected in normal/unchanged states)")

        print("SmartHarness — EXPANDED SOFTWARE SIMULATION (no hardware)")
        scan("1. ALL FOUR CIRCUITS HEALTHY")

        for circuit in circuits:
            circuit.connected = False
        scan("2. FOUR DISCONNECTIONS")
        scan("3. PERSISTENT FAULTS: NO DUPLICATES")

        circuits[0].connected = True
        circuits[2].connected = True
        scan("4. HEADLIGHTS AND BRAKE LIGHTS RECOVER")

        circuits[1].connected = True
        circuits[3].connected = True
        scan("5. INDICATORS AND VENTILATION RECOVER")
        scan("6. ALL HEALTHY: NO DUPLICATES")

    faults = sum(item["fault_code"] == 1 for item in observed)
    recoveries = sum(item["fault_code"] == 0 for item in observed)
    print(f"\nSIMULATED EVENTS: {faults} faults, {recoveries} recoveries")
    if (faults, recoveries) != (4, 4):
        raise RuntimeError("Unexpected number of simulation events")


if __name__ == "__main__":
    main()
