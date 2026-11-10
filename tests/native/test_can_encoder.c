
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "smartharness_can.h"

int main(void)
{
    // Simulate ECU A reporting a disconnected headlight.
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

    // Encode the event.
    bool success = sh_can_encode_fault(&event, &frame);

    assert(success);
    assert(frame.identifier == SH_CAN_ECU_A_ID);
    assert(frame.length == 8);
    assert(frame.is_extended == false);

    // Expected payload from the SmartHarness protocol.
    const uint8_t expected[8] = {
        0x01, 0x01, 0x00, 0x00,
        0x03, 0x01, 0x00, 0x01
    };

    assert(memcmp(frame.data, expected, 8) == 0);

    printf("PASS: CAN encoder produces correct frame\n");
    printf("CAN ID: 0x%03X\n", (unsigned)frame.identifier);

    printf("Payload: ");
    for (int i = 0; i < 8; i++) {
        printf("%02X ", frame.data[i]);
    }
    printf("\n");

    return 0;
}
