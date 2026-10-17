
import can


def encode_fault(event):
    can_id = 0x080 if event["ecu"] == "A" else 0x081

    flags = 0

    if event["command_on"]:
        flags |= 0x01

    if event["active"]:
        flags |= 0x02

    voltage = event["voltage_mv"]
    sequence = event["seq"]

    payload = [
        event["circuit"],
        event["fault_code"],
        *voltage.to_bytes(2, "little"),
        flags,
        *sequence.to_bytes(2, "little"),
        0x01
    ]

    return can.Message(
        arbitration_id=can_id,
        is_extended_id=False,
        data=payload
    )
