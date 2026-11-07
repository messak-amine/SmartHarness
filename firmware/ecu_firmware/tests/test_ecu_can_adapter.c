#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "sensor_sim.h"
#include "fault_detector.h"
#include "ecu_events.h"
#include "ecu_can_adapter.h"
#include "smartharness_can.h"

static int total = 0;
static int failures = 0;
#define CHECK(label, cond) do { \
    ++total; \
    if (cond) printf("[PASS] %s\n", label); \
    else { ++failures; printf("[FAIL] %s\n", label); } \
} while (0)

static bool test_chain(char role, uint8_t circuit, uint32_t can_id)
{
    sh_fault_detector_t detector;
    sh_fault_detector_init(&detector);
    uint16_t next_seq = 7;
    sensor_input_t input = {.command_on = true, .connected = false};
    const uint16_t mv = sensor_sim_read_mv(input);

    sh_fault_transition_t transition = SH_EVENT_NONE;
    for (unsigned i = 0; i < 3U; ++i) {
        transition = sh_fault_detector_update(&detector, true, mv, i * 100U);
    }
    sh_ecu_event_t local = {0};
    sh_can_frame_t frame = {0};
    sh_fault_event_t decoded = {0};
    if (transition != SH_EVENT_OPEN_DETECTED ||
        !sh_ecu_event_build(role, circuit, transition, mv, true, &next_seq, &local) ||
        !sh_ecu_can_encode(&local, &frame) ||
        !sh_can_decode_fault(&frame, &decoded)) {
        return false;
    }
    return frame.identifier == can_id && frame.length == 8U &&
        frame.data[0] == circuit && frame.data[1] == 1U &&
        frame.data[2] == 0U && frame.data[3] == 0U &&
        frame.data[4] == 3U && frame.data[5] == 7U &&
        frame.data[6] == 0U && frame.data[7] == 1U &&
        !frame.is_extended && decoded.ecu == role &&
        decoded.circuit == circuit && decoded.fault_code == 1U &&
        decoded.active && decoded.command_on && decoded.sequence == 7U &&
        next_seq == 8U;
}

int main(void)
{
    CHECK("ECU A circuit 1: detection -> encoding -> decoding", test_chain('A', 1, 0x080U));
    CHECK("ECU A circuit 2: detection -> encoding -> decoding", test_chain('A', 2, 0x080U));
    CHECK("ECU B circuit 3: detection -> encoding -> decoding", test_chain('B', 3, 0x081U));
    CHECK("ECU B circuit 4: detection -> encoding -> decoding", test_chain('B', 4, 0x081U));

    uint16_t seq = 65535U;
    sh_ecu_event_t local = {0};
    sh_can_frame_t frame = {0};
    sh_fault_event_t decoded = {0};

    CHECK("recovery event generated", sh_ecu_event_build('A', 1, SH_EVENT_RECOVERED,
                                3300, true, &seq, &local));
    CHECK("recovery sequence wraps", local.sequence == 65535U && seq == 0U);
    CHECK("recovery encoded", sh_ecu_can_encode(&local, &frame));
    CHECK("recovery decoded", sh_can_decode_fault(&frame, &decoded));
    CHECK("recovery semantics preserved", decoded.fault_code == 0U && !decoded.active &&
                        decoded.voltage_mv == 3300U && decoded.sequence == 65535U);
    CHECK("recovery voltage LE", frame.data[2] == 0xE4U && frame.data[3] == 0x0CU);

    CHECK("intermittent local event created", sh_ecu_event_build('B', 3,
                    SH_EVENT_INTERMITTENT_DETECTED, 0, true, &seq, &local));
    CHECK("local code 2 remains intact", local.fault_code == 2U);
    CHECK("intermittent mapped for CAN v1", sh_ecu_can_encode(&local, &frame));
    CHECK("wire code 1, local code still 2", frame.data[1] == 1U && local.fault_code == 2U);
    CHECK("mapped frame accepted by shared decoder", sh_can_decode_fault(&frame, &decoded) &&
                            decoded.fault_code == 1U && decoded.active && decoded.ecu == 'B');

    local.fault_code = 3;
    CHECK("unsupported local fault rejected", !sh_ecu_can_encode(&local, &frame));
    local.fault_code = 2;
    local.fault_active = false;
    CHECK("inconsistent active flag rejected", !sh_ecu_can_encode(&local, &frame));
    local.fault_active = true;
    local.ecu_role = 'A';
    CHECK("wrong ECU/circuit rejected", !sh_ecu_can_encode(&local, &frame));
    CHECK("null source rejected", !sh_ecu_can_encode(NULL, &frame));
    CHECK("null destination rejected", !sh_ecu_can_encode(&local, NULL));

    printf("\nTests: %d/%d passed\n", total - failures, total);
    return failures == 0 ? 0 : 1;
}
