#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

build_dir=$(mktemp -d)
trap 'rm -rf -- "$build_dir"' EXIT
can_root=firmware/components/smartharness_can
ecu_main=firmware/ecu_firmware/main
gateway_include=firmware/gateway/include

for source in "$can_root/smartharness_can.c" "$ecu_main/ecu_events.c" "$ecu_main/ecu_can_adapter.c"; do
    name=${source##*/}
    gcc -std=c11 -Wall -Wextra -Werror -I"$can_root/include" -I"$ecu_main" \
        -c "$source" -o "$build_dir/${name%.c}.o"
done

g++ -std=c++11 -Wall -Wextra -Werror \
    -I"$can_root/include" -I"$ecu_main" -I"$gateway_include" \
    tests/native/test_can_pipeline.cpp "$build_dir"/*.o -o "$build_dir/can_pipeline"
python -m tests.can_pipeline "$build_dir/can_pipeline"
