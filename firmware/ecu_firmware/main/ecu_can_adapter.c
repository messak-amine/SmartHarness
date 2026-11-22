#include "ecu_can_adapter.h"
#include <stddef.h>

bool sh_ecu_can_encode(const sh_ecu_event_t *source, sh_can_frame_t *frame)
{
    if (source == NULL || frame == NULL) {
        return false;
    }
    if (source->fault_code > 2U) {
        return false;
    }
    if (source->fault_active != (source->fault_code != 0U)) {
        return false;
    }

    /* Code 2 is reserved by the current shared encoder and gateway.
       Keep local detection precise, preserve v1 wire compatibility. */
    const uint8_t wire_code = source->fault_code == 2U ? 1U : source->fault_code;

    const sh_fault_event_t can_event = {
        .ecu = source->ecu_role,
        .circuit = source->circuit_id,
        .fault_code = wire_code,
        .voltage_mv = source->voltage_mv,
        .command_on = source->command_on,
        .active = source->fault_active,
        .sequence = source->sequence
    };
    return sh_can_encode_fault(&can_event, frame);
}
