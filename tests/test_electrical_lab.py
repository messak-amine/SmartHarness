"""Standalone deterministic checks for the experimental engineering model."""
import unittest
from simulator.electrical_lab import ElectricalLab


class ElectricalLabTests(unittest.TestCase):
    def setUp(self):
        self.lab = ElectricalLab()

    def tick(self, n=1):
        result = None
        for _ in range(n):
            result = self.lab.step()
        return result

    def test_four_healthy_circuits_have_readings(self):
        readings, events = self.tick(2)
        self.assertEqual(set(readings), {1, 2, 3, 4})
        self.assertEqual(events, [])
        self.assertTrue(all(v.diagnostic == "NORMAL" for v in readings.values()))

    def test_nominal_voltage_and_current_are_nonzero(self):
        readings, _ = self.tick()
        self.assertTrue(all(3000 <= r.voltage_mv <= 3300 for r in readings.values()))
        self.assertTrue(all(0 < r.current_ma < 750 for r in readings.values()))

    def test_open_circuit_detected_after_debounce(self):
        self.lab.set_mode(1, "OPEN")
        _, first = self.tick()
        readings, second = self.tick()
        self.assertEqual(first, [])
        self.assertEqual((readings[1].voltage_mv, readings[1].current_ma), (0, 0))
        self.assertEqual((second[0].current, second[0].kind), ("OPEN", "FAULT"))

    def test_open_recovery_is_reported_once(self):
        self.lab.set_mode(1, "OPEN")
        self.tick(2)
        self.lab.set_mode(1, "NORMAL")
        self.tick()
        _, events = self.tick()
        self.assertEqual(events[0].kind, "RECOVERY")
        self.assertEqual(events[0].previous, "OPEN")
        self.assertEqual(self.tick()[1], [])

    def test_overload_has_high_current_and_alarm(self):
        self.lab.set_mode(2, "OVERLOAD")
        readings, events = self.tick(2)
        self.assertGreater(readings[2].current_ma, 750)
        self.assertEqual(events[0].current, "OVERLOAD")
        self.assertFalse(self.lab.channels[2].fuse_tripped)

    def test_short_circuit_precedes_protection_trip(self):
        self.lab.set_mode(3, "SHORT")
        _, events = self.tick(2)
        self.assertEqual(events[0].current, "SHORT")
        readings, _ = self.tick()
        self.assertTrue(readings[3].protection_tripped)
        self.assertEqual(readings[3].current_ma, 0)
        _, events = self.tick()
        self.assertEqual(events[0].current, "TRIPPED")

    def test_fuse_remains_tripped_until_reset(self):
        self.lab.set_mode(1, "SHORT")
        self.tick(4)
        self.lab.set_mode(1, "NORMAL")
        self.tick(4)
        self.assertTrue(self.lab.channels[1].fuse_tripped)
        self.lab.reset_fuse(1)
        readings, _ = self.tick(2)
        self.assertFalse(readings[1].protection_tripped)
        self.assertEqual(self.lab.channels[1].stable, "NORMAL")

    def test_cannot_reset_fuse_while_short_remains(self):
        self.lab.set_mode(1, "SHORT")
        self.tick(4)
        with self.assertRaises(ValueError):
            self.lab.reset_fuse(1)

    def test_low_voltage_detected(self):
        self.lab.set_mode(4, "UNDERVOLTAGE")
        readings, events = self.tick(2)
        self.assertLess(readings[4].voltage_mv, 2700)
        self.assertEqual(events[0].current, "UNDERVOLTAGE")

    def test_intermittent_contact_alternates(self):
        self.lab.set_mode(1, "INTERMITTENT")
        seen = [self.tick()[0][1].actual_mode for _ in range(12)]
        self.assertEqual(seen[:4], ["NORMAL"] * 4)
        self.assertEqual(seen[4:8], ["OPEN"] * 4)
        self.assertEqual(seen[8:12], ["NORMAL"] * 4)

    def test_off_does_not_generate_false_new_fault(self):
        self.lab.set_command(1, False)
        self.lab.set_mode(1, "OPEN")
        readings, _ = self.tick(5)
        self.assertEqual(readings[1].diagnostic, "OFF")
        self.assertFalse(any(e.circuit == 1 for e in self.lab.events))

    def test_off_preserves_latched_fault_until_on(self):
        self.lab.set_mode(1, "OPEN")
        self.tick(2)
        self.lab.set_command(1, False)
        self.lab.set_mode(1, "NORMAL")
        self.tick(3)
        self.assertEqual(self.lab.channels[1].stable, "OPEN")
        self.lab.set_command(1, True)
        self.tick(2)
        self.assertEqual(self.lab.channels[1].stable, "NORMAL")

    def test_two_ecus_independent_local_sequences(self):
        self.lab.set_mode(1, "OPEN")
        self.lab.set_mode(4, "OPEN")
        _, events = self.tick(2)
        self.assertEqual([(e.ecu, e.seq) for e in events], [("A", 1), ("B", 1)])

    def test_no_duplicate_persistent_fault_events(self):
        self.lab.set_mode(1, "OPEN")
        self.tick(2)
        _, events = self.tick(9)
        self.assertEqual(events, [])
        self.assertEqual(len(self.lab.events), 1)

    def test_sequence_rollover(self):
        self.lab.sequences["A"] = 65535
        self.lab.set_mode(1, "OPEN")
        _, events = self.tick(2)
        self.assertEqual(events[0].seq, 0)

    def test_invalid_modes_and_noise_level_rejected(self):
        with self.assertRaises(ValueError):
            self.lab.set_mode(1, "FIRE")
        with self.assertRaises(ValueError):
            ElectricalLab(noise_mv=301)

    def test_reproducible_noise_with_fixed_seed(self):
        a, b = ElectricalLab(noise_mv=25, seed=7), ElectricalLab(noise_mv=25, seed=7)
        self.assertEqual([a.step()[0][1].voltage_mv for _ in range(8)],
                         [b.step()[0][1].voltage_mv for _ in range(8)])
