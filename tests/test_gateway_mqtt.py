"""Gateway contract tests and optional real Mosquitto integration tests."""
import json
import os
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
import can
import paho.mqtt.client as mqtt
from gateway.can_mqtt_bridge import forward
from gateway.decoder import decode_fault
from gateway.mqtt_publisher import MQTTPublisher
from simulator.mqtt_demo import run_demo


class GatewayMQTTTests(unittest.TestCase):
    def test_invalid_frames_never_reach_mqtt(self):
        for payload in ("01 01 00 00 07 01 00 01", "03 01 00 00 03 01 00 01",
                        "01 03 00 00 03 01 00 01", "01 00 00 00 03 01 00 01"):
            publisher = Mock()
            self.assertFalse(forward(can.Message(arbitration_id=0x80, is_extended_id=False,
                                                data=bytes.fromhex(payload)), publisher))
            publisher.publish_fault.assert_not_called()

    def test_reject_rtr_error_fd_and_dlc(self):
        for changes in ({"is_remote_frame": True}, {"is_error_frame": True},
                        {"is_fd": True}, {"dlc": 7}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                decode_fault(can.Message(arbitration_id=0x80, is_extended_id=False,
                             data=bytes.fromhex("01 01 00 00 03 01 00 01"), **changes))

    def test_four_circuits_fault_recovery(self):
        publisher = Mock()
        events = run_demo(publisher)
        self.assertEqual(len(events), 8)
        self.assertEqual([e["circuit"] for e in events], [1, 2, 3, 4] * 2)
        self.assertEqual([e["active"] for e in events], [True] * 4 + [False] * 4)
        self.assertEqual(publisher.publish_fault.call_count, 8)

    def test_qos_topics_and_queue_overflow(self):
        client = Mock()
        publisher = MQTTPublisher(client=client)
        event = dict(ecu="B", circuit=4, fault_code=1, active=True, voltage_mv=0, command_on=True, seq=1)
        client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
        publisher.publish_fault(event, wait=False)
        args, kwargs = client.publish.call_args
        self.assertEqual(args[0], "smartharness/ecu/b/faults")
        self.assertEqual(json.loads(args[1]), event)
        self.assertEqual(kwargs, {"qos": 1, "retain": False})
        client.publish.return_value.rc = mqtt.MQTT_ERR_QUEUE_SIZE
        with self.assertRaises(RuntimeError):
            publisher.publish_fault(event, wait=False)


BROKER = os.getenv("MOSQUITTO_BIN") or shutil.which("mosquitto")
if not BROKER and Path("C:/Program Files/Mosquitto/mosquitto.exe").exists():
    BROKER = "C:/Program Files/Mosquitto/mosquitto.exe"


@unittest.skipUnless(BROKER, "Install Mosquitto or set MOSQUITTO_BIN for broker integration")
class BrokerIntegrationTests(unittest.TestCase):
    def start_broker(self):
        self.process = subprocess.Popen([BROKER, "-c", str(self.config)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail("Mosquitto failed to start")
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.1):
                    return
            except OSError:
                time.sleep(0.05)
        self.fail("Broker startup timeout")

    def stop_broker(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)

    def setUp(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "mosquitto.conf"
        self.config.write_text(f"listener {self.port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
        self.start_broker()
        self.addCleanup(self.stop_broker)
        self.messages = queue.Queue()
        self.subscribed = threading.Event()
        self.subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.subscriber.reconnect_delay_set(1, 2)
        self.subscriber.on_connect = lambda c, u, f, r, p: c.subscribe("smartharness/#", qos=1)
        self.subscriber.on_subscribe = lambda *a: self.subscribed.set()
        self.subscriber.on_message = lambda c, u, m: self.messages.put((m.topic, json.loads(m.payload)))
        self.subscriber.connect("127.0.0.1", self.port)
        self.subscriber.loop_start()
        self.addCleanup(self.subscriber.loop_stop)
        self.addCleanup(self.subscriber.disconnect)
        self.assertTrue(self.subscribed.wait(5))
        self.publisher = MQTTPublisher("127.0.0.1", self.port)
        self.publisher.connect()
        self.addCleanup(self.publisher.disconnect)
        self.assertTrue(self.publisher.wait_connected())

    def collect_faults(self, expected):
        events = []
        deadline = time.monotonic() + 8
        while len(events) < expected and time.monotonic() < deadline:
            try:
                topic, event = self.messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if topic.endswith("/faults"):
                events.append((topic, event))
        self.assertEqual(len(events), expected)
        return events

    def test_virtual_can_to_real_broker(self):
        expected = run_demo(self.publisher)
        received = self.collect_faults(8)
        self.assertEqual([e for _, e in received], expected)
        for topic, event in received:
            self.assertEqual(topic, f"smartharness/ecu/{event['ecu'].lower()}/faults")

    def test_broker_restart_flushes_offline_event(self):
        self.stop_broker()
        deadline = time.monotonic() + 5
        while self.publisher.connected.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.publisher.connected.is_set())
        event = dict(ecu="A", circuit=1, fault_code=1, active=True, voltage_mv=0, command_on=True, seq=12)
        info = self.publisher.publish_fault(event, wait=False)
        # Reconnect subscriber first, then allow publisher retry.
        self.subscribed.clear()
        self.start_broker()
        self.assertTrue(self.subscribed.wait(8))
        self.assertTrue(self.publisher.wait_connected(8))
        self.assertTrue(self.publisher.wait_for_delivery(info, 8))
        # Delivery to broker is proved by PUBACK; subscriber race is avoided by publishing another event.
        event["seq"] = 13
        self.publisher.publish_fault(event)
        received = self.collect_faults(1)
        self.assertIn(received[0][1]["seq"], (12, 13))

    def test_gateway_status_online_then_graceful_offline(self):
        def next_status():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    topic, payload = self.messages.get(timeout=0.2)
                except queue.Empty:
                    continue
                if topic.endswith("/status"):
                    return payload
            self.fail("Gateway status not received")
        self.assertEqual(next_status(), {"status": "online"})
        # A new subscriber must immediately receive the retained online status.
        retained = queue.Queue()
        probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        probe.on_connect = lambda c, u, f, r, p: c.subscribe("smartharness/gateway/status", qos=1)
        probe.on_message = lambda c, u, m: retained.put((m.retain, json.loads(m.payload)))
        probe.connect("127.0.0.1", self.port)
        probe.loop_start()
        try:
            self.assertEqual(retained.get(timeout=5), (True, {"status": "online"}))
        finally:
            probe.disconnect()
            probe.loop_stop()
        self.publisher.disconnect()
        self.assertEqual(next_status(), {"status": "offline"})
