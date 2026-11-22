#include "protocol.h"
#include <assert.h>
#include <string.h>
int main() {
    Fault f;
    uint8_t fault[] = {1,1,0,0,3,1,0,1};
    assert(decodeFault(0x80, fault, 8, false, false, false, f));
    char json[180]; faultJson(f, json, sizeof(json));
    assert(strcmp(json, "{\"ecu\":\"A\",\"circuit\":1,\"fault_code\":1,\"active\":true,\"voltage_mv\":0,\"command_on\":true,\"seq\":1}") == 0);
    uint8_t recovery[] = {4,0,0xe4,0x0c,1,0xff,0xff,1};
    assert(decodeFault(0x81, recovery, 8, false, false, false, f));
    assert(f.voltage == 3300 && f.seq == 65535 && !f.active && f.ecu == 'B');
    assert(!decodeFault(0x80, recovery, 8, false, false, false, f));
    assert(!decodeFault(0x81, recovery, 7, false, false, false, f));
    assert(!decodeFault(0x81, recovery, 8, true, false, false, f));
    assert(!decodeFault(0x81, recovery, 8, false, true, false, f));
    assert(!decodeFault(0x81, recovery, 8, false, false, true, f));
    for (unsigned flags=0; flags<256; ++flags) {
        fault[4] = flags;
        assert(decodeFault(0x80, fault, 8, false, false, false, f) == (flags == 2 || flags == 3));
    }
    fault[4] = 3; fault[7] = 2;
    assert(!decodeFault(0x80, fault, 8, false, false, false, f));
}
