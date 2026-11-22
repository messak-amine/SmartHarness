#ifndef SENSOR_SIM_H
#define SENSOR_SIM_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool command_on;
    bool connected;
} sensor_input_t;

uint16_t sensor_sim_read_mv(sensor_input_t input);

#endif