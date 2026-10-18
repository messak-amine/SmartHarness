
import unittest

from simulator.circuit import Circuit
from simulator.ecu import ECU


class TestECU(unittest.TestCase):

    def test_detect_disconnection(self):
        circuit = Circuit(1, "Headlights")
        circuit.command_on = True

        ecu = ECU("A", [circuit])

        circuit.connected = False

        events = ecu.scan()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["fault_code"], 1)
        self.assertTrue(events[0]["active"])

        self.assertEqual(events[0]["circuit"], 1)
        self.assertEqual(events[0]["seq"], 1)

    def test_fault_recovery(self):
        circuit = Circuit(1, "Headlights")
        circuit.command_on = True

        ecu = ECU("A", [circuit])

        # Simulate a disconnection
        circuit.connected = False
        ecu.scan()

        # Reconnect the circuit
        circuit.connected = True
        events = ecu.scan()

        # Verify the recovery event
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["fault_code"], 0)
        self.assertFalse(events[0]["active"])
        self.assertEqual(events[0]["voltage_mv"], 3300)
        self.assertEqual(events[0]["seq"], 2)

    def test_no_duplicate_fault_events(self):
        circuit = Circuit(1, "Headlights")
        circuit.command_on = True
        circuit.connected = False

        ecu = ECU("A", [circuit])

        # First scan: detect the fault
        first_events = ecu.scan()

        # Second scan: fault still exists
        second_events = ecu.scan()

        # Third scan: still disconnected
        third_events = ecu.scan()

        self.assertEqual(len(first_events), 1)
        self.assertEqual(second_events, [])
        self.assertEqual(third_events, [])
        self.assertEqual(ecu.sequence, 1)

    def test_no_duplicate_recovery_events(self):
        circuit = Circuit(1, "Headlights")
        circuit.command_on = True
        circuit.connected = False

        ecu = ECU("A", [circuit])

        # First scan: fault detected
        fault_events = ecu.scan()

        # Reconnect the wire
        circuit.connected = True
        recovery_events = ecu.scan()

        # Scan again after recovery
        second_scan = ecu.scan()
        third_scan = ecu.scan()

        self.assertEqual(len(fault_events), 1)
        self.assertEqual(len(recovery_events), 1)
        self.assertEqual(recovery_events[0]["fault_code"], 0)

        self.assertEqual(second_scan, [])
        self.assertEqual(third_scan, [])
        self.assertEqual(ecu.sequence, 2)
