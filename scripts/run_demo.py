"""
SmartHarness 2.0 — Script de Démonstration & Validation Globale Reproductible (Mission 5)
Emplacement dans le dépôt : scripts/run_demo.py
Exécution sur n'importe quel PC :
    python scripts/run_demo.py
"""

from pathlib import Path
import subprocess
import sys
import time


def print_banner(title: str) -> None:
    print("\n" + "=" * 76)
    print(f"  {title.upper()}")
    print("=" * 76)


def run_step(desc: str, cmd: list, cwd: Path) -> bool:
    print(f"\n[*] Étape : {desc}")
    print(f"    Commande : {' '.join(cmd)}")
    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if res.returncode == 0:
        print(f"[+] Succès ({dt:.2f}s)")
        if res.stdout.strip():
            lines = res.stdout.strip().splitlines()
            for line in lines[-6:]:
                print(f"    | {line}")
        return True
    print(f"[-] Échec ({dt:.2f}s) :")
    print(res.stderr or res.stdout)
    return False


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / "tests").is_dir():
        repo_root = Path.cwd()

    print_banner("SmartHarness 2.0 — Démonstration & Validation Complète (Mission 5)")
    print("Chaîne : ECU A/B (CAN 250 kbit/s) -> Gateway -> MQTT (QoS 1) -> Node-RED -> SQLite")
    print(f"Dossier racine : {repo_root}")
    print(f"Python         : {sys.version.split()[0]}")

    steps = [
        (
            "Suite complète de tests unitaires et d'intégration (M1..M5)",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
        (
            "Mesures réelles du pipeline logiciel & Estimations réseau (Mission 5)",
            [sys.executable, "tests/network_experiments.py"],
        ),
    ]

    if (repo_root / "simulator" / "main.py").exists():
        steps.append((
            "Simulation CAN dynamique originale (ECU A/B -> Virtual CAN -> Gateway)",
            [sys.executable, "-m", "simulator.main"],
        ))

    if (repo_root / "simulator" / "demo_validation.py").exists():
        steps.append((
            "Validation étendue de la simulation (4 pannes + 4 reprises sans doublon)",
            [sys.executable, "-m", "simulator.demo_validation"],
        ))

    results = []
    for desc, cmd in steps:
        results.append((desc, run_step(desc, cmd, repo_root)))

    print_banner("Bilan Récapitulatif de la Validation SmartHarness")
    all_ok = True
    for desc, ok in results:
        status = "PASSED [OK]" if ok else "FAILED [KO]"
        print(f"  - {desc:<62} : {status}")
        if not ok:
            all_ok = False

    print("-" * 76)
    if all_ok:
        print("  RÉSULTAT GLOBAL : Système logiciel 100% validé et prêt pour la démonstration.")
        print("-" * 76)
        return 0
    print("  ATTENTION : Au moins une étape a échoué. Vérifiez les logs ci-dessus.")
    print("-" * 76)
    return 1


if __name__ == "__main__":
    sys.exit(main())
