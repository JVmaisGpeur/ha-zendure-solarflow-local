"""Carte : chaque bloc a son bouton « i », avec un texte en français et en anglais (v1.7.0).

python3 tests/test_card_help.py
"""
from __future__ import annotations

import pathlib
import re
import sys

CARD = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "zendure_local" / "frontend" / "zendure-solarflow-card.js"


def help_block(js: str, lang: str) -> str:
    """Texte de l'objet help: { … } de la langue donnée dans I18N."""
    start = js.index(f"  {lang}: {{")
    h = js.index("help: {", start)
    depth, i = 0, h + len("help: ")
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[i:j + 1]
    raise AssertionError(f"help {lang} non fermé")


def main() -> int:
    js = CARD.read_text(encoding="utf-8")
    keys = re.findall(r'"(\w+)"', re.search(r"const HELP_KEYS = \[([^\]]*)\]", js).group(1))
    errors = []
    for lang in ("fr", "en"):
        block = help_block(js, lang)
        found = set(re.findall(r"^\s*(\w+):\s*\"", block, re.M))
        for k in keys:
            if k not in found:
                errors.append(f"{lang} : texte « i » manquant pour {k}")
        for k in found - set(keys):
            errors.append(f"{lang} : texte « i » sans bloc ({k})")
    used = set(re.findall(r'ib\("(\w+)"\)', js)) | set(re.findall(r'data-help="(\w+)"', js))
    for k in keys:
        if k not in used:
            errors.append(f"bloc sans bouton « i » : {k}")
    for e in errors:
        print("ÉCHEC", e)
    if not errors:
        print(f"Carte : {len(keys)} blocs avec leur « i », en français et en anglais")
    return 1 if errors else 0


def test_card_help():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
