
#include <assert.h>
#include <stdio.h>
#include "smartharness_can.h"

int main(void)
{
    // ECU A reports a disconnected headlight.
    sh_fault_event_t original = {
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

    // Step 1: Encode the event.
    assert(sh_can_encode_fault(&original, &frame));

    // Step 2: Decode the frame.
    assert(sh_can_decode_fault(&frame, &decoded));

    // Step 3: Compare original and decoded data.
    assert(decoded.ecu == original.ecu);
    assert(decoded.circuit == original.circuit);
    assert(decoded.fault_code == original.fault_code);
    assert(decoded.voltage_mv == original.voltage_mv);
    assert(decoded.command_on == original.command_on);
    assert(decoded.active == original.active);
    assert(decoded.sequence == original.sequence);

    printf("PASS: CAN round-trip ECU A\n");

    // Step 4: Reject an invalid CAN protocol version.
    frame.data[7] = 99;
    assert(!sh_can_decode_fault(&frame, &decoded));

    printf("PASS: Invalid protocol version rejected\n");

    return 0;
}
