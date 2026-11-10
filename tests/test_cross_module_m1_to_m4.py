"""
SmartHarness 2.0 — Cross-Module M1 + M2 + M3 + M4 Compatibility Test (Mission 5)
Validates direct interoperability across:
- M1 (`simulator.circuit.Circuit`, `simulator.ecu.ECU`)
- M2 (`simulator.can_protocol.encode_fault`, `gateway.decoder.decode_fault`)
- M3 (`gateway.can_mqtt_bridge.forward`, `gateway.mqtt_publisher.MQTTPublisher`)
- M4 (`dashboard/sql/schema.sql` SQLite table and CHECK constraints)
"""

import json
from pathlib import Path
import sqlite3
import sys
import types
import unittest

from gateway.decoder import decode_fault
from simulator.can_protocol import encode_fault
from simulator.circuit import Circuit
from simulator.ecu import ECU


class CrossModuleM1ToM4Tests(unittest.TestCase):
    def test_m1_ecu_to_m2_can_to_m3_bridge_to_m4_dashboard_sql_schema(self):
        repo_root = Path(__file__).resolve().parent.parent
        schema_path = repo_root / "dashboard" / "sql" / "schema.sql"
        self.assertTrue(schema_path.exists(), "M4 dashboard/sql/schema.sql must exist")

        db = sqlite3.connect(":memory:")
        db.executescript(schema_path.read_text(encoding="utf-8"))

        captured_mqtt = []

        class _FakePahoResult:
            rc = 0
            mid = 1

        class _FakePahoClient:
            def publish(self, topic, payload, qos=1, retain=False):
                captured_mqtt.append((topic, payload, qos, retain))
                return _FakePahoResult()

            def reconnect_delay_set(self, *args, **kwargs):
                pass

            def max_queued_messages_set(self, *args, **kwargs):
                pass

            def will_set(self, *args, **kwargs):
                pass

        injected_paho = False
        try:
            try:
                import paho.mqtt.client  # noqa: F401
            except ImportError:
                injected_paho = True
                paho_mod = types.ModuleType("paho")
                mqtt_mod = types.ModuleType("paho.mqtt")
                client_mod = types.ModuleType("paho.mqtt.client")
                client_mod.MQTT_ERR_SUCCESS = 0
                client_mod.MQTT_ERR_NO_CONN = 4
                client_mod.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
                client_mod.Client = lambda *a, **kw: _FakePahoClient()
                paho_mod.mqtt = mqtt_mod
                mqtt_mod.client = client_mod
                sys.modules["paho"] = paho_mod
                sys.modules["paho.mqtt"] = mqtt_mod
                sys.modules["paho.mqtt.client"] = client_mod

            from gateway.can_mqtt_bridge import forward as m3_forward
            from gateway.mqtt_publisher import MQTTPublisher as M3Publisher

            publisher = M3Publisher(host="127.0.0.1", port=1883, client=_FakePahoClient())

            c1 = Circuit(1, "Headlights")
            c4 = Circuit(4, "Ventilation")
            c1.command_on = True
            c4.command_on = True
            ecu_a = ECU("A", [c1])
            ecu_b = ECU("B", [c4])

            c1.connected = False
            c4.connected = False
            for ev in ecu_a.scan() + ecu_b.scan():
                frame = encode_fault(ev)
                self.assertTrue(m3_forward(frame, publisher))

            self.assertEqual(len(captured_mqtt), 2)

            for topic, payload_str, qos, _ in captured_mqtt:
                data = json.loads(payload_str)
                db.execute(
                    """
                    INSERT INTO fault_events
                    (received_at, topic, ecu, circuit, fault_code, active, voltage_mv, command_on, seq)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-11-10T14:00:00Z",
                        topic,
                        data["ecu"],
                        int(data["circuit"]),
                        int(data["fault_code"]),
                        1 if data["active"] else 0,
                        int(data["voltage_mv"]),
                        1 if data["command_on"] else 0,
                        int(data["seq"]),
                    ),
                )
            db.commit()

            rows = db.execute(
                "SELECT topic, ecu, circuit, fault_code, active FROM fault_events ORDER BY event_id"
            ).fetchall()
            self.assertEqual(rows, [
                ("smartharness/ecu/a/faults", "A", 1, 1, 1),
                ("smartharness/ecu/b/faults", "B", 4, 1, 1),
            ])

            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """
                    INSERT INTO fault_events
                    (received_at, topic, ecu, circuit, fault_code, active, voltage_mv, command_on, seq)
                    VALUES ('2026-11-10T14:00:01Z', 'smartharness/ecu/a/faults', 'A', 3, 1, 1, 0, 1, 2)
                    """
                )
        finally:
            if injected_paho:
                for mod_name in ("paho.mqtt.client", "paho.mqtt", "paho"):
                    sys.modules.pop(mod_name, None)
            db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
