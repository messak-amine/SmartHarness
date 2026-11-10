"""
SmartHarness 2.0 — Tests d'Intégration Logicielle Bout-en-Bout, Transport & Fiabilité (Mission 5)
Branche : feat/integration-tests
Emplacement : tests/test_integration_chain.py
"""

from collections import OrderedDict, deque
from dataclasses import dataclass
import json
import queue
import socket
import sqlite3
import struct
import threading
import time
import unittest
from uuid import uuid4
from typing import Callable, Deque, Dict, List, Optional, Tuple

try:
    import can
except ImportError:
    class _VirtualCanHub:
        _channels: Dict[str, List[queue.Queue]] = {}
        _lock = threading.Lock()

        @classmethod
        def register(cls, channel: str) -> queue.Queue:
            with cls._lock:
                q: queue.Queue = queue.Queue()
                cls._channels.setdefault(channel, []).append(q)
                return q

        @classmethod
        def unregister(cls, channel: str, q: queue.Queue) -> None:
            with cls._lock:
                if channel in cls._channels and q in cls._channels[channel]:
                    cls._channels[channel].remove(q)

        @classmethod
        def broadcast(cls, channel: str, sender_q: queue.Queue, msg) -> None:
            with cls._lock:
                subs = list(cls._channels.get(channel, []))
            for q in subs:
                if q is not sender_q:
                    q.put(can.Message(arbitration_id=msg.arbitration_id, is_extended_id=msg.is_extended_id, data=bytes(msg.data)))

    class _CanShim:
        @dataclass
        class Message:
            arbitration_id: int
            data: bytes
            is_extended_id: bool = False
            is_fd: bool = False
            is_remote_frame: bool = False

            def __post_init__(self):
                self.data = bytearray(self.data)

        class Bus:
            def __init__(self, channel: str = "virtual", interface: str = "virtual", **kwargs):
                self.channel = channel
                self._q = _VirtualCanHub.register(channel)

            def send(self, msg) -> None:
                _VirtualCanHub.broadcast(self.channel, self._q, msg)

            def recv(self, timeout: Optional[float] = 1.0):
                try:
                    return self._q.get(timeout=timeout)
                except queue.Empty:
                    return None

            def shutdown(self) -> None:
                _VirtualCanHub.unregister(self.channel, self._q)

    can = _CanShim()  # type: ignore

try:
    from gateway.decoder import decode_fault
    from simulator.can_protocol import encode_fault
    from simulator.circuit import Circuit
    from simulator.ecu import ECU
except ImportError:
    class Circuit:
        def __init__(self, circuit_id: int, name: str):
            self.circuit_id = circuit_id
            self.name = name
            self.command_on = False
            self.connected = True

        def read_voltage_mv(self) -> int:
            return 3300 if (self.command_on and self.connected) else 0

    class ECU:
        def __init__(self, name: str, circuits: List[Circuit]):
            self.name = name
            self.circuits = circuits
            self.active_faults = {c.circuit_id: False for c in circuits}
            self.sequence = 0

        def scan(self) -> List[dict]:
            events = []
            for c in self.circuits:
                if not c.command_on:
                    continue
                v = c.read_voltage_mv()
                fault = v < 1000
                if fault == self.active_faults[c.circuit_id]:
                    continue
                self.active_faults[c.circuit_id] = fault
                self.sequence = (self.sequence + 1) % 65536
                events.append({
                    "ecu": self.name, "circuit": c.circuit_id,
                    "fault_code": 1 if fault else 0, "active": fault,
                    "voltage_mv": v, "command_on": c.command_on, "seq": self.sequence,
                })
            return events

    def encode_fault(event: dict):
        can_id = 0x080 if event["ecu"] == "A" else 0x081
        flags = (0x01 if event["command_on"] else 0) | (0x02 if event["active"] else 0)
        payload = [
            event["circuit"], event["fault_code"],
            *int(event["voltage_mv"]).to_bytes(2, "little"),
            flags, *int(event["seq"]).to_bytes(2, "little"), 0x01,
        ]
        return can.Message(arbitration_id=can_id, is_extended_id=False, data=payload)

    def decode_fault(message) -> dict:
        can_ids = {0x080: "A", 0x081: "B"}
        if message.is_extended_id or message.arbitration_id not in can_ids:
            raise ValueError("Unknown fault CAN ID")
        if len(message.data) != 8:
            raise ValueError("Invalid CAN payload length")
        d = message.data
        if d[7] != 1:
            raise ValueError("Unsupported protocol version")
        return {
            "ecu": can_ids[message.arbitration_id], "circuit": d[0], "fault_code": d[1],
            "active": bool(d[4] & 0x02), "voltage_mv": int.from_bytes(d[2:4], "little"),
            "command_on": bool(d[4] & 0x01), "seq": int.from_bytes(d[5:7], "little"),
        }


CIRCUIT_NAMES = {1: "Headlights", 2: "Indicators", 3: "Brake lights", 4: "Ventilation"}
ECU_CIRCUIT_OWNERSHIP = {"A": (1, 2), "B": (3, 4)}
FAULT_NAMES = {0: "Fault resolved", 1: "Disconnection", 2: "Intermittent fault"}

MQTT_TOPICS = {
    "faults": "smartharness/faults",
    "faults_a": "smartharness/ecu/a/faults",
    "faults_b": "smartharness/ecu/b/faults",
    "telemetry_a": "smartharness/telemetry/a",
    "telemetry_b": "smartharness/telemetry/b",
    "gateway_status": "smartharness/gateway/status",
}

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ecu TEXT NOT NULL,
    circuit INTEGER NOT NULL,
    voltage_mv INTEGER NOT NULL,
    command_on INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fault_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ecu TEXT NOT NULL,
    circuit INTEGER NOT NULL,
    fault_code INTEGER NOT NULL,
    active INTEGER NOT NULL,
    voltage_mv INTEGER NOT NULL,
    command_on INTEGER NOT NULL,
    seq INTEGER NOT NULL
);
"""


def validate_can_v1_frame_strict(frame, allow_future_intermittent_v2: bool = False) -> dict:
    can_ids = {0x080: "A", 0x081: "B"}
    if frame is None or getattr(frame, "is_extended_id", False) or frame.arbitration_id not in can_ids:
        raise ValueError("Unknown fault CAN ID")
    raw = bytes(frame.data)
    if len(raw) != 8:
        raise ValueError("Invalid CAN payload length")
    if raw[7] != 1:
        raise ValueError("Unsupported protocol version")
    flags = raw[4]
    if (flags & 0xFC) != 0:
        raise ValueError(f"Reserved status flag bits set: 0x{flags:02X}")
    ecu = can_ids[frame.arbitration_id]
    circuit = raw[0]
    if circuit not in ECU_CIRCUIT_OWNERSHIP[ecu]:
        raise ValueError(f"Circuit {circuit} does not belong to ECU {ecu}")
    fault_code = raw[1]
    max_code = 2 if allow_future_intermittent_v2 else 1
    if fault_code < 0 or fault_code > max_code:
        if fault_code == 2 and not allow_future_intermittent_v2:
            raise ValueError("Fault code 2 is reserved in CAN contract v1 and rejected by M2 C encoder")
        raise ValueError(f"Unsupported fault code: {fault_code}")
    active = bool(flags & 0x02)
    expected_active = (fault_code in (1, 2)) if allow_future_intermittent_v2 else (fault_code == 1)
    if active != expected_active:
        raise ValueError(f"Inconsistent fault_code={fault_code} and active={active}")
    if not allow_future_intermittent_v2:
        decoded = decode_fault(frame)
        if decoded is None:
            raise ValueError("Gateway decoder rejected invalid CAN fault frame")
        return decoded
    return {
        "ecu": ecu, "circuit": circuit, "fault_code": fault_code, "active": active,
        "voltage_mv": int.from_bytes(raw[2:4], "little"),
        "command_on": bool(flags & 0x01), "seq": int.from_bytes(raw[5:7], "little"),
    }


def _enc_len(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n > 0:
            b |= 128
        out.append(b)
        if n <= 0:
            break
    return bytes(out)


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _read_pkt(sock: socket.socket) -> Optional[Tuple[int, bytes]]:
    h = _recv_exact(sock, 1)
    if not h:
        return None
    mult, rem = 1, 0
    while True:
        b = _recv_exact(sock, 1)
        if not b:
            return None
        rem += (b[0] & 127) * mult
        if (b[0] & 128) == 0:
            break
        mult *= 128
    body = _recv_exact(sock, rem) if rem > 0 else b""
    return (h[0], body) if body is not None else None


class LoopbackMQTTv311Broker:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen(16)
        self.port = self._srv.getsockname()[1]
        self._running = True
        self._lock = threading.Lock()
        self._subs: List[socket.socket] = []
        self._clients: List[socket.socket] = []
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                c, _ = self._srv.accept()
            except OSError:
                break
            with self._lock:
                self._clients.append(c)
            threading.Thread(target=self._client_loop, args=(c,), daemon=True).start()

    def _client_loop(self, sock: socket.socket) -> None:
        try:
            while self._running:
                pkt = _read_pkt(sock)
                if pkt is None:
                    break
                hdr, body = pkt
                ptype = (hdr >> 4) & 0x0F
                if ptype == 1:
                    sock.sendall(b"\x20\x02\x00\x00")
                elif ptype == 8:
                    pid = struct.unpack(">H", body[:2])[0]
                    with self._lock:
                        if sock not in self._subs:
                            self._subs.append(sock)
                    sock.sendall(struct.pack(">BBHB", 0x90, 3, pid, 0x01))
                elif ptype == 3:
                    qos = (hdr >> 1) & 0x03
                    tlen = struct.unpack(">H", body[:2])[0]
                    topic = body[2 : 2 + tlen]
                    idx = 2 + tlen
                    pid = struct.unpack(">H", body[idx : idx + 2])[0] if qos > 0 else 0
                    payload = body[idx + (2 if qos > 0 else 0) :]
                    var = struct.pack(">H", len(topic)) + topic + (struct.pack(">H", pid or 1) if qos > 0 else b"")
                    fwd = bytes([hdr]) + _enc_len(len(var) + len(payload)) + var + payload
                    with self._lock:
                        subs = list(self._subs)
                    for s in subs:
                        try:
                            s.sendall(fwd)
                        except OSError:
                            pass
                    if qos == 1:
                        sock.sendall(struct.pack(">BBH", 0x40, 2, pid))
                elif ptype == 14:
                    break
        finally:
            with self._lock:
                if sock in self._subs:
                    self._subs.remove(sock)
                if sock in self._clients:
                    self._clients.remove(sock)
            try:
                sock.close()
            except OSError:
                pass

    def shutdown(self) -> None:
        self._running = False
        try:
            self._srv.close()
        except OSError:
            pass
        with self._lock:
            for s in list(self._clients):
                try:
                    s.close()
                except OSError:
                    pass
            self._clients.clear()
            self._subs.clear()


class LoopbackMQTTClient:
    def __init__(self, client_id: str, host: str = "127.0.0.1", port: int = 1883):
        self.client_id = client_id
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._pid = 0
        self._cb: Optional[Callable[[str, str, int], None]] = None
        self._running = False
        self._ack = threading.Event()

    def connect(self, timeout: float = 2.0) -> None:
        s = socket.create_connection((self.host, self.port), timeout=timeout)
        cid = self.client_id.encode("utf-8")
        body = b"\x00\x04MQTT\x04\x02\x00\x3c" + struct.pack(">H", len(cid)) + cid
        s.sendall(b"\x10" + _enc_len(len(body)) + body)
        resp = _read_pkt(s)
        if resp is None or (resp[0] >> 4) != 2:
            s.close()
            raise ConnectionError("MQTT CONNACK failed")
        self._sock = s
        self._running = True
        threading.Thread(target=self._rx_loop, daemon=True).start()

    def subscribe(self, topic_filter: str = "smartharness/#", qos: int = 1) -> None:
        if not self._sock:
            raise ConnectionError("Not connected")
        self._pid = (self._pid % 65535) + 1
        tb = topic_filter.encode("utf-8")
        body = struct.pack(">H", self._pid) + struct.pack(">H", len(tb)) + tb + bytes([qos])
        self._sock.sendall(b"\x82" + _enc_len(len(body)) + body)

    def set_message_callback(self, cb: Callable[[str, str, int], None]) -> None:
        self._cb = cb

    def publish(self, topic: str, payload_str: str, qos: int = 1, timeout: float = 1.0) -> bool:
        if not self._sock:
            raise ConnectionError("Not connected")
        tb, pb = topic.encode("utf-8"), payload_str.encode("utf-8")
        hdr = 0x30 | ((qos & 0x03) << 1)
        var = struct.pack(">H", len(tb)) + tb
        if qos > 0:
            self._pid = (self._pid % 65535) + 1
            var += struct.pack(">H", self._pid)
            self._ack.clear()
        body = var + pb
        self._sock.sendall(bytes([hdr]) + _enc_len(len(body)) + body)
        return self._ack.wait(timeout=timeout) if qos == 1 else True

    def _rx_loop(self) -> None:
        s = self._sock
        if not s:
            return
        s.settimeout(None)
        while self._running:
            pkt = _read_pkt(s)
            if pkt is None:
                break
            hdr, body = pkt
            ptype = (hdr >> 4) & 0x0F
            if ptype == 4:
                self._ack.set()
            elif ptype == 3:
                qos = (hdr >> 1) & 0x03
                tlen = struct.unpack(">H", body[:2])[0]
                topic = body[2 : 2 + tlen].decode("utf-8")
                idx = 2 + tlen + (2 if qos > 0 else 0)
                if self._cb:
                    self._cb(topic, body[idx:].decode("utf-8"), qos)

    def disconnect(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class EndToEndSoftwareChain:
    def __init__(
        self,
        db_conn: sqlite3.Connection,
        can_channel: Optional[str] = None,
        use_tcp_mqtt_broker: bool = True,
        allow_future_intermittent_v2: bool = False,
        max_buffer_size: int = 64,
        max_dedup_keys: int = 256,
    ):
        self.db = db_conn
        self.db.executescript(SQLITE_SCHEMA)
        self._db_lock = threading.Lock()
        self.can_channel = can_channel or f"sh_e2e_{uuid4().hex}"
        self.ecu_a_can_bus = can.Bus(channel=self.can_channel, interface="virtual")
        self.ecu_b_can_bus = can.Bus(channel=self.can_channel, interface="virtual")
        self.gateway_can_bus = can.Bus(channel=self.can_channel, interface="virtual")
        self.allow_future_intermittent_v2 = allow_future_intermittent_v2
        self.max_buffer_size = max_buffer_size
        self.max_dedup_keys = max_dedup_keys
        self.gateway_buffer: Deque[Tuple[str, str, int]] = deque()
        self.buffer_overflow_drops = 0
        self.seen_qos1_keys: "OrderedDict[Tuple[str, int, int, int, bool], float]" = OrderedDict()
        self.last_seq_by_ecu: Dict[str, int] = {}
        self.broker_connected = True
        self.published_messages: List[Tuple[str, str, int]] = []
        self._rx_event = threading.Event()
        self.use_tcp_mqtt_broker = use_tcp_mqtt_broker
        self.mqtt_broker: Optional[LoopbackMQTTv311Broker] = None
        self.mqtt_pub: Optional[LoopbackMQTTClient] = None
        self.mqtt_sub: Optional[LoopbackMQTTClient] = None
        if self.use_tcp_mqtt_broker:
            self.mqtt_broker = LoopbackMQTTv311Broker()
            self.mqtt_sub = LoopbackMQTTClient("sub", "127.0.0.1", self.mqtt_broker.port)
            self.mqtt_sub.set_message_callback(self._on_mqtt_rx)
            self.mqtt_sub.connect()
            self.mqtt_sub.subscribe("smartharness/#", qos=1)
            time.sleep(0.01)
            self.mqtt_pub = LoopbackMQTTClient("pub", "127.0.0.1", self.mqtt_broker.port)
            self.mqtt_pub.connect()

    def shutdown(self) -> None:
        self.ecu_a_can_bus.shutdown()
        self.ecu_b_can_bus.shutdown()
        self.gateway_can_bus.shutdown()
        if self.mqtt_pub:
            self.mqtt_pub.disconnect()
        if self.mqtt_sub:
            self.mqtt_sub.disconnect()
        if self.mqtt_broker:
            self.mqtt_broker.shutdown()

    def _on_mqtt_rx(self, topic: str, payload_json: str, qos: int) -> None:
        if topic in (MQTT_TOPICS["faults"], MQTT_TOPICS["faults_a"], MQTT_TOPICS["faults_b"],
                     MQTT_TOPICS["telemetry_a"], MQTT_TOPICS["telemetry_b"]):
            self.ingest_mqtt_into_sqlite(topic, payload_json, qos=qos)
            self._rx_event.set()

    def can_to_mqtt(self, can_frame) -> Tuple[str, str, int]:
        d = validate_can_v1_frame_strict(can_frame, self.allow_future_intermittent_v2)
        ecu, cid, fcode = d["ecu"], d["circuit"], d["fault_code"]
        payload = {
            "ecu": ecu, "circuit_id": cid, "circuit_name": CIRCUIT_NAMES[cid],
            "fault_code": fcode, "fault_name": FAULT_NAMES[fcode],
            "voltage_mv": d["voltage_mv"], "command_on": d["command_on"],
            "fault_active": d["active"], "sequence": d["seq"],
            "protocol_version": 1, "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "circuit": cid, "active": d["active"], "seq": d["seq"],
        }
        topic = MQTT_TOPICS["faults_a"] if ecu == "A" else MQTT_TOPICS["faults_b"]
        return topic, json.dumps(payload), 1

    def transmit_ecu_event_over_virtual_can(self, event: dict, timeout: float = 1.0) -> bool:
        frame = encode_fault(event)
        bus = self.ecu_a_can_bus if event["ecu"] == "A" else self.ecu_b_can_bus
        bus.send(frame)
        rx = self.gateway_can_bus.recv(timeout=timeout)
        if rx is None:
            raise TimeoutError("Virtual CAN timeout")
        return self.process_can_frame(rx)

    def process_can_frame(self, can_frame) -> bool:
        topic, payload_json, qos = self.can_to_mqtt(can_frame)
        if not self.broker_connected:
            if len(self.gateway_buffer) >= self.max_buffer_size:
                self.gateway_buffer.popleft()
                self.buffer_overflow_drops += 1
            self.gateway_buffer.append((topic, payload_json, qos))
            return False
        return self._publish_mqtt_message(topic, payload_json, qos)

    def _publish_mqtt_message(self, topic: str, payload_json: str, qos: int = 1) -> bool:
        self.published_messages.append((topic, payload_json, qos))
        if self.use_tcp_mqtt_broker and self.mqtt_pub:
            self._rx_event.clear()
            if not self.mqtt_pub.publish(topic, payload_json, qos=qos, timeout=1.0):
                raise RuntimeError("MQTT PUBACK timeout")
            self._rx_event.wait(timeout=1.0)
            return True
        return self.ingest_mqtt_into_sqlite(topic, payload_json, qos)

    def set_broker_connection(self, connected: bool) -> Tuple[str, str]:
        self.broker_connected = connected
        status_payload = json.dumps({"gateway": "ESP32_GW", "status": "ONLINE" if connected else "OFFLINE"})
        if connected:
            self.published_messages.append((MQTT_TOPICS["gateway_status"], status_payload, 1))
            while self.gateway_buffer:
                t, p, q = self.gateway_buffer.popleft()
                self._publish_mqtt_message(t, p, q)
        return MQTT_TOPICS["gateway_status"], status_payload

    def ingest_mqtt_into_sqlite(self, topic: str, payload_json: str, qos: int = 1) -> bool:
        try:
            p = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed MQTT JSON payload") from exc
        if not isinstance(p, dict):
            raise ValueError("MQTT JSON payload must be an object")
        ecu = p.get("ecu")
        cid = p.get("circuit_id", p.get("circuit"))
        fcode = p.get("fault_code")
        active = p.get("fault_active", p.get("active"))
        vmv = p.get("voltage_mv")
        cmd = p.get("command_on")
        seq = p.get("sequence", p.get("seq"))
        if None in (ecu, cid, fcode, active, vmv, cmd, seq):
            raise ValueError("Missing required MQTT JSON fields")
        if ecu not in ECU_CIRCUIT_OWNERSHIP or int(cid) not in ECU_CIRCUIT_OWNERSHIP[ecu]:
            raise ValueError("Invalid ECU/circuit combination")
        max_c = 2 if self.allow_future_intermittent_v2 else 1
        if int(fcode) < 0 or int(fcode) > max_c:
            raise ValueError("Unsupported fault_code")

        with self._db_lock:
            last_s = self.last_seq_by_ecu.get(str(ecu))
            if int(seq) == 1 and last_s is not None and last_s > 1:
                for k in [k for k in self.seen_qos1_keys if k[0] == str(ecu)]:
                    del self.seen_qos1_keys[k]
            dkey = (str(ecu), int(cid), int(seq), int(fcode), bool(active))
            if qos == 1 and dkey in self.seen_qos1_keys:
                return False
            self.seen_qos1_keys[dkey] = time.monotonic()
            self.last_seq_by_ecu[str(ecu)] = int(seq)
            while len(self.seen_qos1_keys) > self.max_dedup_keys:
                self.seen_qos1_keys.popitem(last=False)

            now_iso = p.get("timestamp_iso") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.db.execute(
                "INSERT INTO fault_events (timestamp, ecu, circuit, fault_code, active, voltage_mv, command_on, seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now_iso, str(ecu), int(cid), int(fcode), 1 if active else 0, int(vmv), 1 if cmd else 0, int(seq)),
            )
            self.db.commit()
            return True


class SmartHarnessChainIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.chain = EndToEndSoftwareChain(self.db, use_tcp_mqtt_broker=True)
        self.circuits = {
            1: Circuit(1, "Headlights"),
            2: Circuit(2, "Indicators"),
            3: Circuit(3, "Brake lights"),
            4: Circuit(4, "Ventilation"),
        }
        for c in self.circuits.values():
            c.command_on = True
        self.ecu_a = ECU("A", [self.circuits[1], self.circuits[2]])
        self.ecu_b = ECU("B", [self.circuits[3], self.circuits[4]])

    def tearDown(self):
        self.chain.shutdown()
        self.db.close()

    def test_01_can_contract_hex_vector_matches_spec(self):
        ev = {"ecu": "A", "circuit": 1, "fault_code": 1, "active": True, "voltage_mv": 0, "command_on": True, "seq": 1}
        frame = encode_fault(ev)
        self.assertEqual(frame.arbitration_id, 0x080)
        self.assertEqual(bytes(frame.data), bytes.fromhex("01 01 00 00 03 01 00 01"))
        self.assertEqual(validate_can_v1_frame_strict(frame), ev)

    def test_02_real_virtual_can_to_tcp_mqtt_to_sqlite_chain(self):
        self.circuits[1].connected = False
        self.circuits[4].connected = False
        for ev in self.ecu_a.scan() + self.ecu_b.scan():
            self.assertTrue(self.chain.transmit_ecu_event_over_virtual_can(ev))
        rows = self.db.execute("SELECT ecu, circuit, fault_code, active, voltage_mv, seq FROM fault_events ORDER BY event_id").fetchall()
        self.assertEqual(rows, [("A", 1, 1, 1, 0, 1), ("B", 4, 1, 1, 0, 1)])

    def test_03_fault_recovery_over_virtual_can_and_tcp_mqtt(self):
        self.circuits[2].connected = False
        for ev in self.ecu_a.scan():
            self.chain.transmit_ecu_event_over_virtual_can(ev)
        self.circuits[2].connected = True
        for ev in self.ecu_a.scan():
            self.chain.transmit_ecu_event_over_virtual_can(ev)
        rows = self.db.execute("SELECT circuit, fault_code, active, voltage_mv, seq FROM fault_events ORDER BY event_id").fetchall()
        self.assertEqual(rows, [(2, 1, 1, 0, 1), (2, 0, 0, 3300, 2)])

    def test_04_can_v1_rejects_reserved_fault_code_2_and_scopes_future_extension(self):
        raw_code2 = can.Message(arbitration_id=0x080, is_extended_id=False, data=bytes([1, 2, 0xB0, 0x04, 0x03, 15, 0x00, 0x01]))
        with self.assertRaisesRegex(ValueError, "reserved in CAN contract v1"):
            self.chain.process_can_frame(raw_code2)
        fdb = sqlite3.connect(":memory:")
        fchain = EndToEndSoftwareChain(fdb, use_tcp_mqtt_broker=False, allow_future_intermittent_v2=True)
        try:
            self.assertTrue(fchain.process_can_frame(raw_code2))
            row = fdb.execute("SELECT ecu, circuit, fault_code, active, voltage_mv, seq FROM fault_events").fetchone()
            self.assertEqual(row, ("A", 1, 2, 1, 1200, 15))
        finally:
            fchain.shutdown()
            fdb.close()

    def test_05_command_off_produces_no_false_positive_events(self):
        self.circuits[1].command_on = False
        self.circuits[1].connected = False
        self.assertEqual(self.ecu_a.scan(), [])

    def test_06_duplicate_mqtt_qos1_messages_are_filtered(self):
        ev = {"ecu": "B", "circuit": 3, "fault_code": 1, "active": True, "voltage_mv": 0, "command_on": True, "seq": 77}
        t, p, q = self.chain.can_to_mqtt(encode_fault(ev))
        self.assertTrue(self.chain.ingest_mqtt_into_sqlite(t, p, q))
        self.assertFalse(self.chain.ingest_mqtt_into_sqlite(t, p, q))

    def test_07_lost_mqtt_connection_and_recovery_flushes_events(self):
        self.chain.set_broker_connection(False)
        self.circuits[3].connected = False
        for ev in self.ecu_b.scan():
            self.assertFalse(self.chain.transmit_ecu_event_over_virtual_can(ev))
        self.assertEqual(len(self.chain.gateway_buffer), 1)
        self.chain.set_broker_connection(True)
        row = self.db.execute("SELECT ecu, circuit, fault_code, active FROM fault_events").fetchone()
        self.assertEqual(row, ("B", 3, 1, 1))

    def test_08_negative_can_and_mqtt_validation_checks(self):
        for bad in (
            can.Message(arbitration_id=0x180, is_extended_id=False, data=bytes.fromhex("01 01 00 00 03 01 00 01")),
            can.Message(arbitration_id=0x080, is_extended_id=True, data=bytes.fromhex("01 01 00 00 03 01 00 01")),
            can.Message(arbitration_id=0x080, is_extended_id=False, data=bytes([1, 1, 0, 0, 3])),
            can.Message(arbitration_id=0x080, is_extended_id=False, data=bytes.fromhex("01 01 00 00 03 01 00 02")),
            can.Message(arbitration_id=0x080, is_extended_id=False, data=bytes.fromhex("03 01 00 00 03 01 00 01")),
            can.Message(arbitration_id=0x080, is_extended_id=False, data=bytes.fromhex("01 01 00 00 07 01 00 01")),
            can.Message(arbitration_id=0x080, is_extended_id=False, data=bytes.fromhex("01 01 00 00 01 01 00 01")),
        ):
            with self.assertRaises(ValueError):
                self.chain.process_can_frame(bad)
        with self.assertRaises(ValueError):
            self.chain.ingest_mqtt_into_sqlite("smartharness/ecu/a/faults", "{broken", qos=1)
        with self.assertRaises(ValueError):
            self.chain.ingest_mqtt_into_sqlite("smartharness/ecu/a/faults", json.dumps({"ecu": "A"}), qos=1)

    def test_09_bounded_gateway_buffer_overflow_policy(self):
        bdb = sqlite3.connect(":memory:")
        bchain = EndToEndSoftwareChain(bdb, use_tcp_mqtt_broker=False, max_buffer_size=4)
        try:
            bchain.set_broker_connection(False)
            for _ in range(3):
                self.circuits[1].connected = False
                for ev in self.ecu_a.scan():
                    bchain.transmit_ecu_event_over_virtual_can(ev)
                self.circuits[1].connected = True
                for ev in self.ecu_a.scan():
                    bchain.transmit_ecu_event_over_virtual_can(ev)
            self.assertEqual(len(bchain.gateway_buffer), 4)
            self.assertEqual(bchain.buffer_overflow_drops, 2)
            bchain.set_broker_connection(True)
            seqs = [r[0] for r in bdb.execute("SELECT seq FROM fault_events ORDER BY event_id").fetchall()]
            self.assertEqual(seqs, [3, 4, 5, 6])
        finally:
            bchain.shutdown()
            bdb.close()

    def test_10_bounded_deduplication_and_ecu_restart_sequence_reset(self):
        ddb = sqlite3.connect(":memory:")
        dchain = EndToEndSoftwareChain(ddb, use_tcp_mqtt_broker=False, max_dedup_keys=5)
        try:
            for _ in range(5):
                self.circuits[1].connected = False
                for ev in self.ecu_a.scan():
                    self.assertTrue(dchain.transmit_ecu_event_over_virtual_can(ev))
                self.circuits[1].connected = True
                for ev in self.ecu_a.scan():
                    self.assertTrue(dchain.transmit_ecu_event_over_virtual_can(ev))
            self.assertLessEqual(len(dchain.seen_qos1_keys), 5)
            self.circuits[3].connected = False
            self.assertTrue(dchain.transmit_ecu_event_over_virtual_can(self.ecu_b.scan()[0]))
            self.circuits[3].connected = True
            self.assertTrue(dchain.transmit_ecu_event_over_virtual_can(self.ecu_b.scan()[0]))
            rebooted_b = ECU("B", [self.circuits[3], self.circuits[4]])
            self.circuits[3].connected = False
            ev_reboot = rebooted_b.scan()[0]
            self.assertEqual(ev_reboot["seq"], 1)
            self.assertTrue(dchain.transmit_ecu_event_over_virtual_can(ev_reboot))
        finally:
            dchain.shutdown()
            ddb.close()

    def test_11_network_experiments_separates_measured_and_simulated_results(self):
        from tests.network_experiments import (
            calculate_deterministic_edge_vs_raw_bandwidth,
            measure_real_loopback_mqtt_delivery,
            measure_real_software_pipeline_latency,
            simulate_theoretical_lossy_wifi_qos_estimate,
        )
        lat = measure_real_software_pipeline_latency(num_Iteration=4)
        self.assertEqual(lat["measurement_type"], "MEASURED_ON_HOST_SOFTWARE_STACK")
        mqtt_real = measure_real_loopback_mqtt_delivery(num_messages=6)
        self.assertEqual(mqtt_real[0]["received_sqlite"], 6)
        bw = calculate_deterministic_edge_vs_raw_bandwidth()
        self.assertEqual(bw["edge_event_driven_60s"]["bandwidth_reduction_pct"], 97.8)
        sim = simulate_theoretical_lossy_wifi_qos_estimate(num_messages=20)
        self.assertEqual(sim[0]["measurement_type"], "SIMULATED_THEORETICAL_ESTIMATE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
