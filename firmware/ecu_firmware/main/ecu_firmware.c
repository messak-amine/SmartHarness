#include <stdbool.h>
#include <stdint.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "sensor_sim.h"
#include "fault_detector.h"
#include "ecu_events.h"
#include "ecu_can_adapter.h"

#define SH_POLL_INTERVAL_MS 100U
#define SH_DEMO_CYCLE_MS    12000U

typedef struct {
    uint8_t id;
    const char *name;
    sensor_input_t sensor;
    sh_fault_detector_t detector;
} sh_circuit_t;

#if defined(CONFIG_SH_ECU_B)
static const char *TAG = "ECU_B";
static const char ECU_ROLE = 'B';
static sh_circuit_t circuits[2] = {
    {.id = 3, .name = "Brake Lights", .sensor = {true, true}},
    {.id = 4, .name = "Ventilation",  .sensor = {true, true}}
};
#else
static const char *TAG = "ECU_A";
static const char ECU_ROLE = 'A';
static sh_circuit_t circuits[2] = {
    {.id = 1, .name = "Headlights", .sensor = {true, true}},
    {.id = 2, .name = "Indicators", .sensor = {true, true}}
};
#endif

/* Deterministic SOFTWARE fault injection, NOT ADC/GPIO hardware acquisition. */
static void apply_mock_inputs(uint32_t elapsed_ms)
{
    const uint32_t phase = elapsed_ms % SH_DEMO_CYCLE_MS;
    const bool transient = phase >= 2000U && phase < 2100U;
    const bool open_1 = phase >= 4000U && phase < 5000U;
    const bool open_2 = phase >= 6500U && phase < 7500U;
    circuits[0].sensor.connected = !(transient || open_1 || open_2);
    circuits[1].sensor.connected = true;
}

void app_main(void)
{
    ESP_LOGI(TAG, "ECU %c - simulated inputs, CAN v1 software encoding; physical TX disabled", ECU_ROLE);

    for (unsigned i = 0; i < 2U; ++i) {
        sh_fault_detector_init(&circuits[i].detector);
    }

    const uint32_t start_ms = (uint32_t)(esp_timer_get_time() / 1000);
    uint32_t last_report_s = UINT32_MAX;
    uint16_t next_seq = 0;

    while (true) {
        const uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);
        const uint32_t elapsed_ms = now_ms - start_ms;
        apply_mock_inputs(elapsed_ms);

        for (unsigned i = 0; i < 2U; ++i) {
            sh_circuit_t *c = &circuits[i];
            const uint16_t voltage = sensor_sim_read_mv(c->sensor);
            const sh_fault_transition_t transition = sh_fault_detector_update(
                &c->detector, c->sensor.command_on, voltage, now_ms);

            sh_ecu_event_t event;
            if (sh_ecu_event_build(ECU_ROLE, c->id, transition, voltage,
                                   c->sensor.command_on, &next_seq, &event)) {
                sh_can_frame_t frame;
                if (sh_ecu_can_encode(&event, &frame)) {
                    ESP_LOGW(TAG,
                        "CAN_READY id=0x%03lX circuit=%u local_code=%u wire_code=%u "
                        "voltage_mv=%u seq=%u (NOT TRANSMITTED)",
                        (unsigned long)frame.identifier,
                        (unsigned)event.circuit_id,
                        (unsigned)event.fault_code,
                        (unsigned)frame.data[1],
                        (unsigned)event.voltage_mv,
                        (unsigned)event.sequence);
                } else {
                    ESP_LOGE(TAG, "CAN v1 encode failed for circuit=%u", (unsigned)c->id);
                }
            }
        }

        const uint32_t report_s = elapsed_ms / 1000U;
        if (report_s != last_report_s) {
            last_report_s = report_s;
            for (unsigned i = 0; i < 2U; ++i) {
                const sh_circuit_t *c = &circuits[i];
                ESP_LOGI(TAG, "circuit=%u %s state=%d voltage=%u mV",
                         (unsigned)c->id, c->name, (int)c->detector.state,
                         (unsigned)sensor_sim_read_mv(c->sensor));
            }
        }

        vTaskDelay(pdMS_TO_TICKS(SH_POLL_INTERVAL_MS));
    }
}
