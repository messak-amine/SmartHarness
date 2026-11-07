#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p "${TMPDIR:-/tmp}/sh_m1_tests"
for mod in sensor_sim fault_detector ecu_events; do
    gcc -std=c11 -Wall -Wextra -Werror -I main "tests/test_${mod}.c" "main/${mod}.c" -o "${TMPDIR:-/tmp}/sh_m1_tests/test_${mod}"
    "${TMPDIR:-/tmp}/sh_m1_tests/test_${mod}"
done

CAN_ROOT="../components/smartharness_can"
gcc -std=c11 -Wall -Wextra -Werror -I main -I "$CAN_ROOT/include" \
  tests/test_ecu_can_adapter.c main/sensor_sim.c main/fault_detector.c \
  main/ecu_events.c main/ecu_can_adapter.c "$CAN_ROOT/smartharness_can.c" \
  -o "${TMPDIR:-/tmp}/sh_m1_tests/test_ecu_can_adapter"
"${TMPDIR:-/tmp}/sh_m1_tests/test_ecu_can_adapter"
echo "All ECU and ECU/CAN integration tests passed."
