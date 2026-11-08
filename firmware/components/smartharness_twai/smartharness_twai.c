
#include <stddef.h>
#include <string.h>

#include "smartharness_twai.h"
#include "esp_twai.h"
#include "esp_twai_onchip.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#define SH_TWAI_RX_QUEUE_SIZE 16

static twai_node_handle_t s_twai_node = NULL;
static QueueHandle_t s_rx_queue = NULL;

// Count frames lost when the RX queue is full.
static volatile uint32_t s_rx_dropped = 0;

// Persistent TX storage.
static twai_frame_t s_tx_message;
static uint8_t s_tx_data[SH_CAN_PAYLOAD_SIZE];
static bool s_tx_pending = false;

// --------------------------------------------------
// 1. TWAI Reception Callback
// --------------------------------------------------

static bool sh_twai_rx_callback(
    twai_node_handle_t handle,
    const twai_rx_done_event_data_t *edata,
    void *user_ctx)
{
    (void)edata;
    (void)user_ctx;

    uint8_t buffer[SH_CAN_PAYLOAD_SIZE] = {0};

    twai_frame_t rx = {
        .buffer = buffer,
        .buffer_len = sizeof(buffer)};

    if (twai_node_receive_from_isr(handle, &rx) != ESP_OK)
    {
        return false;
    }

    // Accept standard Classical CAN data frames only.
    if (rx.header.ide ||
        rx.header.rtr ||
        rx.header.fdf ||
        rx.header.dlc > SH_CAN_PAYLOAD_SIZE)
    {
        return false;
    }

    sh_can_frame_t frame = {0};

    frame.identifier = rx.header.id;
    frame.length = (uint8_t)rx.header.dlc;
    frame.is_extended = false;

    memcpy(frame.data, buffer, frame.length);

    BaseType_t task_woken = pdFALSE;

    if (s_rx_queue != NULL)
    {

        if (xQueueSendFromISR(
                s_rx_queue,
                &frame,
                &task_woken) != pdTRUE)
        {

            // The RX queue is full.
            s_rx_dropped++;
        }
    }

    return task_woken == pdTRUE;
}

// --------------------------------------------------
// 2. TWAI Initialization
// --------------------------------------------------

esp_err_t sh_twai_start(const sh_twai_config_t *config)
{
    if (config == NULL)
    {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_twai_node != NULL)
    {
        return ESP_ERR_INVALID_STATE;
    }

    if (config->tx_gpio < 0 ||
        config->rx_gpio < 0 ||
        config->tx_gpio == config->rx_gpio ||
        config->bitrate != SH_TWAI_BITRATE)
    {
        return ESP_ERR_INVALID_ARG;
    }

    s_rx_queue = xQueueCreate(
        SH_TWAI_RX_QUEUE_SIZE,
        sizeof(sh_can_frame_t));

    if (s_rx_queue == NULL)
    {
        return ESP_ERR_NO_MEM;
    }

    twai_onchip_node_config_t node_config = {
        .io_cfg.tx = (gpio_num_t)config->tx_gpio,
        .io_cfg.rx = (gpio_num_t)config->rx_gpio,
        .io_cfg.quanta_clk_out = GPIO_NUM_NC,
        .io_cfg.bus_off_indicator = GPIO_NUM_NC,
        .bit_timing.bitrate = config->bitrate,
        .tx_queue_depth = 5,
        .fail_retry_cnt = -1,
    };

    esp_err_t err = twai_new_node_onchip(
        &node_config,
        &s_twai_node);

    if (err != ESP_OK)
    {
        goto cleanup;
    }

    twai_event_callbacks_t callbacks = {
        .on_rx_done = sh_twai_rx_callback};

    err = twai_node_register_event_callbacks(
        s_twai_node,
        &callbacks,
        NULL);

    if (err != ESP_OK)
    {
        goto cleanup;
    }

    s_tx_pending = false;
    s_rx_dropped = 0;

    err = twai_node_enable(s_twai_node);

    if (err != ESP_OK)
    {
        goto cleanup;
    }

    return ESP_OK;

cleanup:
    if (s_twai_node != NULL)
    {
        twai_node_delete(s_twai_node);
        s_twai_node = NULL;
    }

    vQueueDelete(s_rx_queue);
    s_rx_queue = NULL;

    return err;
}

// --------------------------------------------------
// 3. CAN Frame Transmission
// --------------------------------------------------

esp_err_t sh_twai_send(
    const sh_can_frame_t *frame,
    int timeout_ms)
{
    if (s_twai_node == NULL)
    {
        return ESP_ERR_INVALID_STATE;
    }

    if (frame == NULL || timeout_ms < -1)
    {
        return ESP_ERR_INVALID_ARG;
    }

    sh_fault_event_t decoded;

    if (!sh_can_decode_fault(frame, &decoded))
    {
        return ESP_ERR_INVALID_ARG;
    }

    // Wait for a previous pending transmission.
    if (s_tx_pending)
    {
        esp_err_t err = twai_node_transmit_wait_all_done(
            s_twai_node,
            timeout_ms);

        if (err != ESP_OK)
        {
            return err;
        }

        s_tx_pending = false;
    }

    memcpy(
        s_tx_data,
        frame->data,
        SH_CAN_PAYLOAD_SIZE);

    s_tx_message = (twai_frame_t){0};

    s_tx_message.header.id = frame->identifier;
    s_tx_message.header.ide = false;
    s_tx_message.header.dlc = SH_CAN_PAYLOAD_SIZE;

    s_tx_message.buffer = s_tx_data;
    s_tx_message.buffer_len = SH_CAN_PAYLOAD_SIZE;

    esp_err_t err = twai_node_transmit(
        s_twai_node,
        &s_tx_message,
        timeout_ms);

    if (err != ESP_OK)
    {
        return err;
    }

    s_tx_pending = true;

    // Wait for transmission completion.
    err = twai_node_transmit_wait_all_done(
        s_twai_node,
        timeout_ms);

    if (err == ESP_OK)
    {
        s_tx_pending = false;
    }

    return err;
}

// --------------------------------------------------
// 4. CAN Frame Reception
// --------------------------------------------------

esp_err_t sh_twai_receive(
    sh_can_frame_t *frame,
    int timeout_ms)
{
    if (frame == NULL || timeout_ms < -1)
    {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_twai_node == NULL || s_rx_queue == NULL)
    {
        return ESP_ERR_INVALID_STATE;
    }

    TickType_t ticks = timeout_ms == -1
                           ? portMAX_DELAY
                           : pdMS_TO_TICKS(timeout_ms);

    if (xQueueReceive(s_rx_queue, frame, ticks) == pdTRUE)
    {
        return ESP_OK;
    }

    return ESP_ERR_TIMEOUT;
}

// --------------------------------------------------
// 5. RX Dropped Frame Counter
// --------------------------------------------------

uint32_t sh_twai_rx_dropped_count(void)
{
    return s_rx_dropped;
}

// --------------------------------------------------
// 6. Stop TWAI Controller
// --------------------------------------------------

esp_err_t sh_twai_stop(void)
{
    if (s_twai_node == NULL)
    {
        return ESP_ERR_INVALID_STATE;
    }

    // Wait before releasing TX storage.
    if (s_tx_pending)
    {
        esp_err_t err = twai_node_transmit_wait_all_done(
            s_twai_node,
            1000);

        if (err != ESP_OK)
        {
            return err;
        }

        s_tx_pending = false;
    }

    esp_err_t err = twai_node_disable(s_twai_node);

    if (err != ESP_OK)
    {
        return err;
    }

    err = twai_node_delete(s_twai_node);

    if (err != ESP_OK)
    {
        return err;
    }

    s_twai_node = NULL;

    vQueueDelete(s_rx_queue);
    s_rx_queue = NULL;

    s_tx_pending = false;

    return ESP_OK;
}
