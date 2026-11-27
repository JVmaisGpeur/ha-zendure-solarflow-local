"""Aucune donnée personnelle dans ce qui est publié (charte de l'écosystème, règle du 27/11/2026).

Vérifie les fichiers du dépôt et, si l'historique git est présent, l'identité des envois :
- aucune adresse e-mail, sauf les adresses masquées de GitHub et les domaines d'exemple ;
- aucune adresse matérielle (MAC) réelle : seulement la plage d'exemple 02:00:00:xx:xx:xx ;
- aucun nom réseau d'appareil réel (RMS-ESP32-nnnnnnn), seulement 0000001 ;
- envois signés avec une adresse masquée de GitHub.

Se lance avec pytest, ou seul : python tests/test_aucune_donnee_personnelle.py
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
TEXTE = {".py", ".js", ".json", ".md", ".yaml", ".yml", ".txt", ".toml", ".cfg", ".ini", ".html", ".css"}
IGNORES = {".git", "__pycache__", ".pytest_cache", "node_modules"}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_PERMIS = re.compile(r"(@users\.noreply\.github\.com|^noreply@github\.com|@example\.(com|org|net))$", re.I)
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
MAC_PERMISE = re.compile(r"^02[:-]00[:-]00[:-]", re.I)
NOM_ESP = re.compile(r"RMS-ESP32-(\d+)")


def _fichiers():
    for p in RACINE.rglob("*"):
        if p.is_file() and p.suffix.lower() in TEXTE and not (IGNORES & set(p.parts)) and p.name != pathlib.Path(__file__).name:
            yield p


def problemes() -> list[str]:
    out = []
    for p in _fichiers():
        try:
            texte = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        nom = p.relative_to(RACINE).as_posix()
        out += [f"{nom} : adresse e-mail {m}" for m in EMAIL.findall(texte) if not EMAIL_PERMIS.search(m)]
        out += [f"{nom} : adresse MAC {m}" for m in MAC.findall(texte) if not MAC_PERMISE.match(m)]
        out += [f"{nom} : nom réseau RMS-ESP32-{m}" for m in NOM_ESP.findall(texte) if m != "0000001"]
    git = shutil.which("git")
    if git and (RACINE / ".git").exists():
        r = subprocess.run([git, "log", "--format=%ae%n%ce"], cwd=RACINE, capture_output=True, text=True)
        for e in sorted(set(r.stdout.split())):
            if not EMAIL_PERMIS.search(e):
                out.append(f"historique git : envoi signé avec une adresse non masquée ({e.split('@')[-1]})")
    return out


def test_aucune_donnee_personnelle():
    p = problemes()
    assert not p, "Données personnelles trouvées :\n" + "\n".join(p)


if __name__ == "__main__":
    p = problemes()
    print("\n".join(p) if p else "Aucune donnée personnelle trouvée.")
    sys.exit(1 if p else 0)
