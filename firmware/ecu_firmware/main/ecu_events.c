#include "ecu_events.h"

bool sh_ecu_event_build(char ecu_role, uint8_t circuit_id,
                         sh_fault_transition_t type, uint16_t voltage_mv,
                         bool command_on, uint16_t *next_sequence,
                         sh_ecu_event_t *out)
{
    if (!out || !next_sequence) return false;
    if (!((ecu_role == 'A' && (circuit_id == 1 || circuit_id == 2)) ||
          (ecu_role == 'B' && (circuit_id == 3 || circuit_id == 4)))) return false;
    if (type == SH_EVENT_NONE) return false;

    uint8_t code;
    switch (type) {
        case SH_EVENT_RECOVERED: code = 0; break;
        case SH_EVENT_OPEN_DETECTED: code = 1; break;
        case SH_EVENT_INTERMITTENT_DETECTED: code = 2; break;
        default: return false;
    }

    *out = (sh_ecu_event_t){
        .ecu_role = ecu_role,
        .circuit_id = circuit_id,
        .fault_code = code,
        .voltage_mv = voltage_mv,
        .command_on = command_on,
        .fault_active = code != 0,
        .sequence = *next_sequence
    };
    *next_sequence = (uint16_t)(*next_sequence + 1U);
    return true;
}
