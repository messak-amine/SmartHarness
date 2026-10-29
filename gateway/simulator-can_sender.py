import can

from simulator.circuit import Circuit
from simulator.ecu import ECU
from simulator.can_protocol import encode_fault


def send_events(ecu, bus):
    for event in ecu.scan():
        message = encode_fault(event)
        bus.send(message)
        print(f"[ECU {ecu.name}] CAN event sent")


def main():
    headlights = Circuit(1, "Headlights")
    ventilation = Circuit(4, "Ventilation")

    ecu_a = ECU("A", [headlights])
    ecu_b = ECU("B", [ventilation])

    headlights.command_on = True
    ventilation.command_on = True

    with can.Bus(channel="smartharness", interface="virtual") as bus:

        print("=== FAULT INJECTION ===")

        headlights.connected = False
        ventilation.connected = False

        send_events(ecu_a, bus)
        send_events(ecu_b, bus)

        print("=== FAULT RECOVERY ===")

        headlights.connected = True
        ventilation.connected = True

        send_events(ecu_a, bus)
        send_events(ecu_b, bus)


if __name__ == "__main__":
    main()