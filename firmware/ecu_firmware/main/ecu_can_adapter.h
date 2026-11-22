#ifndef SH_ECU_CAN_ADAPTER_H
#define SH_ECU_CAN_ADAPTER_H

#include <stdbool.h>
#include "ecu_events.h"
#include "smartharness_can.h"

/*
 * Translate ECU application events to the shared CAN v1 codec.
 * Intermittent (local code 2) is deliberately represented as
 * disconnection (wire code 1) until the shared protocol supports 2.
 * The original local event and its fault_code are NOT modified.
 */
bool sh_ecu_can_encode(const sh_ecu_event_t *source, sh_can_frame_t *frame);

#endif
