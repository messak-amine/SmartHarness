#include "sensor_sim.h"

#define SENSOR_NOMINAL_VOLTAGE_MV 3300U

uint16_t sensor_sim_read_mv(sensor_input_t input)
{
    if (!input.command_on || !input.connected) {
        return 0U;
    }

    return SENSOR_NOMINAL_VOLTAGE_MV;
}