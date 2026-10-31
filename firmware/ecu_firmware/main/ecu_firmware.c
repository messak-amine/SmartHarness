#include <stdbool.h>
#include <stdint.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "sensor_sim.h"

typedef struct {
    uint8_t id;
    const char *name;
    sensor_input_t sensor;
} circuit_t;

#if defined(CONFIG_SH_ECU_B)

static const char *TAG = "ECU_B";

static circuit_t circuits[] = {
    {3, "Brake Lights", {true, true}},
    {4, "Ventilation", {true, true}}
};

#else

static const char *TAG = "ECU_A";

static circuit_t circuits[] = {
    {1, "Headlights", {true, true}},
    {2, "Indicators", {true, true}}
};

#endif

void app_main(void)
{
    ESP_LOGI(TAG, "SmartHarness ECU firmware started");

    while (true) {
        for (int i = 0; i < 2; i++) {
            uint16_t voltage_mv =
                sensor_sim_read_mv(circuits[i].sensor);

            ESP_LOGI(TAG,
                     "Circuit %u | %s | Command: %s | Voltage: %u mV",
                     (unsigned)circuits[i].id,
                     circuits[i].name,
                     circuits[i].sensor.command_on ? "ON" : "OFF",
                     (unsigned)voltage_mv);
        }

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}