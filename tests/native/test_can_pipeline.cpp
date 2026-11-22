#include <cassert>
#include <cstdio>
#include <cstring>

extern "C" {
#include "ecu_can_adapter.h"
}
#include "protocol.h"

struct TestFrame {
    char ecu;
    uint8_t circuit;
    sh_fault_transition_t transition;
    uint16_t voltage_mv;
    uint16_t sequence;
    uint32_t can_id;
    uint8_t payload[SH_CAN_PAYLOAD_SIZE];
};

int main() {
    const TestFrame cases[] = {
        {'A', 1, SH_EVENT_OPEN_DETECTED, 0, 1, 0x080, {1, 1, 0, 0, 3, 1, 0, 1}},
        {'A', 1, SH_EVENT_RECOVERED, 3300, 2, 0x080, {1, 0, 0xe4, 0x0c, 1, 2, 0, 1}},
        {'B', 4, SH_EVENT_OPEN_DETECTED, 0, 65535, 0x081, {4, 1, 0, 0, 3, 0xff, 0xff, 1}},
        {'B', 4, SH_EVENT_RECOVERED, 3300, 0, 0x081, {4, 0, 0xe4, 0x0c, 1, 0, 0, 1}},
    };

    for (const auto &test : cases) {
        uint16_t sequence = test.sequence;
        sh_ecu_event_t event{};
        sh_can_frame_t frame{};
        assert(sh_ecu_event_build(test.ecu, test.circuit, test.transition,
                                  test.voltage_mv, true, &sequence, &event));
        assert(sh_ecu_can_encode(&event, &frame));
        assert(frame.identifier == test.can_id && !frame.is_extended);
        assert(frame.length == sizeof(test.payload));
        assert(std::memcmp(frame.data, test.payload, sizeof(test.payload)) == 0);

        Fault diagnostic{};
        assert(decodeFault(frame.identifier, frame.data, frame.length,
                           frame.is_extended, false, false, diagnostic));
        char json[180];
        faultJson(diagnostic, json, sizeof(json));
        std::printf("%03X ", static_cast<unsigned>(frame.identifier));
        for (const auto byte : frame.data) {
            std::printf("%02X", static_cast<unsigned>(byte));
        }
        std::printf(" %s\n", json);
    }
}
