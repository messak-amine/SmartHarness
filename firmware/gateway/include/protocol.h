#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
struct Fault { char ecu; uint8_t circuit, code; uint16_t voltage, seq; bool on, active; };
inline bool decodeFault(uint32_t id, const uint8_t* d, size_t length, bool extended,
                        bool remote, bool error, Fault& f) {
    if (extended || remote || error || length != 8 || (id != 0x80 && id != 0x81)) return false;
    if (d[7] != 1 || d[1] > 2 || (d[4] & 0xfc)) return false;
    if (d[0] < (id == 0x80 ? 1 : 3) || d[0] > (id == 0x80 ? 2 : 4)) return false;
    if (bool(d[4] & 2) != (d[1] != 0)) return false;
    f = {char(id == 0x80 ? 'A' : 'B'), d[0], d[1],
         uint16_t(d[2] | d[3] << 8), uint16_t(d[5] | d[6] << 8),
         bool(d[4] & 1), bool(d[4] & 2)};
    return true;
}
inline void faultJson(const Fault& f, char* output, size_t size) {
    snprintf(output, size, "{\"ecu\":\"%c\",\"circuit\":%u,\"fault_code\":%u,\"active\":%s,\"voltage_mv\":%u,\"command_on\":%s,\"seq\":%u}",
             f.ecu, f.circuit, f.code, f.active ? "true" : "false", f.voltage,
             f.on ? "true" : "false", f.seq);
}
