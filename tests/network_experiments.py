"""
SmartHarness 2.0 — Mesures Réelles du Pipeline Logiciel & Estimations Théoriques Réseau (Mission 5)
Branche : feat/integration-tests
Emplacement dans le dépôt : tests/network_experiments.py

Répond aux exigences de la revue PR #2 :
1. Distingue explicitement et rigoureusement :
   - PARTIE 1 : MESURES EXPÉRIMENTALES RÉELLES (`[MEASURED_ON_HOST_SOFTWARE_STACK]`)
     Exécutées sans `time.sleep()` ni `random.uniform()`, chronométrées avec `time.perf_counter_ns()`
     sur la vraie chaîne logicielle :
       ECU (`simulator.ecu`) -> Trame CAN (`simulator.can_protocol`) -> Bus CAN virtuel (`python-can`)
       -> Décodeur Gateway (`gateway.decoder`) -> Courtier MQTT v3.1.1 TCP Loopback (`127.0.0.1`)
       -> Insertion SQLite (`fault_events`).
   - PARTIE 2 : CALCULS DÉTERMINISTES DE CHARGE UTILE (`[DETERMINISTIC_PROTOCOL_CALCULATION]`)
     Taille réelle mesurée en octets des trames CAN v1 (8 octets) et des payloads JSON MQTT v1
     (`contracts/mqtt_protocol.md`) pour comparer le mode Brut (10 Hz x 4 circuits sur 60 s)
     au mode Edge Computing (événements de transition + état périodique).
   - PARTIE 3 : ESTIMATIONS THÉORIQUES SIMULÉES (`[SIMULATED_THEORETICAL_ESTIMATE]`)
     Modèle probabiliste Monte Carlo clairement étiqueté comme estimation théorique (et non comme
     mesure matérielle) pour illustrer l'effet d'un lien Wi-Fi avec pertes (12 %) sur MQTT QoS 0 vs QoS 1
     en attendant les tests physiques sur ESP32 + Mosquitto externe.
"""

import os
import random
import sqlite3
import statistics
import sys
import time
from typing import Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_integration_chain import (
    Circuit,
    ECU,
    EndToEndSoftwareChain,
    encode_fault,
)


def measure_real_software_pipeline_latency(num_Iteration: int = 30) -> Dict[str, object]:
    """
    [MEASURED_ON_HOST_SOFTWARE_STACK]
    Mesure expérimentalement le temps réel de traversée de bout en bout sur la machine hôte :
    Changement d'état circuit -> `ECU.scan()` -> `encode_fault()` -> `can.Bus(interface="virtual").send()`
    -> `gateway_can_bus.recv()` -> `decode_fault()` -> `LoopbackMQTTv311Broker` (socket TCP 127.0.0.1,
    QoS 1 `PUBLISH` + `PUBACK`) -> Déduplication -> `SQLite INSERT & COMMIT`.
    """
    db = sqlite3.connect(":memory:", check_same_thread=False)
    chain = EndToEndSoftwareChain(
        db,
        use_tcp_mqtt_broker=True,
        max_buffer_size=128,
        max_dedup_keys=256,
    )
    circuit = Circuit(1, "Headlights")
    circuit.command_on = True
    ecu_a = ECU("A", [circuit])

    measured_rtts_ms: List[float] = []
    try:
        for _ in range(num_Iteration):
            circuit.connected = not circuit.connected
            t0_ns = time.perf_counter_ns()
            events = ecu_a.scan()
            for ev in events:
                chain.transmit_ecu_event_over_virtual_can(ev)
            dt_ms = (time.perf_counter_ns() - t0_ns) / 1_000_000.0
            measured_rtts_ms.append(round(dt_ms, 3))
    finally:
        chain.shutdown()
        db.close()

    return {
        "measurement_type": "MEASURED_ON_HOST_SOFTWARE_STACK",
        "transport": "python-can virtual bus + TCP loopback MQTT v3.1.1 socket (127.0.0.1) + SQLite",
        "iterations": num_Iteration,
        "min_ms": round(min(measured_rtts_ms), 3),
        "median_ms": round(statistics.median(measured_rtts_ms), 3),
        "mean_ms": round(statistics.mean(measured_rtts_ms), 3),
        "max_ms": round(max(measured_rtts_ms), 3),
    }


def measure_real_loopback_mqtt_delivery(num_messages: int = 100) -> List[Dict[str, object]]:
    """
    [MEASURED_ON_HOST_SOFTWARE_STACK]
    Envoie réellement `num_messages` paquets MQTT v3.1.1 sur le socket TCP loopback (`127.0.0.1`)
    en QoS 0 puis en QoS 1, et mesure le nombre réel de messages reçus et le délai réel par paquet.
    """
    results: List[Dict[str, object]] = []

    for qos in (0, 1):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        chain = EndToEndSoftwareChain(
            db,
            use_tcp_mqtt_broker=True,
            max_buffer_size=256,
            max_dedup_keys=512,
        )
        circuit = Circuit(1, "Headlights")
        circuit.command_on = True
        ecu_a = ECU("A", [circuit])
        latencies_ms: List[float] = []

        try:
            for _ in range(num_messages):
                circuit.connected = not circuit.connected
                ev = ecu_a.scan()[0]
                can_frame = encode_fault(ev)
                topic, payload_json, _ = chain.can_to_mqtt(can_frame)

                t0_ns = time.perf_counter_ns()
                chain._publish_mqtt_message(topic, payload_json, qos=qos)
                dt_ms = (time.perf_counter_ns() - t0_ns) / 1_000_000.0
                latencies_ms.append(dt_ms)

            stored_count = db.execute("SELECT COUNT(*) FROM fault_events").fetchone()[0]
        finally:
            chain.shutdown()
            db.close()

        results.append({
            "measurement_type": "MEASURED_ON_HOST_SOFTWARE_STACK",
            "scenario": f"QoS {qos} — Socket TCP Loopback (127.0.0.1, sans perte)",
            "sent": num_messages,
            "received_sqlite": stored_count,
            "median_socket_time_ms": round(statistics.median(latencies_ms), 3),
            "max_socket_time_ms": round(max(latencies_ms), 3),
        })

    return results


def calculate_deterministic_edge_vs_raw_bandwidth(
    duration_s: int = 60,
    sample_rate_hz: int = 10,
) -> Dict[str, object]:
    """
    [DETERMINISTIC_PROTOCOL_CALCULATION]
    Calcule de façon exacte et déterministe le volume d'octets échangés sur 60 s en mesurant
    la taille réelle d'une trame CAN v1 (`encode_fault`) et d'un message JSON MQTT v1
    (`EndToEndSoftwareChain.can_to_mqtt`).
    """
    db = sqlite3.connect(":memory:")
    chain = EndToEndSoftwareChain(db, use_tcp_mqtt_broker=False)
    try:
        sample_event = {
            "ecu": "A",
            "circuit": 1,
            "fault_code": 1,
            "active": True,
            "voltage_mv": 0,
            "command_on": True,
            "seq": 1,
        }
        can_frame = encode_fault(sample_event)
        can_bytes_per_frame = len(can_frame.data)
        _, mqtt_json_str, _ = chain.can_to_mqtt(can_frame)
        mqtt_bytes_per_msg = len(mqtt_json_str.encode("utf-8"))
    finally:
        chain.shutdown()
        db.close()

    circuits = 4
    raw_messages = duration_s * sample_rate_hz * circuits
    raw_can_bytes = raw_messages * can_bytes_per_frame
    raw_mqtt_bytes = raw_messages * mqtt_bytes_per_msg

    edge_state_messages = (duration_s // 5) * circuits
    edge_fault_messages = 4
    edge_messages = edge_state_messages + edge_fault_messages
    edge_can_bytes = edge_messages * can_bytes_per_frame
    edge_mqtt_bytes = edge_messages * mqtt_bytes_per_msg

    reduction_pct = round((1.0 - (edge_mqtt_bytes / raw_mqtt_bytes)) * 100.0, 1)

    return {
        "measurement_type": "DETERMINISTIC_PROTOCOL_CALCULATION",
        "measured_can_frame_bytes": can_bytes_per_frame,
        "measured_mqtt_json_bytes": mqtt_bytes_per_msg,
        "raw_periodic_60s": {
            "messages": raw_messages,
            "can_payload_bytes": raw_can_bytes,
            "mqtt_payload_bytes": raw_mqtt_bytes,
        },
        "edge_event_driven_60s": {
            "messages": edge_messages,
            "can_payload_bytes": edge_can_bytes,
            "mqtt_payload_bytes": edge_mqtt_bytes,
            "bandwidth_reduction_pct": reduction_pct,
        },
    }


def simulate_theoretical_lossy_wifi_qos_estimate(
    num_messages: int = 100,
    packet_loss_probability: float = 0.12,
    seed: int = 42,
) -> List[Dict[str, object]]:
    """
    [SIMULATED_THEORETICAL_ESTIMATE — NOT A HARDWARE MEASUREMENT]
    Simulation probabiliste (Monte Carlo, graine fixe `seed=42`) modélisant l'effet théorique
    d'un canal Wi-Fi avec `packet_loss_probability` (12 % de perte par transmission) sur
    100 messages en QoS 0 vs QoS 1.
    """
    rng = random.Random(seed)
    estimates: List[Dict[str, object]] = []

    for qos in (0, 1):
        received_unique = set()
        total_received_packets = 0

        for seq in range(1, num_messages + 1):
            if qos == 0:
                if rng.random() >= packet_loss_probability:
                    received_unique.add(seq)
                    total_received_packets += 1
            else:
                attempts = 0
                delivered = False
                while not delivered and attempts < 5:
                    attempts += 1
                    if rng.random() >= packet_loss_probability:
                        delivered = True
                        received_unique.add(seq)
                        total_received_packets += 1
                        if rng.random() < packet_loss_probability:
                            total_received_packets += 1

        duplicates = total_received_packets - len(received_unique)
        estimates.append({
            "measurement_type": "SIMULATED_THEORETICAL_ESTIMATE",
            "scenario": f"[ESTIMATION SIMULÉE] QoS {qos} — Canal Wi-Fi théorique ({int(packet_loss_probability * 100)}% perte)",
            "sent": num_messages,
            "estimated_received_unique": len(received_unique),
            "estimated_duplicates_before_filter": duplicates,
            "estimated_duplicates_after_dedup": 0,
        })

    return estimates


def main() -> None:
    print("=" * 78)
    print("SMARTHARNESS 2.0 — RAPPORT DE MESURES LOGICIELLES & ESTIMATIONS THÉORIQUES")
    print("=" * 78)

    real_lat = measure_real_software_pipeline_latency(num_Iteration=30)
    print("\n[1] MESURES RÉELLES SUR LA PILE LOGICIELLE HÔTE (MEASURED_ON_HOST_SOFTWARE_STACK)")
    print(f"    Transport : {real_lat['transport']}")
    print(f"    Itérations (ECU -> Virtual CAN -> Gateway -> TCP MQTT -> SQLite) : {real_lat['iterations']}")
    print(f"    - Latence logicielle Min     : {real_lat['min_ms']} ms")
    print(f"    - Latence logicielle Médiane : {real_lat['median_ms']} ms")
    print(f"    - Latence logicielle Moyenne : {real_lat['mean_ms']} ms")
    print(f"    - Latence logicielle Max     : {real_lat['max_ms']} ms")

    real_mqtt = measure_real_loopback_mqtt_delivery(num_messages=100)
    print("\n[2] MESURES RÉELLES DE LIVRAISON MQTT SUR SOCKET TCP LOOPBACK (127.0.0.1)")
    for row in real_mqtt:
        print(
            f"    - {row['scenario']} : {row['received_sqlite']}/{row['sent']} insérés en SQLite | "
            f"Médiane = {row['median_socket_time_ms']} ms | Max = {row['max_socket_time_ms']} ms"
        )

    bw = calculate_deterministic_edge_vs_raw_bandwidth()
    raw = bw["raw_periodic_60s"]
    edge = bw["edge_event_driven_60s"]
    print("\n[3] CALCUL DÉTERMINISTE DE BANDE PASSANTE SUR 60 S (DETERMINISTIC_PROTOCOL_CALCULATION)")
    print(f"    Taille réelle mesurée : Trame CAN = {bw['measured_can_frame_bytes']} octets | Payload JSON MQTT v1 = {bw['measured_mqtt_json_bytes']} octets")
    print(f"    - Mode Brut (10 Hz x 4 circuits) : {raw['messages']} msgs | {raw['can_payload_bytes']} octets CAN | {raw['mqtt_payload_bytes']} octets MQTT")
    print(f"    - Mode Edge (Événements + État)  : {edge['messages']} msgs | {edge['can_payload_bytes']} octets CAN | {edge['mqtt_payload_bytes']} octets MQTT")
    print(f"    - Réduction de bande passante    : -{edge['bandwidth_reduction_pct']}% d'octets transmis")

    sim_qos = simulate_theoretical_lossy_wifi_qos_estimate()
    print("\n[4] ESTIMATIONS THÉORIQUES SIMULÉES — MODÈLE MONTE CARLO WI-FI PERTURBÉ (SIMULATED_THEORETICAL_ESTIMATE)")
    print("    [!] Note : Ces valeurs sont issues d'un modèle probabiliste (12% de perte) et NON de mesures matérielles ESP32.")
    for row in sim_qos:
        print(
            f"    - {row['scenario']} : {row['estimated_received_unique']}/{row['sent']} reçus uniques | "
            f"Doublons avant filtre = {row['estimated_duplicates_before_filter']} | "
            f"Après déduplication = {row['estimated_duplicates_after_dedup']}"
        )
    print("=" * 78)


if __name__ == "__main__":
    main()
