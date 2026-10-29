"""CAN listener. Virtual CAN peers must live in this same process."""
import argparse
import logging
import can
from gateway.decoder import decode_fault
from gateway.mqtt_publisher import MQTTPublisher

LOG = logging.getLogger(__name__)


def forward(message, publisher):
    try:
        diagnostic = decode_fault(message)
    except ValueError as error:
        LOG.warning("Rejected CAN frame: %s", error)
        return False
    publisher.publish_fault(diagnostic, wait=False)
    LOG.info("Forwarded %s", diagnostic)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="virtual")
    parser.add_argument("--channel", default="smartharness")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    publisher = MQTTPublisher(args.host, args.port)
    try:
        publisher.connect()
        with can.Bus(interface=args.interface, channel=args.channel) as bus:
            while True:
                message = bus.recv(0.5)
                if message is not None:
                    try:
                        forward(message, publisher)
                    except RuntimeError:
                        LOG.exception("Event lost: MQTT queue full")
    except KeyboardInterrupt:
        pass
    except can.CanError:
        LOG.exception("CAN interface failed; restart bridge after fixing interface")
        raise
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    main()
