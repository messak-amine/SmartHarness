#include <stdbool.h>
#include <stdint.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "sensor_sim.h"
#include "fault_detector.h"
#include "ecu_events.h"

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

/* Software-only fault-injection scenario on circuit 1 (A) or 3 (B):
   transient -> confirmed open -> recovery -> repeated open (intermittent)
   -> recovery. This is NOT hardware ADC acquisition. */
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
    ESP_LOGI(TAG, "SmartHarness ECU %c - software mock started", ECU_ROLE);
    for (unsigned i = 0; i < 2U; ++i) {
        sh_fault_detector_init(&circuits[i].detector);
    }

    uint32_t elapsed_ms = 0;
    uint16_t next_seq = 0;
    while (true) {
        apply_mock_inputs(elapsed_ms);
        for (unsigned i = 0; i < 2U; ++i) {
            sh_circuit_t *c = &circuits[i];
            const uint16_t voltage = sensor_sim_read_mv(c->sensor);
            const sh_fault_event_t event = sh_fault_detector_update(
                &c->detector, c->sensor.command_on, voltage, elapsed_ms);
            sh_ecu_event_t message;
            if (sh_ecu_event_build(ECU_ROLE, c->id, event, voltage,
                                    c->sensor.command_on, &next_seq, &message)) {
                ESP_LOGW(TAG,
                         "EVENT ecu=%c circuit=%u fault_code=%u active=%u voltage_mv=%u seq=%u",
                         message.ecu_role, (unsigned)message.circuit_id,
                         (unsigned)message.fault_code, (unsigned)message.fault_active,
                         (unsigned)message.voltage_mv, (unsigned)message.sequence);
                /* Membre 2 will forward this object to TWAI.
                   Gateway must explicitly support fault_code=2 before TX. */
            }
            if (elapsed_ms % 1000U == 0U) {
                ESP_LOGI(TAG, "circuit=%u %s voltage=%u mV state=%d",
                         (unsigned)c->id, c->name, (unsigned)voltage,
                         (int)c->detector.state);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(SH_POLL_INTERVAL_MS));
        elapsed_ms += SH_POLL_INTERVAL_MS;
    }
}
