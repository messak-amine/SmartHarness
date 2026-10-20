"""Full model -> event -> encoded CAN -> virtual bus -> decoded gateway tests.

The virtual bus is software-only: these are NOT hardware timing/arbitration tests.
"""

import unittest
from uuid import uuid4

import can

from gateway.decoder import decode_fault
from simulator.can_protocol import encode_fault
from simulator.circuit import Circuit
from simulator.ecu import ECU


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.circuits = {
            1: Circuit(1, "Headlights"),
            2: Circuit(2, "Indicators"),
            3: Circuit(3, "Brake lights"),
            4: Circuit(4, "Ventilation"),
        }
        for circuit in self.circuits.values():
            circuit.command_on = True
        self.ecu_a = ECU("A", [self.circuits[1], self.circuits[2]])
        self.ecu_b = ECU("B", [self.circuits[3], self.circuits[4]])

        # A unique channel avoids test interference if two runs overlap.
        channel = "smartharness_integration_" + uuid4().hex
        self.bus_a = can.Bus(channel=channel, interface="virtual")
        self.bus_b = can.Bus(channel=channel, interface="virtual")
        self.gateway = can.Bus(channel=channel, interface="virtual")
        self.addCleanup(self.gateway.shutdown)
        self.addCleanup(self.bus_b.shutdown)
        self.addCleanup(self.bus_a.shutdown)

    def scan_and_transfer(self):
        sent = []
        for ecu, bus in ((self.ecu_a, self.bus_a), (self.ecu_b, self.bus_b)):
            for event in ecu.scan():
                frame = encode_fault(event)
                bus.send(frame)
                sent.append((event, frame))

        received = []
        for _ in sent:
            frame = self.gateway.recv(timeout=0.3)
            self.assertIsNotNone(frame, "Gateway missed an expected virtual CAN frame")
            self.assertEqual(len(frame.data), 8)
            received.append((frame, decode_fault(frame)))

        self.assertIsNone(self.gateway.recv(timeout=0.01), "Unexpected extra frame")
        return sent, received

    def test_four_healthy_circuits_emit_nothing(self):
        sent, received = self.scan_and_transfer()
        self.assertEqual(sent, [])
        self.assertEqual(received, [])

    def test_each_of_four_circuits_fault_and_recovery(self):
        for circuit_id in (1, 2, 3, 4):
            with self.subTest(circuit_id=circuit_id):
                self.circuits[circuit_id].connected = False
                _, received = self.scan_and_transfer()
                self.assertEqual(len(received), 1)
                frame, diagnostic = received[0]
                expected_ecu = "A" if circuit_id <= 2 else "B"
                expected_id = 0x080 if circuit_id <= 2 else 0x081
                self.assertEqual(frame.arbitration_id, expected_id)
                self.assertFalse(frame.is_extended_id)
                self.assertEqual(diagnostic["ecu"], expected_ecu)
                self.assertEqual(diagnostic["circuit"], circuit_id)
                self.assertTrue(diagnostic["active"])
                self.assertEqual(diagnostic["fault_code"], 1)
                self.assertEqual(diagnostic["voltage_mv"], 0)

                self.circuits[circuit_id].connected = True
                _, recovered = self.scan_and_transfer()
                self.assertEqual(len(recovered), 1)
                self.assertEqual(recovered[0][1]["circuit"], circuit_id)
                self.assertFalse(recovered[0][1]["active"])
                self.assertEqual(recovered[0][1]["fault_code"], 0)
                self.assertEqual(recovered[0][1]["voltage_mv"], 3300)

    def test_simultaneous_faults_on_different_ecus(self):
        self.circuits[1].connected = False
        self.circuits[4].connected = False
        sent, received = self.scan_and_transfer()
        self.assertEqual(len(sent), 2)
        self.assertEqual([frame.arbitration_id for frame, _ in received], [0x080, 0x081])
        self.assertEqual({event["circuit"] for _, event in received}, {1, 4})
        self.assertEqual([event["seq"] for _, event in received], [1, 1])

    def test_two_faults_on_same_ecu(self):
        self.circuits[1].connected = False
        self.circuits[2].connected = False
        _, received = self.scan_and_transfer()
        self.assertEqual(len(received), 2)
        self.assertEqual([diagnostic["circuit"] for _, diagnostic in received], [1, 2])
        self.assertEqual([diagnostic["seq"] for _, diagnostic in received], [1, 2])
        self.assertEqual({frame.arbitration_id for frame, _ in received}, {0x080})

    def test_multi_faults_individual_recoveries(self):
        for circuit in self.circuits.values():
            circuit.connected = False
        _, failures = self.scan_and_transfer()
        self.assertEqual(len(failures), 4)
        self.assertEqual({diag["circuit"] for _, diag in failures}, {1, 2, 3, 4})

        self.circuits[1].connected = True
        self.circuits[3].connected = True
        _, first_recoveries = self.scan_and_transfer()
        self.assertEqual({diag["circuit"] for _, diag in first_recoveries}, {1, 3})
        self.assertTrue(all(not diag["active"] for _, diag in first_recoveries))
        self.assertTrue(self.ecu_a.active_faults[2])
        self.assertTrue(self.ecu_b.active_faults[4])

        self.circuits[2].connected = True
        self.circuits[4].connected = True
        _, last_recoveries = self.scan_and_transfer()
        self.assertEqual({diag["circuit"] for _, diag in last_recoveries}, {2, 4})
        self.assertTrue(all(diag["fault_code"] == 0 for _, diag in last_recoveries))
        self.assertFalse(any(self.ecu_a.active_faults.values()))
        self.assertFalse(any(self.ecu_b.active_faults.values()))

    def test_repeated_scans_do_not_duplicate_frames(self):
        self.circuits[1].connected = False
        self.scan_and_transfer()
        for _ in range(3):
            sent, received = self.scan_and_transfer()
            self.assertEqual(sent, [])
            self.assertEqual(received, [])
        self.circuits[1].connected = True
        self.scan_and_transfer()
        for _ in range(3):
            self.assertEqual(self.scan_and_transfer(), ([], []))

    def test_can_payload_is_preserved_through_virtual_transport(self):
        self.circuits[3].connected = False
        sent, received = self.scan_and_transfer()
        self.assertEqual(len(sent), 1)
        self.assertEqual(bytes(sent[0][1].data), bytes(received[0][0].data))
        self.assertEqual(sent[0][0], received[0][1])


if __name__ == "__main__":
    unittest.main()
