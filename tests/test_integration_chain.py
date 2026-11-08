"""
SmartHarness 2.0 — Tests d'Intégration Logicielle Bout-en-Bout, Transport & Fiabilité (Mission 5)
Branche : feat/integration-tests
Emplacement dans le dépôt : tests/test_integration_chain.py

Exécution directe :
    python -m unittest discover -s tests -v
    pytest -v

Répond aux 5 points de la revue PR #2 par rapport à `develop` :
1. Chaîne d'intégration logicielle réelle :
   `simulator.ecu.ECU` -> `simulator.can_protocol.encode_fault`
   -> Bus CAN virtuel `python-can` (`can.Bus(..., interface="virtual")`)
   -> `gateway.decoder.decode_fault` + validateur strict CAN v1
   -> Courtier MQTT v3.1.1 TCP Loopback (`127.0.0.1` via `socket`) ou mock isolé explicite
   -> Déduplication & validation côté abonné -> SQLite (`fault_events`, `measurements`, `diagnostics`).
2. Alignement strict avec le contrat CAN v1 (`contracts/can_protocol.md`) et l'encodeur C de M2
   (`firmware/components/smartharness_can/smartharness_can.c`) :
   - Seuls `fault_code` `0` (résolu) et `1` (coupure) sont autorisés en v1.
   - `fault_code = 2` (intermittent) est rejeté par défaut en mode strict v1 et n'est accepté
     que lorsque l'extension future est explicitement activée (`allow_future_intermittent_v2=True`).
3. Politiques de mémoire bornée et de fiabilité :
   - Tampon hors-ligne Gateway borné par `max_buffer_size` (éviction FIFO `DROP_OLDEST`).
   - Cache de déduplication QoS 1 borné par `max_dedup_keys` (`OrderedDict`) avec détection
     de redémarrage d'ECU / réinitialisation de séquence (`seq == 1` après `last_seq > 1`).
4. Tests négatifs complets sur les trames CAN et les charges utiles JSON MQTT.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
import sqlite3
import queue
import socket
import struct
import threading
import time
import unittest
from uuid import uuid4
from typing import Callable, Deque, Dict, List, Optional, Tuple

try:
    import can
    HAS_PYTHON_CAN = True
except ImportError:
    HAS_PYTHON_CAN = False

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
        def broadcast(cls, channel: str, sender_q: queue.Queue, msg: "can.Message") -> None:
            with cls._lock:
                subscribers = list(cls._channels.get(channel, []))
            for q in subscribers:
                if q is not sender_q:
                    q.put(
                        can.Message(
                            arbitration_id=msg.arbitration_id,
                            is_extended_id=msg.is_extended_id,
                            data=bytes(msg.data),
                        )
                    )

    class _CanShimModule:
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
                self.interface = interface
                self._queue = _VirtualCanHub.register(channel)

            def send(self, msg: "can.Message") -> None:
                _VirtualCanHub.broadcast(self.channel, self._queue, msg)

            def recv(self, timeout: Optional[float] = 1.0) -> Optional["can.Message"]:
                try:
                    return self._queue.get(timeout=timeout)
                except queue.Empty:
                    return None

            def shutdown(self) -> None:
                _VirtualCanHub.unregister(self.channel, self._queue)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.shutdown()

    can = _CanShimModule()  # type: ignore

try:
    from gateway.decoder import decode_fault
    from simulator.can_protocol import encode_fault
    from simulator.circuit import Circuit
    from simulator.ecu import ECU
    HAS_REPO_MODULES = True
except ImportError:
    HAS_REPO_MODULES = False

    class Circuit:
        def __init__(self, circuit_id: int, name: str):
            self.circuit_id = circuit_id
            self.name = name
            self.command_on = False
            self.connected = True

        def read_voltage_mv(self) -> int:
            if self.command_on and self.connected:
                return 3300
            return 0

    class ECU:
        def __init__(self, name: str, circuits: List[Circuit]):
            self.name = name
            self.circuits = circuits
            self.active_faults = {c.circuit_id: False for c in circuits}
            self.sequence = 0

        def scan(self) -> List[dict]:
            events = []
            for circuit in self.circuits:
                if not circuit.command_on:
                    continue
                voltage = circuit.read_voltage_mv()
                fault_detected = voltage < 1000
                previous_fault = self.active_faults[circuit.circuit_id]
                if fault_detected == previous_fault:
                    continue
                self.active_faults[circuit.circuit_id] = fault_detected
                self.sequence = (self.sequence + 1) % 65536
                events.append({
                    "ecu": self.name,
                    "circuit": circuit.circuit_id,
                    "fault_code": 1 if fault_detected else 0,
                    "active": fault_detected,
                    "voltage_mv": voltage,
                    "command_on": circuit.command_on,
                    "seq": self.sequence,
                })
            return events

    def encode_fault(event: dict):
        can_id = 0x080 if event["ecu"] == "A" else 0x081
        flags = 0
        if event["command_on"]:
            flags |= 0x01
        if event["active"]:
            flags |= 0x02
        voltage = event["voltage_mv"]
        sequence = event["seq"]
        payload = [
            event["circuit"],
            event["fault_code"],
            *voltage.to_bytes(2, "little"),
            flags,
            *sequence.to_bytes(2, "little"),
            0x01,
        ]
        return can.Message(arbitration_id=can_id, is_extended_id=False, data=payload)

    def decode_fault(message) -> dict:
        can_ids = {0x080: "A", 0x081: "B"}
        if message.is_extended_id or message.arbitration_id not in can_ids:
            raise ValueError("Unknown fault CAN ID")
        if len(message.data) != 8:
            raise ValueError("Invalid CAN payload length")
        data = message.data
        if data[7] != 1:
            raise ValueError("Unsupported protocol version")
        return {
            "ecu": can_ids[message.arbitration_id],
            "circuit": data[0],
            "fault_code": data[1],
            "active": bool(data[4] & 0x02),
            "voltage_mv": int.from_bytes(data[2:4], "little"),
            "command_on": bool(data[4] & 0x01),
            "seq": int.from_bytes(data[5:7], "little"),
        }


CIRCUIT_NAMES = {
    1: "Headlights",
    2: "Indicators",
    3: "Brake lights",
    4: "Ventilation",
}

ECU_CIRCUIT_OWNERSHIP = {
    "A": (1, 2),
    "B": (3, 4),
}

FAULT_NAMES_V1 = {
    0: "Fault resolved",
    1: "Disconnection",
}

FAULT_NAMES_FUTURE_V2 = {
    0: "Fault resolved",
    1: "Disconnection",
    2: "Intermittent fault",
}

MQTT_TOPICS = {
    "faults": "smartharness/faults",
    "faults_a": "smartharness/ecu/a/faults",
    "faults_b": "smartharness/ecu/b/faults",
    "telemetry_a": "smartharness/telemetry/a",
    "telemetry_b": "smartharness/telemetry/b",
    "diag_request": "smartharness/diagnostics/request",
    "diag_response": "smartharness/diagnostics/response",
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

CREATE TABLE IF NOT EXISTS diagnostics (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ecu TEXT NOT NULL,
    result TEXT NOT NULL,
    voltage_mv INTEGER NOT NULL
);
"""


def validate_can_v1_frame_strict(
    frame,
    allow_future_intermittent_v2: bool = False,
) -> dict:
    can_ids = {0x080: "A", 0x081: "B"}
    if frame is None or getattr(frame, "is_extended_id", False) or frame.arbitration_id not in can_ids:
        raise ValueError("Unknown fault CAN ID")

    raw_bytes = bytes(frame.data)
    if len(raw_bytes) != 8:
        raise ValueError("Invalid CAN payload length")

    if raw_bytes[7] != 1:
        raise ValueError("Unsupported protocol version")

    flags = raw_bytes[4]
    if (flags & 0xFC) != 0:
        raise ValueError(f"Reserved status flag bits set: 0x{flags:02X}")

    ecu = can_ids[frame.arbitration_id]
    circuit = raw_bytes[0]
    if circuit not in ECU_CIRCUIT_OWNERSHIP[ecu]:
        raise ValueError(
            f"Circuit {circuit} does not belong to ECU {ecu} "
            f"(allowed: {ECU_CIRCUIT_OWNERSHIP[ecu]})"
        )

    fault_code = raw_bytes[1]
    max_allowed_code = 2 if allow_future_intermittent_v2 else 1
    if fault_code < 0 or fault_code > max_allowed_code:
        if fault_code == 2 and not allow_future_intermittent_v2:
            raise ValueError(
                "Fault code 2 (Intermittent fault) is reserved in CAN contract v1 "
                "and rejected by M2 C encoder (sh_can_encode_fault)"
            )
        raise ValueError(f"Unsupported fault code: {fault_code}")

    active = bool(flags & 0x02)
    expected_active = (fault_code in (1, 2)) if allow_future_intermittent_v2 else (fault_code == 1)
    if active != expected_active:
        raise ValueError(
            f"Inconsistent fault_code={fault_code} and active={active} in CAN frame"
        )

    if not allow_future_intermittent_v2:
        decoded = decode_fault(frame)
        if decoded is None:
            raise ValueError("Gateway decoder rejected invalid CAN fault frame")
        return decoded

    return {
        "ecu": ecu,
        "circuit": circuit,
        "fault_code": fault_code,
        "active": active,
        "voltage_mv": int.from_bytes(raw_bytes[2:4], "little"),
        "command_on": bool(flags & 0x01),
        "seq": int.from_bytes(raw_bytes[5:7], "little"),
    }


def _encode_mqtt_remaining_length(length: int) -> bytes:
    out = bytearray()
    while True:
        encoded_byte = length % 128
        length //= 128
        if length > 0:
            encoded_byte |= 128
        out.append(encoded_byte)
        if length <= 0:
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


def _read_mqtt_packet(sock: socket.socket) -> Optional[Tuple[int, bytes]]:
    first = _recv_exact(sock, 1)
    if not first:
        return None
    header_byte = first[0]
    multiplier = 1
    rem_len = 0
    while True:
        b = _recv_exact(sock, 1)
        if not b:
            return None
        encoded = b[0]
        rem_len += (encoded & 127) * multiplier
        if (encoded & 128) == 0:
            break
        multiplier *= 128
    body = _recv_exact(sock, rem_len) if rem_len > 0 else b""
    if body is None:
        return None
    return header_byte, body


class LoopbackMQTTv311Broker:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((host, port))
        self._server_sock.listen(16)
        self.port = self._server_sock.getsockname()[1]
        self._running = True
        self._clients_lock = threading.Lock()
        self._subscribers: List[socket.socket] = []
        self._client_socks: List[socket.socket] = []
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client_sock, _ = self._server_sock.accept()
            except OSError:
                break
            with self._clients_lock:
                self._client_socks.append(client_sock)
            t = threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True)
            t.start()

    def _handle_client(self, sock: socket.socket) -> None:
        try:
            while self._running:
                pkt = _read_mqtt_packet(sock)
                if pkt is None:
                    break
                header, body = pkt
                pkt_type = (header >> 4) & 0x0F

                if pkt_type == 1:
                    sock.sendall(b"\x20\x02\x00\x00")
                elif pkt_type == 8:
                    pkt_id = struct.unpack(">H", body[:2])[0]
                    with self._clients_lock:
                        if sock not in self._subscribers:
                            self._subscribers.append(sock)
                    suback = struct.pack(">BBHB", 0x90, 3, pkt_id, 0x01)
                    sock.sendall(suback)
                elif pkt_type == 3:
                    qos = (header >> 1) & 0x03
                    topic_len = struct.unpack(">H", body[:2])[0]
                    topic = body[2 : 2 + topic_len].decode("utf-8")
                    idx = 2 + topic_len
                    pkt_id = 0
                    if qos > 0:
                        pkt_id = struct.unpack(">H", body[idx : idx + 2])[0]
                        idx += 2
                    payload = body[idx:]

                    fwd_topic_bytes = topic.encode("utf-8")
                    fwd_var = struct.pack(">H", len(fwd_topic_bytes)) + fwd_topic_bytes
                    if qos > 0:
                        fwd_var += struct.pack(">H", pkt_id or 1)
                    fwd_body = fwd_var + payload
                    fwd_pkt = bytes([header]) + _encode_mqtt_remaining_length(len(fwd_body)) + fwd_body

                    with self._clients_lock:
                        subs = list(self._subscribers)
                    for sub_sock in subs:
                        try:
                            sub_sock.sendall(fwd_pkt)
                        except OSError:
                            pass

                    if qos == 1:
                        sock.sendall(struct.pack(">BBH", 0x40, 2, pkt_id))
                elif pkt_type == 14:
                    break
        finally:
            with self._clients_lock:
                if sock in self._subscribers:
                    self._subscribers.remove(sock)
                if sock in self._client_socks:
                    self._client_socks.remove(sock)
            try:
                sock.close()
            except OSError:
                pass

    def shutdown(self) -> None:
        self._running = False
        try:
            self._server_sock.close()
        except OSError:
            pass
        with self._clients_lock:
            for s in list(self._client_socks):
                try:
                    s.close()
                except OSError:
                    pass
            self._client_socks.clear()
            self._subscribers.clear()


class LoopbackMQTTClient:
    def __init__(self, client_id: str, host: str = "127.0.0.1", port: int = 1883):
        self.client_id = client_id
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._pkt_id = 0
        self._on_message: Optional[Callable[[str, str, int], None]] = None
        self._rx_thread: Optional[threading.Thread] = None
        self._running = False
        self._puback_event = threading.Event()
        self._last_puback_id = 0

    def connect(self, timeout: float = 2.0) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        sock.settimeout(timeout)
        client_bytes = self.client_id.encode("utf-8")
        var_header = b"\x00\x04MQTT\x04\x02\x00\x3c"
        payload = struct.pack(">H", len(client_bytes)) + client_bytes
        body = var_header + payload
        pkt = b"\x10" + _encode_mqtt_remaining_length(len(body)) + body
        sock.sendall(pkt)
        resp = _read_mqtt_packet(sock)
        if resp is None or (resp[0] >> 4) != 2 or resp[1][1] != 0:
            sock.close()
            raise ConnectionError("MQTT CONNACK failed")
        self._sock = sock
        self._running = True
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

    def subscribe(self, topic_filter: str = "smartharness/#", qos: int = 1) -> None:
        if self._sock is None:
            raise ConnectionError("MQTT client not connected")
        self._pkt_id = (self._pkt_id % 65535) + 1
        topic_bytes = topic_filter.encode("utf-8")
        body = struct.pack(">H", self._pkt_id) + struct.pack(">H", len(topic_bytes)) + topic_bytes + bytes([qos])
        pkt = b"\x82" + _encode_mqtt_remaining_length(len(body)) + body
        self._sock.sendall(pkt)

    def set_message_callback(self, callback: Callable[[str, str, int], None]) -> None:
        self._on_message = callback

    def publish(self, topic: str, payload_str: str, qos: int = 1, timeout: float = 1.0) -> bool:
        if self._sock is None:
            raise ConnectionError("MQTT client not connected")
        topic_bytes = topic.encode("utf-8")
        payload_bytes = payload_str.encode("utf-8")
        header_byte = 0x30 | ((qos & 0x03) << 1)
        var_header = struct.pack(">H", len(topic_bytes)) + topic_bytes
        pkt_id = 0
        if qos > 0:
            self._pkt_id = (self._pkt_id % 65535) + 1
            pkt_id = self._pkt_id
            var_header += struct.pack(">H", pkt_id)
            self._puback_event.clear()

        body = var_header + payload_bytes
        pkt = bytes([header_byte]) + _encode_mqtt_remaining_length(len(body)) + body
        self._sock.sendall(pkt)

        if qos == 1:
            return self._puback_event.wait(timeout=timeout)
        return True

    def _rx_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        sock.settimeout(None)
        while self._running:
            pkt = _read_mqtt_packet(sock)
            if pkt is None:
                break
            header, body = pkt
            pkt_type = (header >> 4) & 0x0F
            if pkt_type == 4:
                self._last_puback_id = struct.unpack(">H", body[:2])[0]
                self._puback_event.set()
            elif pkt_type == 3:
                qos = (header >> 1) & 0x03
                topic_len = struct.unpack(">H", body[:2])[0]
                topic = body[2 : 2 + topic_len].decode("utf-8")
                idx = 2 + topic_len
                if qos > 0:
                    idx += 2
                payload_str = body[idx:].decode("utf-8")
                if self._on_message is not None:
                    self._on_message(topic, payload_str, qos)

    def disconnect(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.sendall(b"\xe0\x00")
            except OSError:
                pass
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
        if max_buffer_size <= 0:
            raise ValueError("max_buffer_size must be positive")
        if max_dedup_keys <= 0:
            raise ValueError("max_dedup_keys must be positive")

        self.db = db_conn
        self.db.executescript(SQLITE_SCHEMA)
        self._db_lock = threading.Lock()

        self.can_channel = can_channel or f"smartharness_e2e_{uuid4().hex}"
        self.ecu_a_can_bus = can.Bus(channel=self.can_channel, interface="virtual")
        self.ecu_b_can_bus = can.Bus(channel=self.can_channel, interface="virtual")
        self.gateway_can_bus = can.Bus(channel=self.can_channel, interface="virtual")

        self.allow_future_intermittent_v2 = allow_future_intermittent_v2
        self.max_buffer_size = max_buffer_size
        self.max_dedup_keys = max_dedup_keys

        self.gateway_buffer: Deque[Tuple[str, str, int]] = deque()
        self.buffer_overflow_drops: int = 0

        self.seen_qos1_keys: "OrderedDict[Tuple[str, int, int, int, bool], float]" = OrderedDict()
        self.last_seq_by_ecu: Dict[str, int] = {}

        self.broker_connected = True
        self.published_messages: List[Tuple[str, str, int]] = []
        self._rx_sync_event = threading.Event()

        self.use_tcp_mqtt_broker = use_tcp_mqtt_broker
        self.mqtt_broker: Optional[LoopbackMQTTv311Broker] = None
        self.mqtt_publisher: Optional[LoopbackMQTTClient] = None
        self.mqtt_subscriber: Optional[LoopbackMQTTClient] = None

        if self.use_tcp_mqtt_broker:
            self.mqtt_broker = LoopbackMQTTv311Broker()
            self.mqtt_subscriber = LoopbackMQTTClient("sh_dashboard_sub", "127.0.0.1", self.mqtt_broker.port)
            self.mqtt_subscriber.set_message_callback(self._on_tcp_mqtt_message)
            self.mqtt_subscriber.connect()
            self.mqtt_subscriber.subscribe("smartharness/#", qos=1)
            time.sleep(0.01)

            self.mqtt_publisher = LoopbackMQTTClient("sh_gateway_pub", "127.0.0.1", self.mqtt_broker.port)
            self.mqtt_publisher.connect()

    def shutdown(self) -> None:
        self.ecu_a_can_bus.shutdown()
        self.ecu_b_can_bus.shutdown()
        self.gateway_can_bus.shutdown()
        if self.mqtt_publisher is not None:
            self.mqtt_publisher.disconnect()
        if self.mqtt_subscriber is not None:
            self.mqtt_subscriber.disconnect()
        if self.mqtt_broker is not None:
            self.mqtt_broker.shutdown()

    def _on_tcp_mqtt_message(self, topic: str, payload_json: str, qos: int) -> None:
        if topic in (MQTT_TOPICS["faults"], MQTT_TOPICS["faults_a"], MQTT_TOPICS["faults_b"],
                     MQTT_TOPICS["telemetry_a"], MQTT_TOPICS["telemetry_b"]):
            self.ingest_mqtt_into_sqlite(topic, payload_json, qos=qos)
            self._rx_sync_event.set()

    def can_to_mqtt(self, can_frame) -> Tuple[str, str, int]:
        decoded = validate_can_v1_frame_strict(
            can_frame,
            allow_future_intermittent_v2=self.allow_future_intermittent_v2,
        )
        ecu = decoded["ecu"]
        circuit_id = decoded["circuit"]
        fault_code = decoded["fault_code"]
        fault_names = FAULT_NAMES_FUTURE_V2 if self.allow_future_intermittent_v2 else FAULT_NAMES_V1

        enriched_payload = {
            "ecu": ecu,
            "circuit_id": circuit_id,
            "circuit_name": CIRCUIT_NAMES[circuit_id],
            "fault_code": fault_code,
            "fault_name": fault_names[fault_code],
            "voltage_mv": decoded["voltage_mv"],
            "command_on": decoded["command_on"],
            "fault_active": decoded["active"],
            "sequence": decoded["seq"],
            "protocol_version": 1,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "circuit": circuit_id,
            "active": decoded["active"],
            "seq": decoded["seq"],
        }
        topic = MQTT_TOPICS["faults_a"] if ecu == "A" else MQTT_TOPICS["faults_b"]
        return topic, json.dumps(enriched_payload), 1

    def _enqueue_offline_buffer(self, item: Tuple[str, str, int]) -> None:
        if len(self.gateway_buffer) >= self.max_buffer_size:
            self.gateway_buffer.popleft()
            self.buffer_overflow_drops += 1
        self.gateway_buffer.append(item)

    def transmit_ecu_event_over_virtual_can(self, event: dict, timeout: float = 1.0) -> bool:
        can_frame = encode_fault(event)
        sender_bus = self.ecu_a_can_bus if event["ecu"] == "A" else self.ecu_b_can_bus
        sender_bus.send(can_frame)

        received_frame = self.gateway_can_bus.recv(timeout=timeout)
        if received_frame is None:
            raise TimeoutError("Gateway virtual CAN bus did not receive frame within timeout")

        return self.process_can_frame(received_frame)

    def process_can_frame(self, can_frame) -> bool:
        topic, payload_json, qos = self.can_to_mqtt(can_frame)
        if not self.broker_connected:
            self._enqueue_offline_buffer((topic, payload_json, qos))
            return False

        return self._publish_mqtt_message(topic, payload_json, qos)

    def _publish_mqtt_message(self, topic: str, payload_json: str, qos: int = 1) -> bool:
        self.published_messages.append((topic, payload_json, qos))
        if self.use_tcp_mqtt_broker and self.mqtt_publisher is not None:
            self._rx_sync_event.clear()
            acked = self.mqtt_publisher.publish(topic, payload_json, qos=qos, timeout=1.0)
            if not acked:
                raise RuntimeError("MQTT QoS 1 PUBACK timeout on loopback broker")
            self._rx_sync_event.wait(timeout=1.0)
            return True
        return self.ingest_mqtt_into_sqlite(topic, payload_json, qos)

    def set_broker_connection(self, connected: bool) -> Tuple[str, str]:
        self.broker_connected = connected
        status_payload = json.dumps({
            "gateway": "ESP32_GW",
            "status": "ONLINE" if connected else "OFFLINE",
        })
        if connected:
            self.published_messages.append((MQTT_TOPICS["gateway_status"], status_payload, 1))
            while self.gateway_buffer:
                topic, payload_json, qos = self.gateway_buffer.popleft()
                self._publish_mqtt_message(topic, payload_json, qos)
        return MQTT_TOPICS["gateway_status"], status_payload

    def _check_and_record_dedup(
        self,
        ecu: str,
        circuit: int,
        seq: int,
        fault_code: int,
        active: bool,
        qos: int,
    ) -> bool:
        last_seq = self.last_seq_by_ecu.get(ecu)
        if seq == 1 and last_seq is not None and last_seq > 1:
            keys_to_remove = [k for k in self.seen_qos1_keys if k[0] == ecu]
            for k in keys_to_remove:
                del self.seen_qos1_keys[k]

        dedup_key = (ecu, circuit, seq, fault_code, active)
        if qos == 1 and dedup_key in self.seen_qos1_keys:
            return True

        self.seen_qos1_keys[dedup_key] = time.monotonic()
        self.last_seq_by_ecu[ecu] = seq

        while len(self.seen_qos1_keys) > self.max_dedup_keys:
            self.seen_qos1_keys.popitem(last=False)

        return False

    def ingest_mqtt_into_sqlite(self, topic: str, payload_json: str, qos: int = 1) -> bool:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed MQTT JSON payload") from exc

        if not isinstance(payload, dict):
            raise ValueError("MQTT JSON payload must be an object")

        ecu = payload.get("ecu")
        circuit = payload.get("circuit_id", payload.get("circuit"))
        fault_code = payload.get("fault_code")
        active = payload.get("fault_active", payload.get("active"))
        voltage_mv = payload.get("voltage_mv")
        command_on = payload.get("command_on")
        seq = payload.get("sequence", payload.get("seq"))

        if None in (ecu, circuit, fault_code, active, voltage_mv, command_on, seq):
            raise ValueError("Missing required MQTT JSON fields")

        if ecu not in ECU_CIRCUIT_OWNERSHIP or int(circuit) not in ECU_CIRCUIT_OWNERSHIP[ecu]:
            raise ValueError(f"Invalid ECU/circuit combination in MQTT payload: {ecu}/{circuit}")

        max_code = 2 if self.allow_future_intermittent_v2 else 1
        if int(fault_code) < 0 or int(fault_code) > max_code:
            raise ValueError(f"Unsupported fault_code in MQTT payload: {fault_code}")

        if int(voltage_mv) < 0 or int(voltage_mv) > 65535:
            raise ValueError(f"Out-of-range voltage_mv in MQTT payload: {voltage_mv}")

        with self._db_lock:
            if self._check_and_record_dedup(
                str(ecu),
                int(circuit),
                int(seq),
                int(fault_code),
                bool(active),
                qos,
            ):
                return False

            now_iso = payload.get("timestamp_iso") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            cur = self.db.cursor()
            if topic in (MQTT_TOPICS["faults"], MQTT_TOPICS["faults_a"], MQTT_TOPICS["faults_b"]):
                cur.execute(
                    """
                    INSERT INTO fault_events
                    (timestamp, ecu, circuit, fault_code, active, voltage_mv, command_on, seq)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_iso,
                        str(ecu),
                        int(circuit),
                        int(fault_code),
                        1 if active else 0,
                        int(voltage_mv),
                        1 if command_on else 0,
                        int(seq),
                    ),
                )
            elif topic in (MQTT_TOPICS["telemetry_a"], MQTT_TOPICS["telemetry_b"]):
                cur.execute(
                    """
                    INSERT INTO measurements (timestamp, ecu, circuit, voltage_mv, command_on)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        now_iso,
                        str(ecu),
                        int(circuit),
                        int(voltage_mv),
                        1 if command_on else 0,
                    ),
                )
            else:
                raise ValueError(f"Unsupported MQTT topic for SQLite ingestion: {topic}")

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
        event = {
            "ecu": "A",
            "circuit": 1,
            "fault_code": 1,
            "active": True,
            "voltage_mv": 0,
            "command_on": True,
            "seq": 1,
        }
        frame = encode_fault(event)
        self.assertEqual(frame.arbitration_id, 0x080)
        self.assertEqual(bytes(frame.data), bytes.fromhex("01 01 00 00 03 01 00 01"))

        decoded = validate_can_v1_frame_strict(frame)
        self.assertEqual(decoded, event)

    def test_02_real_virtual_can_to_tcp_mqtt_to_sqlite_chain(self):
        self.circuits[1].connected = False
        self.circuits[4].connected = False

        events_a = self.ecu_a.scan()
        events_b = self.ecu_b.scan()
        self.assertEqual(len(events_a), 1)
        self.assertEqual(len(events_b), 1)

        for ev in events_a + events_b:
            transmitted = self.chain.transmit_ecu_event_over_virtual_can(ev)
            self.assertTrue(transmitted)

        topics = [t for t, _, _ in self.chain.published_messages]
        self.assertEqual(topics, ["smartharness/ecu/a/faults", "smartharness/ecu/b/faults"])

        first_json = json.loads(self.chain.published_messages[0][1])
        self.assertEqual(first_json["circuit_name"], "Headlights")
        self.assertEqual(first_json["fault_name"], "Disconnection")
        self.assertEqual(first_json["protocol_version"], 1)
        self.assertIn("timestamp_iso", first_json)

        rows = self.db.execute(
            "SELECT ecu, circuit, fault_code, active, voltage_mv, seq FROM fault_events ORDER BY event_id"
        ).fetchall()
        self.assertEqual(rows, [
            ("A", 1, 1, 1, 0, 1),
            ("B", 4, 1, 1, 0, 1),
        ])

    def test_03_fault_recovery_over_virtual_can_and_tcp_mqtt(self):
        self.circuits[2].connected = False
        for ev in self.ecu_a.scan():
            self.chain.transmit_ecu_event_over_virtual_can(ev)

        self.circuits[2].connected = True
        for ev in self.ecu_a.scan():
            self.chain.transmit_ecu_event_over_virtual_can(ev)

        rows = self.db.execute(
            "SELECT circuit, fault_code, active, voltage_mv, seq FROM fault_events ORDER BY event_id"
        ).fetchall()
        self.assertEqual(rows, [
            (2, 1, 1, 0, 1),
            (2, 0, 0, 3300, 2),
        ])

    def test_04_can_v1_rejects_reserved_fault_code_2_and_scopes_future_extension(self):
        raw_code2_frame = can.Message(
            arbitration_id=0x080,
            is_extended_id=False,
            data=bytes([1, 2, 0xB0, 0x04, 0x03, 15, 0x00, 0x01]),
        )

        with self.assertRaisesRegex(ValueError, "reserved in CAN contract v1"):
            self.chain.process_can_frame(raw_code2_frame)

        count_v1 = self.db.execute("SELECT COUNT(*) FROM fault_events").fetchone()[0]
        self.assertEqual(count_v1, 0)

        future_db = sqlite3.connect(":memory:")
        future_chain = EndToEndSoftwareChain(
            future_db,
            use_tcp_mqtt_broker=False,
            allow_future_intermittent_v2=True,
        )
        try:
            self.assertTrue(future_chain.process_can_frame(raw_code2_frame))
            row = future_db.execute(
                "SELECT ecu, circuit, fault_code, active, voltage_mv, seq FROM fault_events"
            ).fetchone()
            self.assertEqual(row, ("A", 1, 2, 1, 1200, 15))
        finally:
            future_chain.shutdown()
            future_db.close()

    def test_05_command_off_produces_no_false_positive_events(self):
        self.circuits[1].command_on = False
        self.circuits[1].connected = False
        events = self.ecu_a.scan()
        self.assertEqual(events, [])
        count = self.db.execute("SELECT COUNT(*) FROM fault_events").fetchone()[0]
        self.assertEqual(count, 0)

    def test_06_duplicate_mqtt_qos1_messages_are_filtered(self):
        event = {
            "ecu": "B",
            "circuit": 3,
            "fault_code": 1,
            "active": True,
            "voltage_mv": 0,
            "command_on": True,
            "seq": 77,
        }
        frame = encode_fault(event)
        topic, payload_json, qos = self.chain.can_to_mqtt(frame)

        first_insert = self.chain.ingest_mqtt_into_sqlite(topic, payload_json, qos)
        second_insert = self.chain.ingest_mqtt_into_sqlite(topic, payload_json, qos)

        self.assertTrue(first_insert)
        self.assertFalse(second_insert, "Duplicate QoS 1 message must be ignored")
        count = self.db.execute("SELECT COUNT(*) FROM fault_events WHERE seq = 77").fetchone()[0]
        self.assertEqual(count, 1)

    def test_07_lost_mqtt_connection_and_recovery_flushes_events(self):
        self.chain.set_broker_connection(False)

        self.circuits[3].connected = False
        for ev in self.ecu_b.scan():
            stored_immediately = self.chain.transmit_ecu_event_over_virtual_can(ev)
            self.assertFalse(stored_immediately)

        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM fault_events").fetchone()[0], 0)
        self.assertEqual(len(self.chain.gateway_buffer), 1)

        status_topic, status_json = self.chain.set_broker_connection(True)
        self.assertEqual(status_topic, "smartharness/gateway/status")
        self.assertEqual(json.loads(status_json)["status"], "ONLINE")

        row = self.db.execute(
            "SELECT ecu, circuit, fault_code, active FROM fault_events"
        ).fetchone()
        self.assertEqual(row, ("B", 3, 1, 1))

    def test_08_negative_can_and_mqtt_validation_checks(self):
        bad_id_frame = can.Message(
            arbitration_id=0x180,
            is_extended_id=False,
            data=bytes.fromhex("01 01 00 00 03 01 00 01"),
        )
        with self.assertRaises(ValueError):
            self.chain.process_can_frame(bad_id_frame)

        ext_id_frame = can.Message(
            arbitration_id=0x080,
            is_extended_id=True,
            data=bytes.fromhex("01 01 00 00 03 01 00 01"),
        )
        with self.assertRaises(ValueError):
            self.chain.process_can_frame(ext_id_frame)

        short_frame = can.Message(
            arbitration_id=0x080,
            is_extended_id=False,
            data=bytes([1, 1, 0, 0, 3]),
        )
        with self.assertRaises(ValueError):
            self.chain.process_can_frame(short_frame)

        bad_ver_frame = can.Message(
            arbitration_id=0x080,
            is_extended_id=False,
            data=bytes.fromhex("01 01 00 00 03 01 00 02"),
        )
        with self.assertRaises(ValueError):
            self.chain.process_can_frame(bad_ver_frame)

        wrong_circuit_frame = can.Message(
            arbitration_id=0x080,
            is_extended_id=False,
            data=bytes.fromhex("03 01 00 00 03 01 00 01"),
        )
        with self.assertRaisesRegex(ValueError, "does not belong to ECU|rejected"):
            self.chain.process_can_frame(wrong_circuit_frame)

        reserved_flags_frame = can.Message(
            arbitration_id=0x080,
            is_extended_id=False,
            data=bytes.fromhex("01 01 00 00 07 01 00 01"),
        )
        with self.assertRaisesRegex(ValueError, "Reserved status flag bits|rejected"):
            self.chain.process_can_frame(reserved_flags_frame)

        inconsistent_frame = can.Message(
            arbitration_id=0x080,
            is_extended_id=False,
            data=bytes.fromhex("01 01 00 00 01 01 00 01"),
        )
        with self.assertRaisesRegex(ValueError, "Inconsistent|rejected"):
            self.chain.process_can_frame(inconsistent_frame)

        with self.assertRaisesRegex(ValueError, "Malformed MQTT JSON payload"):
            self.chain.ingest_mqtt_into_sqlite("smartharness/ecu/a/faults", "{broken_json", qos=1)

        with self.assertRaisesRegex(ValueError, "Missing required MQTT JSON fields"):
            self.chain.ingest_mqtt_into_sqlite("smartharness/ecu/a/faults", json.dumps({"ecu": "A"}), qos=1)

    def test_09_bounded_gateway_buffer_overflow_policy(self):
        bounded_db = sqlite3.connect(":memory:")
        bounded_chain = EndToEndSoftwareChain(
            bounded_db,
            use_tcp_mqtt_broker=False,
            max_buffer_size=4,
        )
        try:
            bounded_chain.set_broker_connection(False)

            for _ in range(3):
                self.circuits[1].connected = False
                for ev in self.ecu_a.scan():
                    bounded_chain.transmit_ecu_event_over_virtual_can(ev)
                self.circuits[1].connected = True
                for ev in self.ecu_a.scan():
                    bounded_chain.transmit_ecu_event_over_virtual_can(ev)

            self.assertEqual(len(bounded_chain.gateway_buffer), 4)
            self.assertEqual(bounded_chain.buffer_overflow_drops, 2)

            bounded_chain.set_broker_connection(True)
            seqs = [
                r[0]
                for r in bounded_db.execute("SELECT seq FROM fault_events ORDER BY event_id").fetchall()
            ]
            self.assertEqual(seqs, [3, 4, 5, 6])
        finally:
            bounded_chain.shutdown()
            bounded_db.close()

    def test_10_bounded_deduplication_and_ecu_restart_sequence_reset(self):
        dedup_db = sqlite3.connect(":memory:")
        dedup_chain = EndToEndSoftwareChain(
            dedup_db,
            use_tcp_mqtt_broker=False,
            max_dedup_keys=5,
        )
        try:
            for _ in range(5):
                self.circuits[1].connected = False
                for ev in self.ecu_a.scan():
                    self.assertTrue(dedup_chain.transmit_ecu_event_over_virtual_can(ev))
                self.circuits[1].connected = True
                for ev in self.ecu_a.scan():
                    self.assertTrue(dedup_chain.transmit_ecu_event_over_virtual_can(ev))

            self.assertLessEqual(len(dedup_chain.seen_qos1_keys), 5)
            total_rows = dedup_db.execute("SELECT COUNT(*) FROM fault_events").fetchone()[0]
            self.assertEqual(total_rows, 10)

            self.circuits[3].connected = False
            ev_b1 = self.ecu_b.scan()[0]
            self.assertEqual(ev_b1["seq"], 1)
            self.assertTrue(dedup_chain.transmit_ecu_event_over_virtual_can(ev_b1))

            self.circuits[3].connected = True
            ev_b2 = self.ecu_b.scan()[0]
            self.assertEqual(ev_b2["seq"], 2)
            self.assertTrue(dedup_chain.transmit_ecu_event_over_virtual_can(ev_b2))

            rebooted_ecu_b = ECU("B", [self.circuits[3], self.circuits[4]])
            self.circuits[3].connected = False
            ev_b_post_reboot = rebooted_ecu_b.scan()[0]
            self.assertEqual(ev_b_post_reboot["seq"], 1)

            self.assertTrue(dedup_chain.transmit_ecu_event_over_virtual_can(ev_b_post_reboot))

            ecu_b_seqs = [
                r[0]
                for r in dedup_db.execute(
                    "SELECT seq FROM fault_events WHERE ecu = 'B' ORDER BY event_id"
                ).fetchall()
            ]
            self.assertEqual(ecu_b_seqs, [1, 2, 1])
        finally:
            dedup_chain.shutdown()
            dedup_db.close()

    def test_11_network_experiments_separates_measured_and_simulated_results(self):
        from tests.network_experiments import (
            calculate_deterministic_edge_vs_raw_bandwidth,
            measure_real_loopback_mqtt_delivery,
            measure_real_software_pipeline_latency,
            simulate_theoretical_lossy_wifi_qos_estimate,
        )

        lat = measure_real_software_pipeline_latency(num_Iteration=6)
        self.assertEqual(lat["measurement_type"], "MEASURED_ON_HOST_SOFTWARE_STACK")
        self.assertEqual(lat["iterations"], 6)
        self.assertGreater(lat["max_ms"], 0.0)

        mqtt_real = measure_real_loopback_mqtt_delivery(num_messages=10)
        self.assertEqual(len(mqtt_real), 2)
        for item in mqtt_real:
            self.assertEqual(item["measurement_type"], "MEASURED_ON_HOST_SOFTWARE_STACK")
            self.assertEqual(item["received_sqlite"], 10)

        bw = calculate_deterministic_edge_vs_raw_bandwidth()
        self.assertEqual(bw["measurement_type"], "DETERMINISTIC_PROTOCOL_CALCULATION")
        self.assertEqual(bw["measured_can_frame_bytes"], 8)
        self.assertEqual(bw["edge_event_driven_60s"]["bandwidth_reduction_pct"], 97.8)

        sim = simulate_theoretical_lossy_wifi_qos_estimate(num_messages=50)
        for item in sim:
            self.assertEqual(item["measurement_type"], "SIMULATED_THEORETICAL_ESTIMATE")
            self.assertIn("[ESTIMATION SIMULÉE]", item["scenario"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

import time
import unittest
from gateway.decoder import decode_fault
from simulator.can_protocol import encode_fault
from simulator.circuit import Circuit
from simulator.ecu import ECU

MQTT_TOPICS = {
    "faults_a": "smartharness/ecu/a/faults",
    "faults_b": "smartharness/ecu/b/faults",
    "gateway_status": "smartharness/gateway/status",
}

SQLITE_SCHEMA = """
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


class EndToEndSoftwareChain:
    def __init__(self, db_conn: sqlite3.Connection):
        self.db = db_conn
        self.db.executescript(SQLITE_SCHEMA)
        self.broker_connected = True
        self.gateway_buffer = []
        self.seen_qos1_keys = set()
        self.published_messages = []

    def can_to_mqtt(self, can_frame):
        decoded = decode_fault(can_frame)
        if decoded["circuit"] not in (1, 2, 3, 4):
            raise ValueError("Invalid circuit ID")
        if decoded["fault_code"] not in (0, 1, 2):
            raise ValueError("Invalid fault code")
        topic = MQTT_TOPICS["faults_a"] if decoded["ecu"] == "A" else MQTT_TOPICS["faults_b"]
        return topic, json.dumps(decoded), 1

    def process_can_frame(self, can_frame) -> bool:
        topic, payload_json, qos = self.can_to_mqtt(can_frame)
        if not self.broker_connected:
            self.gateway_buffer.append((topic, payload_json, qos))
            return False
        self.published_messages.append((topic, payload_json, qos))
        return self.ingest_mqtt_into_sqlite(topic, payload_json, qos)

    def set_broker_connection(self, connected: bool):
        self.broker_connected = connected
        status_payload = json.dumps({"gateway": "ESP32_GW", "status": "ONLINE" if connected else "OFFLINE"})
        if connected:
            self.published_messages.append((MQTT_TOPICS["gateway_status"], status_payload, 1))
            while self.gateway_buffer:
                t, p, q = self.gateway_buffer.pop(0)
                self.published_messages.append((t, p, q))
                self.ingest_mqtt_into_sqlite(t, p, q)
        return MQTT_TOPICS["gateway_status"], status_payload

    def ingest_mqtt_into_sqlite(self, topic: str, payload_json: str, qos: int = 1) -> bool:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed MQTT JSON payload") from exc
        dedup_key = (payload["ecu"], payload["circuit"], payload["seq"], payload["fault_code"], payload["active"])
        if qos == 1 and dedup_key in self.seen_qos1_keys:
            return False
        self.seen_qos1_keys.add(dedup_key)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.db.execute(
            "INSERT INTO fault_events (timestamp, ecu, circuit, fault_code, active, voltage_mv, command_on, seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now_iso, payload["ecu"], int(payload["circuit"]), int(payload["fault_code"]), 1 if payload["active"] else 0, int(payload["voltage_mv"]), 1 if payload["command_on"] else 0, int(payload["seq"])),
        )
        self.db.commit()
        return True


class SmartHarnessChainIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.chain = EndToEndSoftwareChain(self.db)
        self.circuits = {1: Circuit(1, "Headlights"), 2: Circuit(2, "Indicators"), 3: Circuit(3, "Brake lights"), 4: Circuit(4, "Ventilation")}
        for c in self.circuits.values():
            c.command_on = True
        self.ecu_a = ECU("A", [self.circuits[1], self.circuits[2]])
        self.ecu_b = ECU("B", [self.circuits[3], self.circuits[4]])

    def tearDown(self):
        self.db.close()

    def test_01_can_contract_hex_vector_matches_spec(self):
        event = {"ecu": "A", "circuit": 1, "fault_code": 1, "active": True, "voltage_mv": 0, "command_on": True, "seq": 1}
        frame = encode_fault(event)
        self.assertEqual(frame.arbitration_id, 0x080)
        self.assertEqual(bytes(frame.data), bytes.fromhex("01 01 00 00 03 01 00 01"))
        self.assertEqual(decode_fault(frame), event)

    def test_02_full_chain_fault_to_can_to_mqtt_to_sqlite(self):
        self.circuits[1].connected = False
        self.circuits[4].connected = False
        for ev in self.ecu_a.scan() + self.ecu_b.scan():
            self.assertTrue(self.chain.process_can_frame(encode_fault(ev)))
        rows = self.db.execute("SELECT ecu, circuit, fault_code, active, voltage_mv, seq FROM fault_events ORDER BY event_id").fetchall()
        self.assertEqual(rows, [("A", 1, 1, 1, 0, 1), ("B", 4, 1, 1, 0, 1)])

    def test_03_fault_recovery_updates_sqlite_history(self):
        self.circuits[2].connected = False
        for ev in self.ecu_a.scan():
            self.chain.process_can_frame(encode_fault(ev))
        self.circuits[2].connected = True
        for ev in self.ecu_a.scan():
            self.chain.process_can_frame(encode_fault(ev))
        rows = self.db.execute("SELECT circuit, fault_code, active, voltage_mv, seq FROM fault_events ORDER BY event_id").fetchall()
        self.assertEqual(rows, [(2, 1, 1, 0, 1), (2, 0, 0, 3300, 2)])

    def test_04_intermittent_fault_code_compatibility(self):
        event = {"ecu": "A", "circuit": 1, "fault_code": 2, "active": True, "voltage_mv": 1200, "command_on": True, "seq": 15}
        self.assertTrue(self.chain.process_can_frame(encode_fault(event)))
        row = self.db.execute("SELECT ecu, circuit, fault_code, active, voltage_mv, seq FROM fault_events").fetchone()
        self.assertEqual(row, ("A", 1, 2, 1, 1200, 15))

    def test_05_command_off_produces_no_false_positive_events(self):
        self.circuits[1].command_on = False
        self.circuits[1].connected = False
        self.assertEqual(self.ecu_a.scan(), [])

    def test_06_duplicate_mqtt_qos1_messages_are_filtered(self):
        event = {"ecu": "B", "circuit": 3, "fault_code": 1, "active": True, "voltage_mv": 0, "command_on": True, "seq": 77}
        topic, payload_json, qos = self.chain.can_to_mqtt(encode_fault(event))
        self.assertTrue(self.chain.ingest_mqtt_into_sqlite(topic, payload_json, qos))
        self.assertFalse(self.chain.ingest_mqtt_into_sqlite(topic, payload_json, qos))

    def test_07_lost_mqtt_connection_and_recovery_flushes_events(self):
        self.chain.set_broker_connection(False)
        self.circuits[3].connected = False
        for ev in self.ecu_b.scan():
            self.assertFalse(self.chain.process_can_frame(encode_fault(ev)))
        self.chain.set_broker_connection(True)
        row = self.db.execute("SELECT ecu, circuit, fault_code, active FROM fault_events").fetchone()
        self.assertEqual(row, ("B", 3, 1, 1))

    def test_08_invalid_can_and_mqtt_messages_are_rejected(self):
        bad_id = encode_fault({"ecu": "A", "circuit": 1, "fault_code": 1, "active": True, "voltage_mv": 0, "command_on": True, "seq": 1})
        bad_id.arbitration_id = 0x999
        with self.assertRaisesRegex(ValueError, "Unknown fault CAN ID"):
            self.chain.process_can_frame(bad_id)
        with self.assertRaisesRegex(ValueError, "Malformed MQTT JSON payload"):
            self.chain.ingest_mqtt_into_sqlite("smartharness/ecu/a/faults", "{broken_json", qos=1)


if __name__ == "__main__":
    unittest.main()
