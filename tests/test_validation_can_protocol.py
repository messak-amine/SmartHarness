"""Fault-event CAN format checks against contracts/can_protocol.md."""

import unittest

from simulator.can_protocol import encode_fault


def sample_event(**changes):
    event = {
        "ecu": "A", "circuit": 1, "fault_code": 1,
        "voltage_mv": 0, "active": True,
        "command_on": True, "seq": 1,
    }
    event.update(changes)
    return event


class CANEncodingTests(unittest.TestCase):
    def test_ecu_a_uses_id_080(self):
        self.assertEqual(encode_fault(sample_event()).arbitration_id, 0x080)

    def test_ecu_b_uses_id_081(self):
        self.assertEqual(encode_fault(sample_event(ecu="B", circuit=3)).arbitration_id, 0x081)

    def test_standard_classical_can_frame(self):
        message = encode_fault(sample_event())
        self.assertFalse(message.is_extended_id)
        self.assertFalse(message.is_fd)
        self.assertFalse(message.is_remote_frame)

    def test_exactly_eight_payload_bytes(self):
        message = encode_fault(sample_event())
        self.assertEqual(len(message.data), 8)
        self.assertEqual(message.dlc, 8)

    def test_example_payload_matches_contract(self):
        self.assertEqual(
            bytes(encode_fault(sample_event()).data),
            bytes.fromhex("01 01 00 00 03 01 00 01"),
        )

    def test_voltage_little_endian_and_sequence_little_endian(self):
        message = encode_fault(sample_event(voltage_mv=0x1234, seq=0xABCD))
        self.assertEqual(message.data[2:4], bytes([0x34, 0x12]))
        self.assertEqual(message.data[5:7], bytes([0xCD, 0xAB]))

    def test_recovery_flags_are_command_on_without_active(self):
        message = encode_fault(sample_event(fault_code=0, active=False, voltage_mv=3300))
        self.assertEqual(message.data[1], 0)
        self.assertEqual(message.data[2:4], (3300).to_bytes(2, "little"))
        self.assertEqual(message.data[4], 0x01)

    def test_flags_when_command_off_and_fault_inactive(self):
        message = encode_fault(sample_event(fault_code=0, active=False, command_on=False))
        self.assertEqual(message.data[4], 0x00)

    def test_maximum_uint16_fields(self):
        message = encode_fault(sample_event(voltage_mv=65535, seq=65535))
        self.assertEqual(message.data[2:4], b"\xff\xff")
        self.assertEqual(message.data[5:7], b"\xff\xff")
        self.assertEqual(message.data[7], 1)


if __name__ == "__main__":
    unittest.main()
