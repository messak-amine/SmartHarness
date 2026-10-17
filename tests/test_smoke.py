
import unittest
import can

from simulator.circuit import Circuit
from simulator.ecu import ECU
from simulator.can_protocol import encode_fault
from gateway.decoder import decode_fault


class SmartHarnessSmokeTest(unittest.TestCase):

    def test_two_ecus_send_faults(self):
        headlights = Circuit(1, "Headlights")
        ventilation = Circuit(4, "Ventilation")

        headlights.command_on = True
        ventilation.command_on = True

        ecu_a = ECU("A", [headlights])
        ecu_b = ECU("B", [ventilation])

        # Both circuits initially operate normally.
        self.assertEqual(ecu_a.scan(), [])
        self.assertEqual(ecu_b.scan(), [])

        # Inject a disconnection on each ECU.
        headlights.connected = False
        ventilation.connected = False

        with (
            can.Bus(channel="smartharness_test", interface="virtual") as bus_a,
            can.Bus(channel="smartharness_test", interface="virtual") as bus_b,
            can.Bus(channel="smartharness_test", interface="virtual") as gateway
        ):
            for ecu, bus, expected_id, expected_circuit in [
                (ecu_a, bus_a, 0x080, 1),
                (ecu_b, bus_b, 0x081, 4)
            ]:
                event = ecu.scan()[0]
                bus.send(encode_fault(event))

                message = gateway.recv(timeout=1.0)

                self.assertIsNotNone(message)
                self.assertEqual(message.arbitration_id, expected_id)

                diagnostic = decode_fault(message)

                self.assertEqual(diagnostic["circuit"], expected_circuit)
                self.assertEqual(diagnostic["fault_code"], 1)
                self.assertTrue(diagnostic["active"])


if __name__ == "__main__":
    unittest.main()
