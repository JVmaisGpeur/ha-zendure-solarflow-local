"""Lance tous les tests : python3 tests/run_all.py"""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
failed = []
for name in ("test_dispatch.py", "test_discovery.py", "test_translations.py", "test_contract.py", "test_scenarios.py", "test_provenance.py", "test_card_help.py", "test_aucune_donnee_personnelle.py"):
    print(f"\n=== {name} ===", flush=True)
    if subprocess.run([sys.executable, str(HERE / name)], cwd=HERE).returncode:
        failed.append(name)
print("\nÉCHECS : " + ", ".join(failed) if failed else "\nTOUS LES TESTS SONT OK")
sys.exit(1 if failed else 0)
