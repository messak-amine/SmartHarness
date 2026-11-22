
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "smartharness_can.h"

int main(void)
{
    sh_fault_event_t event = {
        .ecu = 'A',
        .circuit = 1,
        .fault_code = 1,
        .voltage_mv = 0,
        .command_on = true,
        .active = true,
        .sequence = 1
    };

    sh_can_frame_t frame = {0};
    sh_fault_event_t decoded = {0};

    // Test 1: Reject invalid pointers.
    assert(!sh_can_encode_fault(NULL, &frame));
    assert(!sh_can_encode_fault(&event, NULL));
    assert(!sh_can_decode_fault(NULL, &decoded));
    assert(!sh_can_decode_fault(&frame, NULL));

    printf("PASS: Invalid pointers rejected\n");

    // Test 2: Reject invalid events.
    event.ecu = 'X';
    assert(!sh_can_encode_fault(&event, &frame));
    event.ecu = 'A';

    event.fault_code = 2;
    assert(!sh_can_encode_fault(&event, &frame));
    event.fault_code = 1;

    event.active = false;
    assert(!sh_can_encode_fault(&event, &frame));
    event.active = true;

    printf("PASS: Invalid diagnostic events rejected\n");

    // Create a valid reference frame.
    assert(sh_can_encode_fault(&event, &frame));

    // Test 3: Reject unknown CAN identifier.
    frame.identifier = 0x777;
    assert(!sh_can_decode_fault(&frame, &decoded));
    frame.identifier = SH_CAN_ECU_A_ID;

    // Reject circuit 4 reported by ECU A.
    frame.data[0] = 4;
    assert(!sh_can_decode_fault(&frame, &decoded));
    frame.data[0] = 1;

    // Reject invalid payload length.
    frame.length = 7;
    assert(!sh_can_decode_fault(&frame, &decoded));
    frame.length = 8;

    // Reject extended CAN frame.
    frame.is_extended = true;
    assert(!sh_can_decode_fault(&frame, &decoded));
    frame.is_extended = false;

    // Reject reserved status flag.
    frame.data[4] = 0x07;
    assert(!sh_can_decode_fault(&frame, &decoded));
    frame.data[4] = 0x03;

    // Reject contradictory fault state.
    frame.data[4] = 0x01;
    assert(!sh_can_decode_fault(&frame, &decoded));
    frame.data[4] = 0x03;

    printf("PASS: Invalid CAN frames rejected\n");

    // Test 4: Maximum 16-bit values.
    event.voltage_mv = UINT16_MAX;
    event.sequence = UINT16_MAX;

    assert(sh_can_encode_fault(&event, &frame));
    assert(sh_can_decode_fault(&frame, &decoded));

    assert(decoded.voltage_mv == UINT16_MAX);
    assert(decoded.sequence == UINT16_MAX);

    printf("PASS: Maximum 16-bit values preserved\n");

    return 0;
}
