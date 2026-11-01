
#ifndef SMARTHARNESS_TWAI_H
#define SMARTHARNESS_TWAI_H

#include <stdint.h>
#include "esp_err.h"
#include "smartharness_can.h"

#ifdef __cplusplus
extern "C" {
#endif

#define SH_TWAI_BITRATE 250000

// Configuration for one ESP32 TWAI controller.
typedef struct {
    int tx_gpio;
    int rx_gpio;
    uint32_t bitrate;
} sh_twai_config_t;

// Initialize and start the TWAI controller.
esp_err_t sh_twai_start(
    const sh_twai_config_t *config
);

// Transmit a CAN frame.
esp_err_t sh_twai_send(
    const sh_can_frame_t *frame,
    int timeout_ms
);

// Receive a CAN frame.
esp_err_t sh_twai_receive(
    sh_can_frame_t *frame,
    int timeout_ms
);

// Stop and release the controller.
esp_err_t sh_twai_stop(void);

#ifdef __cplusplus
}
#endif

#endif
