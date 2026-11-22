idf_component_register(
    SRCS
        "ecu_firmware.c"
        "sensor_sim.c"
        "fault_detector.c"
        "ecu_events.c"
        "ecu_can_adapter.c"
    INCLUDE_DIRS "."
    REQUIRES smartharness_can
    PRIV_REQUIRES esp_timer freertos log
)
