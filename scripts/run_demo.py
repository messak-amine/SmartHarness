"""
SmartHarness 2.0 — Démonstration et validation Python (Mission 5)
Emplacement dans le dépôt : scripts/run_demo.py
Exécution sur n'importe quel PC :
    python scripts/run_demo.py
"""

from pathlib import Path
import re
import subprocess
import sys
import time


def print_banner(title: str) -> None:
    print("\n" + "=" * 76)
    print(f"  {title.upper()}")
    print("=" * 76)


def run_step(desc: str, cmd: list[str], cwd: Path) -> str:
    print(f"\n[*] Étape : {desc}")
    print(f"    Commande : {' '.join(cmd)}")
    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if res.returncode != 0:
        print(f"[-] Échec ({dt:.2f}s)")
        print(res.stderr or res.stdout)
        return "FAILED"

    # unittest writes its result summary to stderr even on a successful exit.
    skipped = re.search(r"^OK \([^\n)]*\bskipped=(\d+)", res.stderr, re.MULTILINE)
    if skipped:
        print(f"[!] Validation incomplète : {skipped.group(1)} tests ignorés ({dt:.2f}s)")
        for line in res.stderr.splitlines():
            if " ... skipped " in line:
                print(f"    | {line}")
        return "INCOMPLETE"

    print(f"[+] Succès ({dt:.2f}s)")
    for line in res.stdout.strip().splitlines()[-6:]:
        print(f"    | {line}")
    return "PASSED"


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / "tests").is_dir():
        repo_root = Path.cwd()

    print_banner("SmartHarness 2.0 — Démonstration & Validation Python (Mission 5)")
    print("Périmètre : CAN virtuel, Gateway Python et tests MQTT")
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
    for desc, status in results:
        print(f"  - {desc:<62} : {status}")

    print("-" * 76)
    statuses = {status for _, status in results}
    if "FAILED" in statuses:
        print("  Échec de la validation Python. Vérifiez les logs ci-dessus.")
        return 1
    if "INCOMPLETE" in statuses:
        print("  Validation Python incomplète. Vérifiez les tests ignorés ci-dessus.")
        return 2
    print("  Validation Python réussie. Le pipeline Node-RED est testé séparément.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
