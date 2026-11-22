"""Check the host tool's ECU wire frames against the Python CAN implementation."""

import json
import subprocess
import sys

import can

from gateway.decoder import decode_fault
from simulator.can_protocol import encode_fault


def check_frames(executable: str) -> None:
    rows = subprocess.check_output([executable], text=True).splitlines()
    if not rows:
        raise RuntimeError("Native CAN test produced no frames")

    for row in rows:
        identifier, payload, gateway_json = row.split(maxsplit=2)
        can_id = int(identifier, 16)
        data = bytes.fromhex(payload)
        frame = can.Message(arbitration_id=can_id, data=data, is_extended_id=False)
        diagnostic = decode_fault(frame)
        assert diagnostic == json.loads(gateway_json), f"Gateway disagreement: {row}"

        simulated = encode_fault(diagnostic)
        assert not simulated.is_extended_id and simulated.arbitration_id == can_id, row
        assert bytes(simulated.data) == data, f"Simulator payload differs: {row}"

    print(f"CAN v1: {len(rows)} ECU frames match both gateway decoders and the simulator")


if __name__ == "__main__":
    check_frames(sys.argv[1])
