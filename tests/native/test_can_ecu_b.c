
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "smartharness_can.h"

int main(void)
{
    // ECU B: Ventilation circuit recovered.
    sh_fault_event_t original = {
        .ecu = 'B',
        .circuit = 4,
        .fault_code = 0,
        .voltage_mv = 3300,
        .command_on = true,
        .active = false,
        .sequence = 258
    };

    sh_can_frame_t frame = {0};
    sh_fault_event_t decoded = {0};

    // Encode diagnostic event.
    assert(sh_can_encode_fault(&original, &frame));

    assert(frame.identifier == SH_CAN_ECU_B_ID);
    assert(frame.length == 8);

    // Verify exact CAN payload.
    const uint8_t expected[8] = {
        0x04, 0x00, 0xE4, 0x0C,
        0x01, 0x02, 0x01, 0x01
    };

    assert(memcmp(frame.data, expected, 8) == 0);

    printf("PASS: ECU B CAN encoding\n");

    // Decode and compare.
    assert(sh_can_decode_fault(&frame, &decoded));

    assert(decoded.ecu == original.ecu);
    assert(decoded.circuit == original.circuit);
    assert(decoded.fault_code == original.fault_code);
    assert(decoded.voltage_mv == original.voltage_mv);
    assert(decoded.command_on == original.command_on);
    assert(decoded.active == original.active);
    assert(decoded.sequence == original.sequence);

    printf("PASS: ECU B recovery round-trip\n");

    // ECU A must not report ECU B's circuit.
    original.ecu = 'A';
    assert(!sh_can_encode_fault(&original, &frame));

    printf("PASS: Invalid ECU/circuit assignment rejected\n");

    return 0;
}
