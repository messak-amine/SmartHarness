"""QoS 1 publisher with bounded in-memory buffering and automatic reconnect."""
import json
import logging
import os
import threading
from collections import deque
import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)
STATUS_TOPIC = "smartharness/gateway/status"


class MQTTPublisher:
    def __init__(self, host=None, port=None, client=None, timeout=5):
        self.host = host or os.getenv("MQTT_HOST", "localhost")
        self.port = int(port or os.getenv("MQTT_PORT", "1883"))
        self.timeout = timeout
        self.connected = threading.Event()
        self._acks = deque(maxlen=512)
        self._ack_condition = threading.Condition()
        self.client = client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish
        self.client.reconnect_delay_set(1, 30)
        self.client.max_queued_messages_set(256)
        self.client.will_set(STATUS_TOPIC, '{"status":"offline"}', qos=1, retain=True)
        if os.getenv("MQTT_USERNAME"):
            self.client.username_pw_set(os.environ["MQTT_USERNAME"], os.getenv("MQTT_PASSWORD"))
        if os.getenv("MQTT_CA"):
            self.client.tls_set(ca_certs=os.environ["MQTT_CA"])

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            LOG.error("Broker refused connection: %s", reason_code)
            return
        self.connected.set()
        client.publish(STATUS_TOPIC, '{"status":"online"}', qos=1, retain=True)
        LOG.info("MQTT connected")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        if reason_code != 0:
            LOG.warning("MQTT disconnected: %s; automatic retry enabled", reason_code)

    def connect(self):
        self.client.connect_async(self.host, self.port, 60)
        self.client.loop_start()

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        if reason_code != 0:
            return
        with self._ack_condition:
            self._acks.append(mid)
            self._ack_condition.notify_all()

    def wait_for_delivery(self, info, timeout=None):
        # Offline Paho message infos keep NO_CONN even after a later PUBACK.
        with self._ack_condition:
            return self._ack_condition.wait_for(
                lambda: info.mid in self._acks,
                timeout=self.timeout if timeout is None else timeout)

    def wait_connected(self, timeout=None):
        return self.connected.wait(self.timeout if timeout is None else timeout)

    def publish_fault(self, diagnostic, wait=True):
        ecu = diagnostic["ecu"]
        if ecu not in ("A", "B"):
            raise ValueError("Invalid ECU")
        result = self.client.publish(
            f"smartharness/ecu/{ecu.lower()}/faults",
            json.dumps(diagnostic, separators=(",", ":")), qos=1, retain=False)
        # Paho queues QoS 1 messages even while disconnected.
        if result.rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
            raise RuntimeError(f"MQTT queue rejected event: {result.rc}")
        if wait:
            if not self.wait_connected():
                raise TimeoutError("MQTT unavailable; event remains queued in memory")
            if not self.wait_for_delivery(result):
                raise TimeoutError("PUBACK timeout; delivery uncertain, event may be retried")
        return result

    def disconnect(self):
        try:
            if self.connected.is_set():
                result = self.client.publish(STATUS_TOPIC, '{"status":"offline"}', qos=1, retain=True)
                self.wait_for_delivery(result)
        finally:
            self.client.disconnect()
            self.client.loop_stop()
            self.connected.clear()
