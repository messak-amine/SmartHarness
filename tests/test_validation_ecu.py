"""ECU state transitions, event sequence, and independence."""

import unittest
from unittest.mock import patch

from simulator.circuit import Circuit
from simulator.ecu import ECU


class ECUTests(unittest.TestCase):
    def setUp(self):
        self.headlights = Circuit(1, "Headlights")
        self.indicators = Circuit(2, "Indicators")
        self.headlights.command_on = True
        self.indicators.command_on = True
        self.ecu = ECU("A", [self.headlights, self.indicators])

    def test_healthy_circuits_produce_no_events(self):
        self.assertEqual(self.ecu.scan(), [])
        self.assertEqual(self.ecu.sequence, 0)
        self.assertEqual(self.ecu.active_faults, {1: False, 2: False})

    def test_repeated_healthy_scans_do_not_create_events(self):
        for _ in range(5):
            self.assertEqual(self.ecu.scan(), [])
        self.assertEqual(self.ecu.sequence, 0)

    def test_repeated_scans_after_recovery_are_silent(self):
        self.headlights.connected = False
        self.ecu.scan()
        self.headlights.connected = True
        self.ecu.scan()
        for _ in range(5):
            self.assertEqual(self.ecu.scan(), [])
        self.assertEqual(self.ecu.sequence, 2)

    def test_off_disconnected_circuit_creates_no_new_fault(self):
        self.headlights.command_on = False
        self.headlights.connected = False
        self.assertEqual(self.ecu.scan(), [])
        self.assertFalse(self.ecu.active_faults[1])

    def test_off_after_fault_preserves_fault_state_current_policy(self):
        """Characterization, not an endorsement of the OFF-state policy."""
        self.headlights.connected = False
        self.ecu.scan()
        self.headlights.command_on = False
        self.assertEqual(self.ecu.scan(), [])
        self.assertTrue(self.ecu.active_faults[1])
        self.assertEqual(self.ecu.sequence, 1)

    def test_on_again_while_still_disconnected_no_duplicate(self):
        self.headlights.connected = False
        self.ecu.scan()
        self.headlights.command_on = False
        self.ecu.scan()
        self.headlights.command_on = True
        self.assertEqual(self.ecu.scan(), [])
        self.assertTrue(self.ecu.active_faults[1])

    def test_reconnect_while_off_reports_recovery_when_on_again(self):
        self.headlights.connected = False
        self.ecu.scan()
        self.headlights.command_on = False
        self.headlights.connected = True
        self.assertEqual(self.ecu.scan(), [])
        self.headlights.command_on = True
        recovery = self.ecu.scan()
        self.assertEqual(len(recovery), 1)
        self.assertEqual((recovery[0]["fault_code"], recovery[0]["seq"]), (0, 2))

    def test_two_faults_in_one_ecu_are_separate_events(self):
        self.headlights.connected = False
        self.indicators.connected = False
        events = self.ecu.scan()
        self.assertEqual([e["circuit"] for e in events], [1, 2])
        self.assertEqual([e["seq"] for e in events], [1, 2])
        self.assertEqual(self.ecu.scan(), [])

    def test_one_fault_recovery_does_not_clear_other_fault(self):
        self.headlights.connected = False
        self.indicators.connected = False
        self.ecu.scan()
        self.headlights.connected = True
        events = self.ecu.scan()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["circuit"], 1)
        self.assertFalse(self.ecu.active_faults[1])
        self.assertTrue(self.ecu.active_faults[2])

    def test_two_ecus_have_independent_states_and_sequences(self):
        brake = Circuit(3, "Brake Lights")
        brake.command_on = True
        ecu_b = ECU("B", [brake])
        self.headlights.connected = False
        self.indicators.connected = False
        self.assertEqual([e["seq"] for e in self.ecu.scan()], [1, 2])
        self.assertEqual(ecu_b.scan(), [])
        self.assertFalse(ecu_b.active_faults[3])
        self.assertEqual(ecu_b.sequence, 0)
        brake.connected = False
        events_b = ecu_b.scan()
        self.assertEqual(len(events_b), 1)
        self.assertEqual(events_b[0]["seq"], 1)
        self.assertEqual(events_b[0]["ecu"], "B")
        self.assertEqual(self.ecu.sequence, 2)

    def test_sequence_wraps_65535_to_zero(self):
        self.ecu.sequence = 65534
        self.headlights.connected = False
        self.assertEqual(self.ecu.scan()[0]["seq"], 65535)
        self.headlights.connected = True
        self.assertEqual(self.ecu.scan()[0]["seq"], 0)
        self.headlights.connected = False
        self.assertEqual(self.ecu.scan()[0]["seq"], 1)

    def test_threshold_below_1000_is_fault(self):
        with patch.object(self.headlights, "read_voltage_mv", return_value=999):
            event = self.ecu.scan()[0]
        self.assertEqual(event["fault_code"], 1)
        self.assertEqual(event["voltage_mv"], 999)

    def test_threshold_equal_1000_is_healthy(self):
        with patch.object(self.headlights, "read_voltage_mv", return_value=1000):
            self.assertEqual(self.ecu.scan(), [])


if __name__ == "__main__":
    unittest.main()
