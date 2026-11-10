"""Run from the repository root with the Gateway Python environment and dashboard/npm dependencies.

python -m tests.audit_mqtt_outage [--crash saved|early]
Set MOSQUITTO_BIN when Mosquitto is outside PATH. Evidence is kept in the OS temp directory.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack, closing
from datetime import datetime, timezone

import can
from gateway.can_mqtt_bridge import forward
from gateway.mqtt_publisher import MQTTPublisher
from simulator.can_protocol import encode_fault
from simulator.circuit import Circuit
from simulator.ecu import ECU

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
FAULT = "smartharness/ecu/a/faults"


def until(fn, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if result := fn():
            return result
        time.sleep(.05)
    raise TimeoutError(fn)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Trace:
    def __init__(self, path):
        self.rows = []
        self.lock = threading.Lock()
        self.path = path

    def add(self, stage, **data):
        with self.lock:
            row = dict(utc=datetime.now(timezone.utc).isoformat(), stage=stage, **data)
            self.rows.append(row)
            with self.path.open("a", encoding="utf-8") as f:
                print(json.dumps(row), file=f)

    def has(self, stage, **data):
        with self.lock:
            return any(row["stage"] == stage and data.items() <= row.items() for row in self.rows)


def packet(stream):
    header = stream.read(1)
    if not header:
        raise EOFError()
    size = 0
    prefix = bytearray(header)
    for shift in (0, 7, 14, 21):
        digit = stream.read(1)
        if not digit:
            raise EOFError()
        prefix.extend(digit)
        size |= (digit[0] & 127) << shift
        if digit[0] < 128:
            break
    else:
        raise ValueError("MQTT remaining length")
    body = stream.read(size)
    if len(body) != size:
        raise EOFError()
    return bytes(prefix), body


def observe(trace, stage, flags, body):
    kind = flags >> 4
    num = lambda offset: int.from_bytes(body[offset:offset+2], "big")
    if kind == 1:
        # MQTT 3.1.1 CONNECT: identifier follows the ten-byte variable header.
        trace.add(stage+".CONNECT", clean=bool(body[7] & 2), client=body[12:12+num(10)].decode())
    elif kind == 2:
        trace.add(stage+".CONNACK", session_present=bool(body[0] & 1), rc=body[1])
    elif kind in (4, 8, 9):
        tag = {4: "PUBACK", 8: "SUBSCRIBE", 9: "SUBACK"}[kind]
        fields = {"mid": num(0)}
        if kind == 8:
            offset = 2
            topics = {}
            while offset < len(body):
                end = offset+2+num(offset)
                topics[body[offset+2:end].decode()] = body[end]
                offset = end+1
            fields["topics"] = topics
        if kind == 9:
            fields["grants"] = list(body[2:])
        trace.add(stage+"."+tag, **fields)
    elif kind == 3:
        end = 2+num(0)
        qos = (flags >> 1) & 3
        topic = body[2:end].decode()
        if topic == FAULT:
            event = json.loads(body[end+(2 if qos else 0):])
            trace.add(stage+".PUBLISH", topic=topic, mid=num(end) if qos else None, seq=event["seq"])


class Relay(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, role, port, trace):
        self.enabled = threading.Event()
        self.enabled.set()

        class Handler(socketserver.BaseRequestHandler):
            def handle(handler):
                if not self.enabled.is_set():
                    return
                try:
                    upstream = socket.create_connection(("127.0.0.1", port), 1)
                except OSError:
                    return
                with upstream:
                    upstream.settimeout(None)
                    def pump(source, target, direction):
                        try:
                            with source.makefile("rb") as f:
                                while True:
                                    prefix, body = packet(f)
                                    observe(trace, role+"."+direction, prefix[0], body)
                                    target.sendall(prefix+body)
                        except (EOFError, OSError):
                            pass
                        finally:
                            for sock in (source, target):
                                try:
                                    sock.shutdown(socket.SHUT_RDWR)
                                except OSError:
                                    pass
                    back = threading.Thread(target=pump, args=(upstream, handler.request, "in"), daemon=True)
                    back.start()
                    pump(handler.request, upstream, "out")
                    back.join()
        super().__init__(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def close(self):
        self.shutdown()
        self.server_close()


def stop(p):
    if p.poll() is None:
        p.kill()
        p.wait(10)


def shutdown_broker(p, crash):
    if crash:
        stop(p)
    elif os.name == "nt":
        # This child attaches only to the isolated console created for this broker.
        helper = """import ctypes,sys,time
k=ctypes.windll.kernel32
k.FreeConsole()
assert k.AttachConsole(int(sys.argv[1]))
assert k.SetConsoleCtrlHandler(None, True)
assert k.GenerateConsoleCtrlEvent(0,0)
time.sleep(.25)
"""
        subprocess.run([sys.executable, "-c", helper, str(p.pid)], check=True)
    else:
        p.terminate()
    p.wait(10)
    if not crash and p.returncode != 0:
        raise RuntimeError(f"broker shutdown: {p.returncode}")


def subscription_ready(trace, since):
    with trace.lock:
        rows = trace.rows[since:]
        # A resumed MQTT session needs no new SUBSCRIBE or SUBACK.
        if any(r["stage"] == "red.in.CONNACK" and r["session_present"] for r in rows):
            return True
        for request in rows:
            if request["stage"] == "red.out.SUBSCRIBE" and FAULT in request["topics"]:
                index = list(request["topics"]).index(FAULT)
                if any(r["stage"] == "red.in.SUBACK" and r["mid"] == request["mid"]
                       and r["grants"][index] == 1 for r in rows):
                    return True
        return False


def scenario(first, crash, source, check_instances=False):
    folder = Path(tempfile.mkdtemp(prefix="smartharness-outage-"))
    trace = Trace(folder/"trace.jsonl")
    mp, hp = free_port(), free_port()
    assert mp != hp and not {mp, hp} & {1880, 1881, 1883}
    db = folder/"events.sqlite"
    print(first, folder, flush=True)
    with ExitStack() as stack:
        gw, red = [Relay(role, mp, trace) for role in ("gw", "red")]
        for relay in (gw, red):
            stack.callback(relay.close)
        # Exercise both documented launch directories on every run.
        dashboard_launcher = first == "gateway"
        base = source if dashboard_launcher else source.parent/"broker"
        config = (base/"mosquitto.conf").read_text(encoding="utf-8")
        broker_data = folder/"broker"
        broker_data.mkdir()
        broker_cwd = folder/"dashboard" if dashboard_launcher else folder
        broker_cwd.mkdir(exist_ok=True)
        expected_listener = "listener 1883 127.0.0.1"
        if config.splitlines().count(expected_listener) != 1:
            raise ValueError("Expected one local test listener")
        config = config.replace(expected_listener, f"listener {mp} 127.0.0.1")
        (folder/"broker.conf").write_text(config, encoding="utf-8")
        exe = os.getenv("MOSQUITTO_BIN") or shutil.which("mosquitto") or "C:/Program Files/Mosquitto/mosquitto.exe"
        def broker():
            options = {}
            if os.name == "nt":
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                options.update(creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)
            log = stack.enter_context((folder/"broker.log").open("ab"))
            p = subprocess.Popen([exe, "-v", "-c", str(folder/"broker.conf")], cwd=broker_cwd,
                                 stdout=log, stderr=subprocess.STDOUT, **options)
            stack.callback(stop, p)
            trace.add("broker.start", pid=p.pid)
            return p
        b = broker()
        flows = json.loads((source/"flows.json").read_text(encoding="utf-8"))
        for node in flows:
            if node["id"] in ("validate", "stored"):
                expr = "JSON.parse(msg.payload)" if node["id"] == "validate" else "msg.event"
                node["func"] = f"node.warn('AUDIT {node['id']} '+{expr}.seq+' '+Date.now());\n"+node["func"]
        (folder/"flows.json").write_text(json.dumps(flows),encoding="utf-8")
        (folder/"settings.cjs").write_text("module.exports={...require("+json.dumps(str(DASH/"settings.js"))+"),flowFile:"+json.dumps(str(folder/"flows.json"))+"};")
        env = dict(os.environ, MQTT_HOST="127.0.0.1", MQTT_PORT=str(red.server_address[1]),
                   PORT=str(hp), SH_DB_PATH=str(db), SH_RUNTIME_DIR=str(folder/"runtime"))
        nr = subprocess.Popen([shutil.which("node"),str(DASH/"node_modules/node-red/red.js"),"--settings",
                               str(folder/"settings.cjs")],env=env,stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace")
        stack.callback(stop,nr)
        def logs():
            with (folder/"node.log").open("w",encoding="utf-8") as out:
                for line in nr.stdout:
                    out.write(line)
                    if "AUDIT " in line:
                        label, seq, stamp = line.split("AUDIT ")[1].split()
                        trace.add("node."+label, seq=int(seq), node_epoch_ms=int(stamp))
        threading.Thread(target=logs,daemon=True).start()
        until(lambda: subscription_ready(trace, 0))
        peer_db = folder/"peer.sqlite"
        if check_instances:
            peer = Relay("peer", mp, trace)
            stack.callback(peer.close)
            peer_port = free_port()
            assert peer_port not in (hp, mp, 1880, 1881, 1883)
            peer_env = dict(env, PORT=str(peer_port), MQTT_PORT=str(peer.server_address[1]),
                            SH_RUNTIME_DIR=str(folder/"peer-runtime"), SH_DB_PATH=str(peer_db))
            def start_peer():
                proc = subprocess.Popen([shutil.which("node"), str(DASH/"scripts/start.js")],
                                        env=peer_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                stack.callback(stop, proc)
                return proc
            peer_proc = start_peer()
            until(lambda: trace.has("peer.in.SUBACK"))
            peer_id = next(r["client"] for r in trace.rows if r["stage"] == "peer.out.CONNECT")
            main_id = next(r["client"] for r in trace.rows if r["stage"] == "red.out.CONNECT")
            assert peer_id and main_id and peer_id != main_id
            stop(peer_proc)
            start_peer()
            until(lambda: trace.has("peer.in.CONNACK", session_present=True))
            assert {r["client"] for r in trace.rows if r["stage"] == "peer.out.CONNECT"} == {peer_id}
        p = MQTTPublisher("127.0.0.1",gw.server_address[1])
        receipts = {}
        original = p.publish_fault
        def logged(event, wait=True):
            info = original(event,wait)
            receipts[event["seq"]] = info
            trace.add("gateway.enqueue",seq=event["seq"],mid=info.mid,rc=int(info.rc))
            return info
        p.publish_fault = logged
        p.connect()
        stack.callback(p.disconnect)
        assert p.wait_connected()
        c = Circuit(1,"Headlights")
        c.command_on = True
        ecu = ECU("A",[c])
        ecu.sequence = 65534
        tx, rx = [stack.enter_context(can.Bus(interface="virtual",channel="outage")) for _ in range(2)]
        def emit(connected):
            c.connected = connected
            event, = ecu.scan()
            trace.add("ecu.create",seq=event["seq"])
            tx.send(encode_fault(event))
            frame = rx.recv(1)
            assert frame and forward(frame,p)
            return frame
        def rows(database=db):
            if not database.is_file():
                return []
            with closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fault_events'").fetchone():
                    return []
                return [x[0] for x in conn.execute("select seq from fault_events order by event_id")]
        emit(False)
        until(lambda:trace.has("node.stored",seq=65535))
        emit(True)
        until(lambda:trace.has("node.stored",seq=0))
        if check_instances:
            until(lambda: rows(peer_db) == [65535, 0])
            assert rows() == [65535, 0]
            print("Two live Dashboards: distinct IDs, stable after restart, same two events in both databases.")
        if crash == "saved" and "persistence true" in config:
            # Ensure the subscription has actually been checkpointed before this crash.
            until(lambda:any(f.stat().st_size for f in broker_data.glob("*.db")),timeout=75)
        if crash == "early" and any(broker_data.glob("*.db")):
            raise RuntimeError("Checkpoint already exists; early-crash precondition failed")
        gw.enabled.clear()
        red.enabled.clear()
        shutdown_broker(b,crash != "graceful")
        until(lambda:not p.connected.is_set())
        trace.add("broker.down",crash=crash)
        emit(False)
        mid=next(row["mid"] for row in trace.rows if row["stage"]=="gateway.enqueue" and row["seq"]==1)
        before = len(trace.rows)
        b = broker()
        if first=="gateway":
            gw.enabled.set()
            until(lambda:trace.has("gw.in.PUBACK",mid=mid))
            red.enabled.set()
        else:
            red.enabled.set()
            until(lambda:subscription_ready(trace, before))
            gw.enabled.set()
        until(lambda:p.connected.is_set() and subscription_ready(trace, before))
        until(lambda:trace.has("gw.in.PUBACK",mid=mid))
        assert p.wait_for_delivery(receipts[1]), "Gateway PUBACK callback missing"
        repeat = emit(True)
        until(lambda:trace.has("node.stored",seq=2))
        assert forward(repeat,p)
        until(lambda:rows().count(2)==2)
        actual=rows()
        trace.add("sqlite.read",sequences=actual)
        print("SQLite",actual,flush=True)
        return actual==[65535,0,1,2,2]


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crash", choices=("saved","early"), default="graceful",
                        help="Kill the broker after its first checkpoint, or before it.")
    parser.add_argument("--dashboard", type=Path, default=DASH,
                        help="Read broker config and flows from another revision for comparison")
    parser.add_argument("--instances", action="store_true", help="Also run a second real Dashboard on the same test broker")
    opts=parser.parse_args()
    results=[scenario(first, opts.crash, opts.dashboard.resolve(), opts.instances and first=="gateway") for first in ("gateway","node-red")]
    print("Gateway first / Node-RED first:",results)
    sys.exit(0 if all(results) else 1)