#ifndef SH_ECU_EVENTS_H
#define SH_ECU_EVENTS_H
#include <stdbool.h>
#include <stdint.h>
#include "fault_detector.h"

/* The Membre 2 transport layer owns TWAI framing and CAN TX. This is its input. */
typedef struct {
    char ecu_role;           /* 'A' or 'B' */
    uint8_t circuit_id;     /* ECU A: 1,2; ECU B: 3,4 */
    uint8_t fault_code;     /* 0 recovery, 1 open, 2 intermittent (reserved by gateway) */
    uint16_t voltage_mv;
    bool command_on;
    bool fault_active;
    uint16_t sequence;      /* per ECU, wraps at 65535 -> 0 */
} sh_ecu_event_t;

/* false means no event or invalid role/circuit. Increments sequence once on success. */
bool sh_ecu_event_build(char ecu_role, uint8_t circuit_id,
                         sh_fault_event_t type, uint16_t voltage_mv,
                         bool command_on, uint16_t *next_sequence,
                         sh_ecu_event_t *out);
#endif
