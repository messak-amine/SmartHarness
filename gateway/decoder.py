
CAN_IDS = {
    0x080: "A",
    0x081: "B"
}


def decode_fault(message):
    if message.is_remote_frame or message.is_error_frame or message.is_fd:
        raise ValueError("Expected Classical CAN data frame")
    if message.is_extended_id or message.arbitration_id not in CAN_IDS:
        raise ValueError("Unknown fault CAN ID")

    if len(message.data) != 8 or message.dlc != 8:
        raise ValueError("Invalid CAN payload length")

    data = message.data

    if data[7] != 1:
        raise ValueError("Unsupported protocol version")

    allowed = (1, 2) if CAN_IDS[message.arbitration_id] == "A" else (3, 4)
    if data[0] not in allowed:
        raise ValueError("Circuit does not belong to ECU")
    if data[1] not in (0, 1, 2) or data[4] & 0xFC:
        raise ValueError("Invalid fault code or reserved flags")
    if bool(data[4] & 2) != (data[1] != 0):
        raise ValueError("Inconsistent active flag and fault code")

    return {
        "ecu": CAN_IDS[message.arbitration_id],
        "circuit": data[0],
        "fault_code": data[1],
        "active": bool(data[4] & 0x02),
        "voltage_mv": int.from_bytes(data[2:4], "little"),
        "command_on": bool(data[4] & 0x01),
        "seq": int.from_bytes(data[5:7], "little")
    }
