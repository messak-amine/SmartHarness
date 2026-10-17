
import can
import json
from gateway.decoder import decode_fault

from simulator.circuit import Circuit
from simulator.ecu import ECU
from simulator.can_protocol import encode_fault


headlights = Circuit(1, "Headlights")
headlights.command_on = True

ecu_a = ECU("A", [headlights])

# Simulate a disconnected wire.
headlights.connected = False
event = ecu_a.scan()[0]

# Create two participants on the same virtual CAN bus.
with can.Bus(channel="smartharness", interface="virtual") as sender, \
     can.Bus(channel="smartharness", interface="virtual") as receiver:

    message = encode_fault(event)
    sender.send(message)

    received = receiver.recv(timeout=1.0)

    if received is not None:
        print("CAN ID:", hex(received.arbitration_id))
        print("CAN data:", list(received.data))

        diagnostic = decode_fault(received)

        print("\nGateway decoded JSON:")
        print(json.dumps(diagnostic, indent=2))
    else:
        print("No CAN message received")
