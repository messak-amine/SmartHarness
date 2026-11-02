#ifndef SH_FAULT_DETECTOR_H
#define SH_FAULT_DETECTOR_H
#include <stdbool.h>
#include <stdint.h>

/* Provisional thresholds for the 3.3 V software mock; recalibrate on hardware. */
#define SH_FAULT_MIN_OK_MV        2500U
#define SH_CONFIRM_SAMPLES       3U
#define SH_INTERMITTENT_WINDOW_MS 30000UL

typedef enum {
    SH_FAULT_NORMAL = 0,
    SH_FAULT_OPEN,
    SH_FAULT_INTERMITTENT
} sh_fault_state_t;

typedef enum {
    SH_EVENT_NONE = 0,
    SH_EVENT_OPEN_DETECTED,
    SH_EVENT_INTERMITTENT_DETECTED,
    SH_EVENT_RECOVERED
} sh_fault_event_t;

typedef struct {
    sh_fault_state_t state;
    uint8_t bad_count;
    uint8_t good_count;
    bool has_previous_fault;
    uint32_t previous_fault_ms;
} sh_fault_detector_t;

void sh_fault_detector_init(sh_fault_detector_t *d);
sh_fault_event_t sh_fault_detector_update(sh_fault_detector_t *d,
                                           bool command_on,
                                           uint16_t voltage_mv,
                                           uint32_t timestamp_ms);
#endif
