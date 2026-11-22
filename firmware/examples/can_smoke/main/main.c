
#include <stdio.h>
#include "smartharness_can.h"

void app_main(void)
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

    if (sh_can_encode_fault(&event, &frame)) {
        printf("SmartHarness CAN encoder ready\n");
        printf("CAN ID: 0x%03lX\n",
               (unsigned long)frame.identifier);
    } else {
        printf("CAN encoding failed\n");
    }
}
