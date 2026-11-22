"""Tests du répartiteur de groupe (sans Home Assistant) : python3 tests/test_dispatch.py"""
import importlib.util
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dispatch", ROOT / "custom_components/zendure_local/dispatch.py")
d = importlib.util.module_from_spec(spec)
sys.modules["dispatch"] = d
spec.loader.exec_module(d)
M, C = d.Member, d.Circuit


def two():
    # 2400 AC (8,64 kWh, circuit 1200 W) et 2400 AC+ (12 kWh)
    return [
        M("ac", soc=60, min_soc=5, max_soc=100, capacity=8.64, max_charge=1200, max_discharge=1200),
        M("acp", soc=40, min_soc=9, max_soc=100, capacity=12.0, max_charge=2400, max_discharge=2400),
    ]


def check(parts, members, total, circuits=()):
    sign = 1 if total > 0 else -1
    by = {m.id: m for m in members}
    for i, v in parts.items():
        assert v == 0 or (v > 0) == (total > 0), f"G6 signe opposé {parts}"
        cap = by[i].max_discharge if sign > 0 else by[i].max_charge
        ok = by[i].can_discharge if sign > 0 else by[i].can_charge
        assert abs(v) <= cap + 1e-6, f"G7 limite dépassée {i}={v} > {cap}"
        if not ok:
            assert v == 0, f"G7 batterie bloquée sollicitée {i}={v}"
    assert sum(abs(v) for v in parts.values()) <= abs(total) + 1e-6, f"G9 total {parts} > {total}"
    for c in circuits:
        used = sum(abs(parts[i]) for i in c.members if i in parts)
        assert used <= c.limit + 1e-6, f"G12 circuit {used} > {c.limit}"


def test_simultaneous_prorata():
    ms = two()
    p = d.dispatch(1800, ms, d.SIMULTANEOUS)
    check(p, ms, 1800)
    assert p == {"ac": 600, "acp": 1200}, p


def test_soc_balance_direction():
    ms = two()
    dis = d.dispatch(1000, ms, d.SOC_BALANCE)
    chg = d.dispatch(-1000, ms, d.SOC_BALANCE)
    check(dis, ms, 1000)
    check(chg, ms, -1000)
    # En décharge, la batterie au SOC le plus haut (ac, 60 %) prend plus que sa part de capacité
    assert dis["ac"] / 1000 > 8.64 / 20.64, dis
    # En charge, la plus vide (acp, 40 %) prend plus que sa part de capacité
    assert abs(chg["acp"]) / 1000 > 12.0 / 20.64, chg
    # À SOC égaux, part au prorata de la capacité : les SOC évoluent au même rythme
    eq = [M("a", soc=50, capacity=8.64, max_charge=5000, max_discharge=5000),
          M("b", soc=50, capacity=12.0, max_charge=5000, max_discharge=5000)]
    p = d.dispatch(2064, eq, d.SOC_BALANCE, rounding=False)
    assert abs(p["a"] - 864) < 1 and abs(p["b"] - 1200) < 1, p


def test_report_and_total_limit():
    ms = two()
    p = d.dispatch(5000, ms, d.SIMULTANEOUS)
    check(p, ms, 5000)
    assert p == {"ac": 1200, "acp": 2400}, p  # G9 : jamais plus que la somme des limites


def test_blocked_battery_reported_to_other():
    ms = two()
    ms[1].can_discharge = False  # 2400 AC+ au SOC min
    p = d.dispatch(1500, ms, d.SOC_BALANCE)
    check(p, ms, 1500)
    assert p == {"ac": 1200, "acp": 0}, p


def test_priority_switchover():
    ms = two()
    order = ["ac", "acp"]
    p = d.dispatch(800, ms, d.PRIORITY, order)
    assert p == {"ac": 800, "acp": 0}, p  # la première travaille seule
    p = d.dispatch(2000, ms, d.PRIORITY, order)
    check(p, ms, 2000)
    assert p == {"ac": 1200, "acp": 800}, p  # bascule à sa limite
    ms[0].can_discharge = False  # la première atteint son SOC min
    p = d.dispatch(800, ms, d.PRIORITY, order)
    assert p == {"ac": 0, "acp": 800}, p


def test_shared_circuit():
    ms = [
        M("a", max_charge=2400, max_discharge=2400),
        M("b", max_charge=2400, max_discharge=2400),
        M("c", max_charge=1200, max_discharge=1200),
    ]
    circ = [C({"a", "b"}, 3000)]
    for strat in (d.SIMULTANEOUS, d.SOC_BALANCE, d.PRIORITY):
        for total in (-6000, -3500, 2000, 4200, 6000):
            p = d.dispatch(total, ms, strat, ["a", "b", "c"], circ)
            check(p, ms, total, circ)
    p = d.dispatch(4200, ms, d.SIMULTANEOUS, None, circ)
    assert p["a"] + p["b"] <= 3000 and p["c"] == 1200, p  # surplus reporté sur c
    assert d.capability(ms, 1, circ) == 4200


def test_random_invariants():
    rnd = random.Random(7)
    for _ in range(3000):
        n = rnd.randint(2, 4)
        ms = [
            M(str(i), soc=rnd.uniform(0, 100), min_soc=rnd.choice([0, 5, 10]), max_soc=rnd.choice([90, 100]),
              max_charge=rnd.choice([0, 600, 1200, 2400, 3200]), max_discharge=rnd.choice([0, 800, 1200, 2400]),
              can_charge=rnd.random() > 0.2, can_discharge=rnd.random() > 0.2)
            for i in range(n)
        ]
        ids = [m.id for m in ms]
        circ = [C(set(rnd.sample(ids, 2)), rnd.choice([800, 1500, 3000]))] if rnd.random() > 0.5 else []
        total = rnd.uniform(-8000, 8000)
        for strat in (d.SIMULTANEOUS, d.SOC_BALANCE, d.PRIORITY):
            p = d.dispatch(total, ms, strat, ids[::-1], circ)
            check(p, ms, total, circ)
            # Tout ce qui est possible est utilisé (à 10 W près par batterie)
            possible = min(abs(total), d.capability(ms, 1 if total > 0 else -1, circ))
            assert sum(abs(v) for v in p.values()) >= possible - d.STEP * n - 1e-6, (strat, p, total, possible)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"{len(tests)} tests du répartiteur : OK")
