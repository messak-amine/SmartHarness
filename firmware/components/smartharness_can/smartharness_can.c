
#include "smartharness_can.h"
#include <stddef.h>

bool sh_can_encode_fault(
    const sh_fault_event_t *event,
    sh_can_frame_t *frame
)
{
    // Check that both pointers are valid.
    if (event == NULL || frame == NULL) {
        return false;
    }

    // Check ECU and its assigned circuits.
    uint32_t can_id;

    if (event->ecu == 'A' &&
        event->circuit >= 1 && event->circuit <= 2) {
        can_id = SH_CAN_ECU_A_ID;
    }
    else if (event->ecu == 'B' &&
             event->circuit >= 3 && event->circuit <= 4) {
        can_id = SH_CAN_ECU_B_ID;
    }
    else {
        return false;
    }

    // Version 1 currently supports disconnection and recovery.
    if (event->fault_code > 1) {
        return false;
    }

    if (event->active != (event->fault_code == 1)) {
        return false;
    }

    // Build an 8-byte Classical CAN frame.
    sh_can_frame_t result = {0};

    result.identifier = can_id;
    result.length = SH_CAN_PAYLOAD_SIZE;
    result.is_extended = false;

    // Byte 0: Circuit ID
    result.data[0] = event->circuit;

    // Byte 1: Fault code
    result.data[1] = event->fault_code;

    // Bytes 2-3: Voltage (little-endian)
    result.data[2] = (uint8_t)(event->voltage_mv & 0xFF);
    result.data[3] = (uint8_t)(event->voltage_mv >> 8);

    // Byte 4: Status flags
    result.data[4] = 0;

    if (event->command_on) {
        result.data[4] |= 0x01;
    }

    if (event->active) {
        result.data[4] |= 0x02;
    }

    // Bytes 5-6: Sequence number (little-endian)
    result.data[5] = (uint8_t)(event->sequence & 0xFF);
    result.data[6] = (uint8_t)(event->sequence >> 8);

    // Byte 7: Protocol version
    result.data[7] = SH_CAN_PROTOCOL_VERSION;

    *frame = result;

    return true;
}

bool sh_can_decode_fault(
    const sh_can_frame_t *frame,
    sh_fault_event_t *event
)
{
    if (frame == NULL || event == NULL) {
        return false;
    }

    // Validate CAN frame format.
    if (frame->is_extended ||
        frame->length != SH_CAN_PAYLOAD_SIZE ||
        frame->data[7] != SH_CAN_PROTOCOL_VERSION) {
        return false;
    }

    // Identify the ECU and validate circuit ownership.
    char ecu;

    if (frame->identifier == SH_CAN_ECU_A_ID &&
        frame->data[0] >= 1 && frame->data[0] <= 2) {
        ecu = 'A';
    }
    else if (frame->identifier == SH_CAN_ECU_B_ID &&
             frame->data[0] >= 3 && frame->data[0] <= 4) {
        ecu = 'B';
    }
    else {
        return false;
    }

    uint8_t fault_code = frame->data[1];
    uint8_t flags = frame->data[4];

    // Reject unsupported codes and reserved flag bits.
    if (fault_code > 1 || (flags & 0xFC) != 0) {
        return false;
    }

    bool active = (flags & 0x02) != 0;

    // Fault code and active state must be consistent.
    if (active != (fault_code == 1)) {
        return false;
    }

    sh_fault_event_t result = {0};

    result.ecu = ecu;
    result.circuit = frame->data[0];
    result.fault_code = fault_code;

    // Decode 16-bit little-endian voltage.
    result.voltage_mv =
        (uint16_t)frame->data[2] |
        ((uint16_t)frame->data[3] << 8);

    result.command_on = (flags & 0x01) != 0;
    result.active = active;

    // Decode sequence number.
    result.sequence =
        (uint16_t)frame->data[5] |
        ((uint16_t)frame->data[6] << 8);

    *event = result;

    return true;
}
