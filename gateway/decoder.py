
CAN_IDS = {
    0x080: "A",
    0x081: "B"
}


def decode_fault(message):
    if message.is_extended_id or message.arbitration_id not in CAN_IDS:
        raise ValueError("Unknown fault CAN ID")

    if len(message.data) != 8:
        raise ValueError("Invalid CAN payload length")

    data = message.data

    if data[7] != 1:
        raise ValueError("Unsupported protocol version")

    return {
        "ecu": CAN_IDS[message.arbitration_id],
        "circuit": data[0],
        "fault_code": data[1],
        "active": bool(data[4] & 0x02),
        "voltage_mv": int.from_bytes(data[2:4], "little"),
        "command_on": bool(data[4] & 0x01),
        "seq": int.from_bytes(data[5:7], "little")
    }
