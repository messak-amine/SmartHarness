
import can
import json

from simulator.circuit import Circuit
from simulator.ecu import ECU
from simulator.can_protocol import encode_fault
from gateway.decoder import decode_fault


def process_scan(ecu, ecu_bus, gateway_bus):
    events = ecu.scan()

    if not events:
        print(f"ECU {ecu.name}: No new diagnostic events")

    for event in events:
        message = encode_fault(event)
        ecu_bus.send(message)

        received = gateway_bus.recv(timeout=1.0)

        if received is None:
            raise RuntimeError("Gateway did not receive CAN frame")

        diagnostic = decode_fault(received)

        print(f"[CAN] ID: 0x{received.arbitration_id:03X}")
        print("[GATEWAY]", json.dumps(diagnostic))


def main():
    # Create four simulated circuits.
    headlights = Circuit(1, "Headlights")
    indicators = Circuit(2, "Indicators")
    brake_lights = Circuit(3, "Brake Lights")
    ventilation = Circuit(4, "Ventilation")

    circuits = [headlights, indicators, brake_lights, ventilation]

    ecu_a = ECU("A", [headlights, indicators])
    ecu_b = ECU("B", [brake_lights, ventilation])

    # Initially, every circuit is commanded ON.
    for circuit in circuits:
        circuit.command_on = True

    # Three independent participants on one virtual channel.
    with (
        can.Bus(channel="smartharness", interface="virtual") as bus_a,
        can.Bus(channel="smartharness", interface="virtual") as bus_b,
        can.Bus(channel="smartharness", interface="virtual") as gateway_bus
    ):
        print("\n=== NORMAL OPERATION ===")
        process_scan(ecu_a, bus_a, gateway_bus)
        process_scan(ecu_b, bus_b, gateway_bus)

        print("\n=== FAULT INJECTION ===")
        headlights.connected = False
        ventilation.connected = False

        process_scan(ecu_a, bus_a, gateway_bus)
        process_scan(ecu_b, bus_b, gateway_bus)

        print("\n=== FAULT RECOVERY ===")
        headlights.connected = True
        ventilation.connected = True

        process_scan(ecu_a, bus_a, gateway_bus)
        process_scan(ecu_b, bus_b, gateway_bus)


if __name__ == "__main__":
    main()
