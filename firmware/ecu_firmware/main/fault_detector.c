#include "fault_detector.h"

void sh_fault_detector_init(sh_fault_detector_t *d)
{
    if (d == 0) return;
    *d = (sh_fault_detector_t){0};
    d->state = SH_FAULT_NORMAL;
}

sh_fault_transition_t sh_fault_detector_update(sh_fault_detector_t *d,
                                           bool command_on,
                                           uint16_t voltage_mv,
                                           uint32_t timestamp_ms)
{
    if (d == 0) return SH_EVENT_NONE;

    /* An OFF circuit is not faulty just because its measured voltage is 0. */
    if (!command_on) {
        d->bad_count = 0;
        d->good_count = 0;
        return SH_EVENT_NONE;
    }

    const bool ok = voltage_mv >= SH_FAULT_MIN_OK_MV;
    if (d->state == SH_FAULT_NORMAL) {
        if (ok) {
            d->bad_count = 0;
            return SH_EVENT_NONE;
        }
        if (++d->bad_count < SH_CONFIRM_SAMPLES) return SH_EVENT_NONE;

        d->bad_count = 0;
        const bool repeated = d->has_previous_fault &&
            (uint32_t)(timestamp_ms - d->previous_fault_ms) <= SH_INTERMITTENT_WINDOW_MS;
        d->has_previous_fault = true;
        d->previous_fault_ms = timestamp_ms;
        d->state = repeated ? SH_FAULT_INTERMITTENT : SH_FAULT_OPEN;
        return repeated ? SH_EVENT_INTERMITTENT_DETECTED : SH_EVENT_OPEN_DETECTED;
    }

    /* Confirm a recovery only after 3 consecutive good samples. */
    if (!ok) {
        d->good_count = 0;
        return SH_EVENT_NONE;
    }
    if (++d->good_count < SH_CONFIRM_SAMPLES) return SH_EVENT_NONE;
    d->good_count = 0;
    d->state = SH_FAULT_NORMAL;
    return SH_EVENT_RECOVERED;
}
