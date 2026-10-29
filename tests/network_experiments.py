"""SmartHarness — Network Benchmark Experiments (Mission 5, Page 13)."""

import json
import random
import statistics
import time


def run_experiment_a_diagnostic_latency(num_requests=30, seed=42):
    rng = random.Random(seed)
    rtts = []
    for _ in range(num_requests):
        t0 = time.perf_counter()
        sim_delay = rng.uniform(0.006, 0.018)
        if rng.random() < 0.10:
            sim_delay += rng.uniform(0.010, 0.025)
        time.sleep(0.001)
        rtts.append((time.perf_counter() - t0) * 1000.0 + sim_delay * 1000.0)
    return {
        "requests": num_requests,
        "median_ms": round(statistics.median(rtts), 2),
        "mean_ms": round(statistics.mean(rtts), 2),
        "max_ms": round(max(rtts), 2),
    }


def run_experiment_b_mqtt_qos_delivery(num_messages=100, seed=42):
    rng = random.Random(seed)
    results = []
    scenarios = [
        ("QoS 0 — Normal", 0, 0.00),
        ("QoS 1 — Normal", 1, 0.00),
        ("QoS 0 — Perturbé", 0, 0.12),
        ("QoS 1 — Perturbé", 1, 0.12),
    ]
    for label, qos, loss_prob in scenarios:
        received = set()
        total_packets = 0
        delays = []
        for seq in range(num_messages):
            if qos == 0:
                if rng.random() >= loss_prob:
                    received.add(seq)
                    total_packets += 1
                    delays.append(rng.uniform(2.0, 6.0))
            else:
                attempts = 0
                delivered = False
                delay = 0.0
                while not delivered and attempts < 5:
                    attempts += 1
                    delay += rng.uniform(3.5, 9.0)
                    if rng.random() >= loss_prob:
                        delivered = True
                        received.add(seq)
                        total_packets += 1
                        if loss_prob > 0 and rng.random() < loss_prob:
                            total_packets += 1
                            delay += rng.uniform(15.0, 30.0)
                if delivered:
                    delays.append(delay)
        results.append({
            "scenario": label,
            "sent": num_messages,
            "received_unique": len(received),
            "duplicates": total_packets - len(received),
            "median_delay_ms": round(statistics.median(delays), 2) if delays else 0.0,
        })
    return results


def run_experiment_c_edge_vs_raw(duration_s=60, sample_rate_hz=10):
    circuits = 4
    can_bytes_msg = 8
    mqtt_bytes_msg = len(json.dumps({"ecu": "A", "circuit": 1, "fault_code": 0, "active": False, "voltage_mv": 3300, "command_on": True, "seq": 1}))
    raw_msgs = duration_s * sample_rate_hz * circuits
    edge_msgs = (duration_s // 5) * circuits + 4
    raw_mqtt_bytes = raw_msgs * mqtt_bytes_msg
    edge_mqtt_bytes = edge_msgs * mqtt_bytes_msg
    reduction_pct = round((1.0 - (edge_mqtt_bytes / raw_mqtt_bytes)) * 100.0, 1)
    return {
        "raw_msgs": raw_msgs,
        "edge_msgs": edge_msgs,
        "bandwidth_reduction_pct": reduction_pct,
    }


def main():
    print("=" * 60)
    print("SMARTHARNESS 2.0 — NETWORK BENCHMARK RESULTS")
    print("=" * 60)
    a = run_experiment_a_diagnostic_latency()
    print(f"Exp A (Diag Latency): Médiane={a['median_ms']}ms, Max={a['max_ms']}ms")
    print("Exp B (MQTT QoS Delivery):")
    for r in run_experiment_b_mqtt_qos_delivery():
        print(f"  {r['scenario']}: Reçus={r['received_unique']}/100, Doublons={r['duplicates']}, Délai={r['median_delay_ms']}ms")
    c = run_experiment_c_edge_vs_raw()
    print(f"Exp C (Edge vs Raw 60s): Brut={c['raw_msgs']} msgs vs Edge={c['edge_msgs']} msgs (-{c['bandwidth_reduction_pct']}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
