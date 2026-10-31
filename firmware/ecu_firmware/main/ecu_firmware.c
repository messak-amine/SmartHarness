#include <stdbool.h>
#include <stdint.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

typedef struct {
    uint8_t id;
    const char *name;
    bool command_on;
    uint16_t voltage_mv;
} circuit_t;

#if defined(CONFIG_SH_ECU_B)

static const char *TAG = "ECU_B";

static const circuit_t circuits[] = {
    {3, "Brake Lights", true, 3300},
    {4, "Ventilation", true, 3300}
};

#else

static const char *TAG = "ECU_A";

static const circuit_t circuits[] = {
    {1, "Headlights", true, 3300},
    {2, "Indicators", true, 3300}
};

#endif

void app_main(void)
{
    ESP_LOGI(TAG, "SmartHarness ECU firmware started");

    while (true) {
        for (int i = 0; i < 2; i++) {
            ESP_LOGI(TAG,
                     "Circuit %u | %s | Command: %s | Voltage: %u mV",
                     (unsigned)circuits[i].id,
                     circuits[i].name,
                     circuits[i].command_on ? "ON" : "OFF",
                     (unsigned)circuits[i].voltage_mv);
        }

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
