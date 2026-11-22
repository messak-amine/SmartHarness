from gateway.mqtt_publisher import MQTTPublisher

publisher = MQTTPublisher()

diagnostic = {
    "ecu": "A",
    "circuit": 1,
    "fault_code": 1,
    "active": True,
    "voltage_mv": 0,
    "command_on": True,
    "seq": 1
}

try:
    publisher.connect()
    publisher.publish_fault(diagnostic)
finally:
    publisher.disconnect()