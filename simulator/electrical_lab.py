"""SmartHarness electrical engineering *experiment* (not a physical measurement).

No changes to Circuit/ECU or shared CAN/MQTT contracts. This optional bench uses
simplified, explicitly synthetic low-voltage resistive loads and a local-only
classifier for fault types not supported by the project's CAN protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Dict, List


CIRCUITS = {
    1: ("Headlights", "A", 8.0),
    2: ("Indicators", "A", 12.0),
    3: ("Brake lights", "B", 10.0),
    4: ("Ventilator", "B", 9.0),
}
MODES = ("NORMAL", "OPEN", "SHORT", "OVERLOAD", "UNDERVOLTAGE", "INTERMITTENT")
LABELS = {
    "NORMAL": "Normal", "OPEN": "Circuit ouvert", "SHORT": "Court-circuit",
    "OVERLOAD": "Surcharge", "UNDERVOLTAGE": "Sous-tension",
    "INTERMITTENT": "Faux contact", "TRIPPED": "Protection déclenchée", "OFF": "Commande OFF",
}


@dataclass(frozen=True)
class Reading:
    tick: int
    seconds: float
    circuit: int
    ecu: str
    command_on: bool
    requested_mode: str
    actual_mode: str
    voltage_mv: int
    current_ma: int
    power_mw: int
    diagnostic: str
    protection_tripped: bool


@dataclass(frozen=True)
class LabEvent:
    tick: int
    seconds: float
    ecu: str
    circuit: int
    kind: str
    previous: str
    current: str
    seq: int


class Channel:
    """One simulated load, its protection latch, and a debounced diagnosis."""
    def __init__(self, cid: int):
        if cid not in CIRCUITS:
            raise ValueError("Unknown circuit")
        self.id = cid
        self.name, self.ecu, self.resistance_ohms = CIRCUITS[cid]
        self.command_on = True
        self.mode = "NORMAL"
        self.fuse_tripped = False
        self.short_streak = 0
        self.stable = "NORMAL"
        self.candidate = "NORMAL"
        self.candidate_count = 0

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unsupported experimental mode: {mode}")
        self.mode = mode

    def reset_protection(self) -> None:
        # A short is still present until the operator removes the fault.
        if self.mode == "SHORT":
            raise ValueError("Remove short-circuit before resetting protection")
        self.fuse_tripped = False
        self.short_streak = 0


class ElectricalLab:
    """Deterministic model: 3.3 V supply, 0.25 ohm source resistance.

    Units are mV/mA/mW. Simplified instrument readings reflect the *load-side*
    power availability; an open load is represented by 0 mV/0 mA on that side.
    Model thresholds and fuse action are didactic assumptions, not requirements
    of an actual automotive ECU or the shared SmartHarness CAN contract.
    """
    SUPPLY_V = 3.3
    SOURCE_R = 0.25
    DEBOUNCE_SAMPLES = 2
    FUSE_CURRENT_MA = 2500
    FUSE_TICKS = 3
    LOW_VOLTAGE_MV = 2700
    OVERCURRENT_MA = 750
    SHORT_CURRENT_MA = 2000
    OPEN_CURRENT_MA = 50

    def __init__(self, *, noise_mv: int = 0, seed: int = 21):
        if noise_mv < 0 or noise_mv > 300:
            raise ValueError("noise_mv must be between 0 and 300")
        self.channels = {cid: Channel(cid) for cid in CIRCUITS}
        self.tick = 0
        self.noise_mv = noise_mv
        self.random = Random(seed)
        self.sequences = {"A": 0, "B": 0}
        self.readings: Dict[int, Reading] = {}
        self.history: Dict[int, List[Reading]] = {cid: [] for cid in CIRCUITS}
        self.events: List[LabEvent] = []

    def set_mode(self, cid: int, mode: str) -> None:
        self.channels[cid].set_mode(mode)

    def set_command(self, cid: int, on: bool) -> None:
        self.channels[cid].command_on = bool(on)

    def reset_fuse(self, cid: int) -> None:
        self.channels[cid].reset_protection()

    def _classify(self, v_mv: int, i_ma: int, *, tripped: bool) -> str:
        if tripped:
            return "TRIPPED"
        if i_ma >= self.SHORT_CURRENT_MA:
            return "SHORT"
        if i_ma >= self.OVERCURRENT_MA:
            return "OVERLOAD"
        if i_ma <= self.OPEN_CURRENT_MA:
            return "OPEN"
        if v_mv < self.LOW_VOLTAGE_MV:
            return "UNDERVOLTAGE"
        return "NORMAL"

    def _sample_channel(self, ch: Channel) -> Reading:
        effective = ch.mode
        if not ch.command_on:
            effective = "OFF"
        elif effective == "INTERMITTENT":
            # Contact alternates every 4 scans; reproducible without randomness.
            effective = "OPEN" if ((self.tick - 1) // 4) % 2 else "NORMAL"

        if not ch.command_on or ch.fuse_tripped:
            v, i = 0.0, 0.0
        elif effective == "OPEN":
            v, i = 0.0, 0.0
        else:
            load_r = {"SHORT": 0.15, "OVERLOAD": 2.5}.get(effective, ch.resistance_ohms)
            source_v = 2.2 if effective == "UNDERVOLTAGE" else self.SUPPLY_V
            i = source_v / (self.SOURCE_R + load_r)
            v = i * load_r

        current_ma = int(round(i * 1000))
        if ch.command_on and not ch.fuse_tripped and current_ma >= self.FUSE_CURRENT_MA:
            ch.short_streak += 1
            if ch.short_streak >= self.FUSE_TICKS:
                ch.fuse_tripped = True
                current_ma, v = 0, 0.0
        else:
            ch.short_streak = 0
        voltage_mv = int(round(v * 1000))
        if ch.command_on and not ch.fuse_tripped and voltage_mv > 0 and self.noise_mv:
            voltage_mv = max(0, voltage_mv + self.random.randint(-self.noise_mv, self.noise_mv))
        power_mw = int(round(voltage_mv * current_ma / 1000))

        if not ch.command_on:
            # Same policy as existing ECU.scan(): OFF is not interpreted as recovery.
            # The last *stable* fault diagnosis is held until scanning resumes.
            ch.candidate = ch.stable
            ch.candidate_count = 0
            diagnostic = "OFF"
        else:
            diagnostic = self._classify(voltage_mv, current_ma, tripped=ch.fuse_tripped)
            if diagnostic == ch.stable:
                ch.candidate = ch.stable
                ch.candidate_count = 0
            else:
                if diagnostic == ch.candidate:
                    ch.candidate_count += 1
                else:
                    ch.candidate = diagnostic
                    ch.candidate_count = 1
                if ch.candidate_count >= self.DEBOUNCE_SAMPLES:
                    old = ch.stable
                    ch.stable = diagnostic
                    ch.candidate_count = 0
                    kind = "RECOVERY" if diagnostic == "NORMAL" else ("FAULT" if old == "NORMAL" else "CHANGE")
                    self.sequences[ch.ecu] = (self.sequences[ch.ecu] + 1) % 65536
                    self.events.append(LabEvent(self.tick, self.tick * .5, ch.ecu,
                                                ch.id, kind, old, diagnostic,
                                                self.sequences[ch.ecu]))

        return Reading(self.tick, self.tick * .5, ch.id, ch.ecu, ch.command_on,
                       ch.mode, effective if not ch.fuse_tripped else "TRIPPED",
                       voltage_mv, current_ma, power_mw, diagnostic,
                       ch.fuse_tripped)

    def step(self) -> tuple[Dict[int, Reading], List[LabEvent]]:
        self.tick += 1
        start = len(self.events)
        readings = {}
        for cid, ch in self.channels.items():
            reading = self._sample_channel(ch)
            readings[cid] = reading
            self.history[cid].append(reading)
            if len(self.history[cid]) > 240:
                self.history[cid].pop(0)
        self.readings = readings
        return readings, self.events[start:]


class BaselineCANBridge:
    """Original ECU→CAN→gateway pipeline restricted to open-wire diagnostics.

    Other experimental alarms remain LOCAL. No new IDs, codes or flag layouts.
    Three python-can virtual nodes: ECU A, ECU B, Gateway receiver.
    """
    def __init__(self):
        from uuid import uuid4
        import can
        self.channel = "smartharness_lab_" + uuid4().hex
        self.tx_a = self.tx_b = self.rx = None
        try:
            self.tx_a = can.Bus(interface="virtual", channel=self.channel)
            self.tx_b = can.Bus(interface="virtual", channel=self.channel)
            self.rx = can.Bus(interface="virtual", channel=self.channel)
        except Exception:
            self.close()
            raise
        self.reset()

    def reset(self):
        from simulator.circuit import Circuit
        from simulator.ecu import ECU
        self.circuits = {cid: Circuit(cid, data[0]) for cid, data in CIRCUITS.items()}
        for c in self.circuits.values():
            c.command_on = True
        self.a = ECU("A", [self.circuits[1], self.circuits[2]])
        self.b = ECU("B", [self.circuits[3], self.circuits[4]])
        # Drain stale frames left by an earlier demo before we reset the counters.
        while self.rx.recv(timeout=0) is not None:
            pass

    def step(self, lab: ElectricalLab, readings: Dict[int, Reading]):
        from simulator.can_protocol import encode_fault
        from gateway.decoder import decode_fault
        outgoing = []
        for cid, reading in readings.items():
            circuit = self.circuits[cid]
            circuit.command_on = reading.command_on
            # Only a *physical wire opening* is part of the baseline protocol.
            circuit.connected = reading.actual_mode != "OPEN"
        for ecu, tx in ((self.a, self.tx_a), (self.b, self.tx_b)):
            for event in ecu.scan():
                tx.send(encode_fault(event))
                outgoing.append(event)
        received = []
        for _ in outgoing:
            frame = self.rx.recv(timeout=0.25)
            if frame is None:
                raise RuntimeError("CAN virtual: expected frame missing")
            received.append((frame, decode_fault(frame)))
        if self.rx.recv(timeout=0) is not None:
            raise RuntimeError("CAN virtual: unexpected extra frame")
        return received

    def close(self):
        for b in (self.rx, self.tx_b, self.tx_a):
            if b is not None:
                b.shutdown()
        self.rx = self.tx_b = self.tx_a = None
