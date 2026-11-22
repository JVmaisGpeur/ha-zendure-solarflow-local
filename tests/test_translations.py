"""L1 / L2 : traductions complètes et identiques en français et en anglais.

python3 tests/test_translations.py
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "zendure_local"


def flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        out.update(flat(v, key) if isinstance(v, dict) else {key: v})
    return out


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_same_keys():
    fr, en, strings = (flat(load(n)) for n in ("translations/fr.json", "translations/en.json", "strings.json"))
    assert set(fr) == set(en), f"clés différentes FR/EN : {set(fr) ^ set(en)}"
    assert set(strings) == set(en), f"strings.json différent : {set(strings) ^ set(en)}"
    for k in fr:
        assert fr[k].count("{") == en[k].count("{"), f"paramètres différents : {k}"
        assert fr[k].strip() and en[k].strip(), f"texte vide : {k}"


def code():
    return "\n".join(p.read_text(encoding="utf-8") for p in ROOT.glob("*.py"))


def test_entity_keys_translated():
    src = code()
    keys = set(re.findall(r'translation_key\s*=\s*"([a-z0-9_]+)"', src))
    keys |= set(re.findall(r'_attr_translation_key\s*=\s*"([a-z0-9_]+)"', src))
    exceptions = set(re.findall(r'translation_key="([a-z0-9_]+)"', src))
    for lang in ("fr", "en"):
        t = load(f"translations/{lang}.json")
        names = {k for platform in t["entity"].values() for k in platform}
        issues = set(t["issues"])
        exc = set(t["exceptions"])
        sel = set(t.get("selector", {}))
        missing = {k for k in keys if k not in names and k not in issues and k not in exc and k not in sel}
        assert not missing, f"{lang} : clés sans traduction {missing}"
        assert {k for k in exceptions if k in exc or k in issues or k in names or k in sel} == exceptions


def test_enum_states_translated():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("zl_const", ROOT / "const.py")
    c = importlib.util.module_from_spec(spec)
    sys.modules["zl_const"] = c
    spec.loader.exec_module(c)
    for lang in ("fr", "en"):
        e = load(f"translations/{lang}.json")["entity"]
        rs = e["sensor"]["regulation_state"]["state"]
        assert set(c.BATTERY_REGULATION_STATES + c.GROUP_REGULATION_STATES) <= set(rs), lang
        assert set(c.MODES + [c.MODE_GROUP]) <= set(e["select"]["operating_mode"]["state"]), lang
        assert set(c.STRATEGIES) <= set(e["select"]["strategy"]["state"]), lang


def test_no_hardcoded_visible_text():
    """Aucun message d'erreur affiché codé en dur : HomeAssistantError passe par translation_key."""
    src = code()
    bad = re.findall(r'HomeAssistantError\(\s*["f]', src)
    assert not bad, f"HomeAssistantError avec texte en dur : {bad}"
    assert '"statut"' not in src, "l'attribut texte statut doit être remplacé par regulation_state (L2)"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("Traductions : OK")
