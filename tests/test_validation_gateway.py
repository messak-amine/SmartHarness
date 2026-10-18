"""Gateway decoding and defensive rejection of malformed CAN fault frames."""

import unittest

import can

from gateway.decoder import decode_fault
from simulator.can_protocol import encode_fault

def sample_event(**changes):
    event = {
        "ecu": "A", "circuit": 1, "fault_code": 1,
        "voltage_mv": 0, "active": True,
        "command_on": True, "seq": 1,
    }
    event.update(changes)
    return event


def fault_message(data=None, **changes):
    payload = bytes.fromhex("01 01 00 00 03 01 00 01") if data is None else data
    return can.Message(arbitration_id=0x080, is_extended_id=False, data=payload, **changes)


class GatewayTests(unittest.TestCase):
    def test_valid_fault_decodes_correctly(self):
        self.assertEqual(decode_fault(fault_message()), {
            "ecu": "A", "circuit": 1, "fault_code": 1,
            "active": True, "voltage_mv": 0, "command_on": True, "seq": 1,
        })

    def test_round_trip_recovers_voltage_and_sequence(self):
        event = sample_event(
            ecu="B", circuit=4, fault_code=0, active=False,
            voltage_mv=0x1234, seq=0xABCD,
        )
        self.assertEqual(decode_fault(encode_fault(event)), event)

    def test_round_trip_fault_and_recovery(self):
        for event in (
            sample_event(voltage_mv=999, seq=65535),
            sample_event(fault_code=0, active=False, voltage_mv=3300, seq=0),
        ):
            with self.subTest(event=event):
                self.assertEqual(decode_fault(encode_fault(event)), event)

    def test_unknown_can_id_rejected(self):
        message = can.Message(arbitration_id=0x777, is_extended_id=False,
                              data=bytes.fromhex("01 01 00 00 03 01 00 01"))
        with self.assertRaisesRegex(ValueError, "CAN ID"):
            decode_fault(message)

    def test_planned_telemetry_id_not_accepted_as_fault(self):
        message = can.Message(arbitration_id=0x180, is_extended_id=False,
                              data=bytes.fromhex("01 01 00 00 03 01 00 01"))
        with self.assertRaises(ValueError):
            decode_fault(message)

    def test_extended_frame_rejected(self):
        message = can.Message(arbitration_id=0x080, is_extended_id=True,
                              data=bytes.fromhex("01 01 00 00 03 01 00 01"))
        with self.assertRaises(ValueError):
            decode_fault(message)

    def test_wrong_payload_lengths_rejected(self):
        for length in (0, 7, 9):
            with self.subTest(length=length):
                message = fault_message(data=bytes([0] * length))
                with self.assertRaisesRegex(ValueError, "length"):
                    decode_fault(message)

    def test_wrong_protocol_version_rejected(self):
        message = fault_message(data=bytes.fromhex("01 01 00 00 03 01 00 02"))
        with self.assertRaisesRegex(ValueError, "version"):
            decode_fault(message)


if __name__ == "__main__":
    unittest.main()
