"""Single-process virtual CAN -> real MQTT demo, no ESP32 required."""
import argparse
import json
import can
from gateway.can_mqtt_bridge import forward
from gateway.mqtt_publisher import MQTTPublisher
from simulator.circuit import Circuit
from simulator.ecu import ECU
from simulator.can_protocol import encode_fault


def run_demo(publisher):
    circuits = [Circuit(i, name) for i, name in enumerate(
        ("Headlights", "Indicators", "Brake lights", "Ventilation"), 1)]
    ecus = [ECU("A", circuits[:2]), ECU("B", circuits[2:])]
    for circuit in circuits:
        circuit.command_on = True
    receipts = []
    with can.Bus(interface="virtual", channel="mqtt-demo") as sender, can.Bus(
            interface="virtual", channel="mqtt-demo") as receiver:
        for connected in (True, False, True):
            for circuit in circuits:
                circuit.connected = connected
            for ecu in ecus:
                for event in ecu.scan():
                    sender.send(encode_fault(event))
                    message = receiver.recv(1)
                    if message is None:
                        raise RuntimeError("Missing simulated CAN event")
                    forward(message, publisher)
                    receipts.append(event)
                    print(json.dumps(event))
    return receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    publisher = MQTTPublisher(args.host, args.port)
    try:
        publisher.connect()
        if not publisher.wait_connected():
            raise TimeoutError("Start Mosquitto before this demo")
        # Wait for every PUBACK before shutting down the demo.
        class BlockingPublisher:
            def publish_fault(self, event, wait=False):
                return publisher.publish_fault(event, wait=True)
        run_demo(BlockingPublisher())
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    main()
