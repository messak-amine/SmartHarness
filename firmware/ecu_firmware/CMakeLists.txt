cmake_minimum_required(VERSION 3.16)

# Reuse the shared CAN codec owned by the embedded-interfaces workstream.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ecu_firmware)
