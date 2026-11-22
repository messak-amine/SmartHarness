

idf_component_register(
    SRCS "smartharness_twai.c"
    INCLUDE_DIRS "include"
    REQUIRES smartharness_can
    PRIV_REQUIRES esp_driver_twai freertos
)
