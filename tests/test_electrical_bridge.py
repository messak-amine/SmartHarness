"""Real python-can virtual transport checks (run on developer's Windows PC)."""
import unittest
from simulator.electrical_lab import BaselineCANBridge, ElectricalLab


class LabCANCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.lab = ElectricalLab()
        self.bridge = BaselineCANBridge()

    def tearDown(self):
        self.bridge.close()

    def step(self):
        readings, events = self.lab.step()
        return events, self.bridge.step(self.lab, readings)

    def test_wire_open_sends_compatible_can_frame(self):
        self.lab.set_mode(1, "OPEN")
        _, frames = self.step()
        self.assertEqual(len(frames), 1)
        frame, msg = frames[0]
        self.assertEqual((frame.arbitration_id, len(frame.data)), (0x080, 8))
        self.assertEqual((msg["circuit"], msg["fault_code"]), (1, 1))

    def test_wire_recovery_uses_existing_fault_code_zero(self):
        self.lab.set_mode(4, "OPEN")
        self.step()
        self.lab.set_mode(4, "NORMAL")
        _, frames = self.step()
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0].arbitration_id, 0x081)
        self.assertEqual(frames[0][1]["fault_code"], 0)
        self.assertEqual(self.step()[1], [])

    def test_noncontract_fault_does_not_fake_can_code(self):
        self.lab.set_mode(3, "SHORT")
        self.lab.set_mode(4, "OVERLOAD")
        for _ in range(4):
            _, frames = self.step()
            self.assertEqual(frames, [])
        self.assertTrue(any(e.current == "SHORT" for e in self.lab.events))
        self.assertTrue(any(e.current == "OVERLOAD" for e in self.lab.events))

    def test_simultaneous_open_faults_from_two_ecus(self):
        self.lab.set_mode(1, "OPEN")
        self.lab.set_mode(3, "OPEN")
        _, frames = self.step()
        self.assertEqual({f.arbitration_id for f,_ in frames}, {0x080,0x081})
        self.assertEqual(len(frames), 2)
