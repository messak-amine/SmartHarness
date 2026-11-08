
#ifndef SMARTHARNESS_CAN_H
#define SMARTHARNESS_CAN_H

#include <stdbool.h>
#include <stdint.h>

// SmartHarness CAN protocol constants
#define SH_CAN_ECU_A_ID 0x080
#define SH_CAN_ECU_B_ID 0x081
#define SH_CAN_PAYLOAD_SIZE 8
#define SH_CAN_PROTOCOL_VERSION 1

#ifdef __cplusplus
extern "C" {
#endif

// Diagnostic event produced by an ECU
typedef struct {
    char ecu;
    uint8_t circuit;
    uint8_t fault_code;
    uint16_t voltage_mv;
    bool command_on;
    bool active;
    uint16_t sequence;
} sh_fault_event_t;

// CAN frame representation
typedef struct {
    uint32_t identifier;
    uint8_t data[SH_CAN_PAYLOAD_SIZE];
    uint8_t length;
    bool is_extended;
} sh_can_frame_t;

// Convert diagnostic event to CAN frame
bool sh_can_encode_fault(
    const sh_fault_event_t *event,
    sh_can_frame_t *frame
);

// Convert CAN frame to diagnostic event
bool sh_can_decode_fault(
    const sh_can_frame_t *frame,
    sh_fault_event_t *event
);

#ifdef __cplusplus
}
#endif

#endif
