#include <stdio.h>
#include <stdint.h>
#include "sensor_sim.h"

static int test_sensor(const char *name,
                       sensor_input_t input,
                       uint16_t expected)
{
    uint16_t actual = sensor_sim_read_mv(input);

    if (actual == expected) {
        printf("[PASS] %s: %u mV\n", name, actual);
        return 0;
    }

    printf("[FAIL] %s: expected %u, got %u\n",
           name, expected, actual);
    return 1;
}

int main(void)
{
    int failures = 0;

    failures += test_sensor(
        "ON + Connected", (sensor_input_t){true, true}, 3300);

    failures += test_sensor(
        "ON + Disconnected", (sensor_input_t){true, false}, 0);

    failures += test_sensor(
        "OFF + Connected", (sensor_input_t){false, true}, 0);

    failures += test_sensor(
        "OFF + Disconnected", (sensor_input_t){false, false}, 0);

    sensor_input_t sensor = {true, false};
    sensor.connected = true;

    failures += test_sensor(
        "Recovery", sensor, 3300);

    printf("\nTests: %d/5 passed\n", 5 - failures);

    return failures == 0 ? 0 : 1;
}