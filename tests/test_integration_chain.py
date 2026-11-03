"""SmartHarness — Integration & Reliability Tests (Mission 5)."""

import json
import sqlite3
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
