"""Z4 (v1.7.0) : provenance de l'énergie de charge et stock par origine.

python3 tests/test_provenance.py

1) Calcul pur (provenance.py) : chaque critère d'acceptation du cahier des charges.
2) Intégration en temps virtuel : groupe de deux batteries, surplus solaire puis charge réseau.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "custom_components" / "zendure_local"))
from provenance import Provenance, combine  # noqa: E402

RESULTS: list[str] = []


def ok(msg: str) -> None:
    RESULTS.append(msg)
    print("ok ", msg)


def close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def run(p: Provenance, seconds: int, p_ac=0, meter=None, p_pv=0, p_pack=0, level=50, cap=10.0, step=5, t0=0.0):
    """Lectures toutes les `step` s pendant `seconds` s ; renvoie l'instant final."""
    t = t0
    for _ in range(seconds // step + 1):
        p.sample(t, p_ac, meter, p_pv, p_pack, level, cap)
        t += step
    return t - step


# ------------------------------------------------------------------------------------------ calcul pur
def unit_tests() -> None:
    # Surplus solaire : charge 1 500 W pendant 1 h, compteur à −100 W (léger surplus restant)
    p = Provenance()
    run(p, 3600, p_ac=1500, meter=-100, p_pack=1450)
    assert close(p.solar_in, 1.5, 0.01) and p.grid_in == 0, (p.grid_in, p.solar_in)
    ok(f"Surplus 1 500 W pendant 1 h : {p.solar_in:.3f} kWh solaire, {p.grid_in:.3f} kWh réseau")

    # Charge réseau 2 000 W pendant 1 h, sans solaire (le compteur voit maison 400 W + charge)
    p = Provenance()
    run(p, 3600, p_ac=2000, meter=2400, p_pack=1900)
    assert close(p.grid_in, 2.0, 0.01) and p.solar_in == 0
    ok(f"Charge réseau 2 000 W pendant 1 h : {p.grid_in:.3f} kWh réseau")

    # Charge 1 500 W avec 400 W de soutirage : 400 réseau, 1 100 solaire
    p = Provenance()
    run(p, 3600, p_ac=1500, meter=400, p_pack=1450)
    assert close(p.grid_in, 0.4, 0.005) and close(p.solar_in, 1.1, 0.005), (p.grid_in, p.solar_in)
    ok(f"Charge 1 500 W, soutirage 400 W : {p.grid_in:.3f} kWh réseau, {p.solar_in:.3f} kWh solaire")

    # Réseau + solaire = entrée AC + PV en continu (méthode des rectangles, mêmes lectures)
    p, ac_in, t = Provenance(), 0.0, 0.0
    profile = [(1200, 300), (1500, -200), (800, 800), (2000, 2500), (0, 400)]
    for ac, meter in profile * 40:
        p.sample(t, ac, meter, 0, ac * 0.95, 50, 10)
        ac_in += ac * 7 / 3_600_000
        t += 7
    ac_in -= profile[-1][0] * 7 / 3_600_000  # la dernière lecture n'est pas encore intégrée
    assert close(p.grid_in + p.solar_in, ac_in, ac_in * 0.001), (p.grid_in + p.solar_in, ac_in)
    ok(f"Réseau + solaire = entrée AC ({ac_in:.4f} kWh), écart < 0,1 %")

    # Modèle à entrées PV : 800 W de PV en continu, aucune entrée AC, compteur à 0
    p = Provenance()
    run(p, 3600, p_ac=0, meter=0, p_pv=800, p_pack=780)
    assert close(p.solar_in, 0.8, 0.01) and p.grid_in == 0
    ok("PV en continu 800 W pendant 1 h : tout solaire")

    # Sans capteur de compteur : toute la charge AC est comptée réseau
    p = Provenance()
    run(p, 3600, p_ac=1000, meter=None, p_pack=950)
    assert close(p.grid_in, 1.0, 0.01) and p.solar_in == 0
    ok("Sans compteur : charge AC comptée réseau")

    # Stock 50 / 50 (installation), décharge de la moitié : reste 50 / 50, somme = niveau × capacité
    p = Provenance()
    p.sample(0, 0, 0, 0, 0, 80, 10)
    assert close(p.stock_grid, 4.0, 1e-9) and close(p.stock_solar, 4.0, 1e-9) and p.initial_share == 100
    p.sample(3600, 0, 0, 0, 0, 40, 10)
    assert close(p.stock_grid, 2.0, 1e-9) and close(p.stock_solar, 2.0, 1e-9)
    assert p.initial_share == 100
    ok("Stock de départ 50 / 50, décharge de moitié : 2,0 + 2,0 kWh = 40 % × 10 kWh, part initiale 100 %")

    # Charge réseau qui double le stock réseau : part initiale 50 %
    t = 3600.0
    for k in range(721):  # 1 h, une lecture toutes les 5 s ; le niveau monte de 40 à 60 % (+2 kWh)
        p.sample(t, 2000, 2400, 0, 2000, 40 + 20 * k / 720, 10)
        t += 5
    p.sample(t, 0, 0, 0, 0, 60, 10)
    assert close(p.stock_grid, 4.0, 0.01) and close(p.stock_solar, 2.0, 0.01), (p.stock_grid, p.stock_solar)
    assert close(p.initial_share, 50.0, 0.5), p.initial_share
    ok(f"Charge réseau de 2 kWh : stock réseau {p.stock_grid:.2f} kWh, part initiale {p.initial_share:.0f} %")

    # SOC min qui change (la réserve de nuit) : il n'entre pas dans le calcul, stocks inchangés
    before = (p.stock_grid, p.stock_solar)
    for t2 in range(int(t) + 60, int(t) + 1800, 60):
        p.sample(t2, 0, 0, 0, 0, 60, 10)
    assert close(p.stock_grid, before[0], 1e-9) and close(p.stock_solar, before[1], 1e-9)
    ok("SOC min passé de 5 à 50 % puis 5 % : stocks inchangés (seuls le niveau et la capacité comptent)")

    # Calibration : le niveau saute de 60 à 72 % sans charge : somme recalée, proportions gardées
    share = p.stored_solar_share
    p.sample(t2 + 60, 0, 0, 0, 0, 72, 10)
    assert close(p.stock_grid + p.stock_solar, 7.2, 1e-9) and close(p.stored_solar_share, share, 1e-9)
    ok(f"Calibration 60 → 72 % : somme 7,2 kWh, part solaire gardée à {share:.1f} %")

    # Pack ajouté à 60 % : capacité 10 → 12 kWh, 1,2 kWh d'origine inconnue entre en stock de départ
    p = Provenance()
    p.sample(0, 0, 0, 0, 0, 60, 10)
    t = 5.0
    for k in range(721):  # +2 kWh réseau → 6 + 2 = 8 kWh
        p.sample(t, 2000, 2400, 0, 2000, 60 + 20 * k / 720, 10)
        t += 5
    p.sample(t, 0, 0, 0, 0, 80, 10)
    g0, s0, init0 = p.stock_grid, p.stock_solar, p.initial_share
    p.sample(t + 10, 0, 0, 0, 0, 80, 12)  # nouveau pack de 2 kWh, chargé à 80 %
    assert close(p.stock_grid, g0 + 0.8, 1e-6) and close(p.stock_solar, s0 + 0.8, 1e-6), (p.stock_grid, p.stock_solar)
    assert p.initial_share > init0
    ok(f"Pack ajouté : +0,8 kWh dans chaque stock, part initiale {init0:.0f} % → {p.initial_share:.0f} %")

    # Persistance : tout revient à l'identique
    q = Provenance.from_dict(p.as_dict())
    assert (q.grid_in, q.solar_in, q.stock_grid, q.stock_solar, q.initial_share) == (
        p.grid_in, p.solar_in, p.stock_grid, p.stock_solar, p.initial_share)
    ok("Redémarrage : les cinq valeurs et la part initiale sont conservées")

    # Groupe : somme des batteries
    a, b = Provenance(), Provenance()
    run(a, 1800, p_ac=1000, meter=500, p_pack=950, level=50, cap=8.64)
    run(b, 1800, p_ac=1000, meter=500, p_pack=950, level=40, cap=12.0)
    g = combine([a, b], 1800)
    assert close(g["energy_charged_grid"], a.grid_in + b.grid_in, 1e-9)
    assert close(g["stored_energy_grid"] + g["stored_energy_solar"], 0.5 * 8.64 + 0.4 * 12, 1e-6)
    ok("Groupe : énergies et stocks = somme des batteries")


# ------------------------------------------------------------------------------------------ intégration
AC, ACP = "10.0.0.1", "10.0.0.2"
SPECS = {
    AC: dict(sn="AC001", product="solarFlow2400AC", packs=[5, 5, 5], soc=40, min_soc=5),
    ACP: dict(sn="ACP01", product="solarFlow2400AC+", packs=[500, 350, 300, 350, 300], soc=40, min_soc=9),
}


async def integration(loop) -> None:
    import sim_world as w

    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": list(SPECS)})
    world = w.World(loop, hass, bats, noise=10)
    world.start()
    val = lambda entry, key: w.entity(hass, entry, key).native_value  # noqa: E731

    # 30 min de surplus solaire de 2 000 W, groupe en couplage intelligent
    world.load, world.solar = 400, 2400
    await w.entity(hass, g, "operating_mode").async_select_option("smart")
    await asyncio.sleep(1800)
    solar, grid = val(g, "energy_charged_solar"), val(g, "energy_charged_grid")
    assert solar > 0.8 and grid < 0.05 * solar, (solar, grid)
    ok(f"Surplus 30 min (groupe) : {solar:.2f} kWh solaire, {grid:.3f} kWh réseau (retard de régulation)")
    share_sun = val(g, "stored_solar_share")

    # 30 min de charge réseau, sans soleil
    world.solar = 0
    await w.entity(hass, g, "import_limit").async_set_native_value(3000)
    await w.entity(hass, g, "charge_target_soc").async_set_native_value(100)
    await w.entity(hass, g, "operating_mode").async_select_option("grid_charge")
    await asyncio.sleep(1800)
    grid2 = val(g, "energy_charged_grid")
    assert grid2 - grid > 1.0, (grid, grid2)
    share_after = val(g, "stored_solar_share")
    assert share_after < share_sun, (share_sun, share_after)
    ok(f"Charge réseau 30 min : +{grid2 - grid:.2f} kWh réseau, part solaire du stock {share_sun:.0f} % → {share_after:.0f} %")

    # Chaque batterie : réseau + solaire = son compteur d'entrée AC
    for host in (AC, ACP):
        e = entries[host]
        total = val(e, "energy_charged_grid") + val(e, "energy_charged_solar")
        ac_in = val(e, "energy_grid_input")
        assert close(total, ac_in, max(0.001 * ac_in, 0.002)), (host, total, ac_in)
    ok("Chaque batterie : réseau + solaire = énergie entrée côté prise (< 0,1 %)")

    # Groupe = somme des batteries, à 1 % près
    for key in ("energy_charged_grid", "energy_charged_solar", "stored_energy_grid", "stored_energy_solar"):
        s = sum(val(entries[h], key) for h in (AC, ACP))
        assert close(val(g, key), s, max(0.01 * s, 0.002)), (key, val(g, key), s)
    ok("Groupe = somme des batteries pour les quatre énergies (< 1 %)")

    # Stocks = niveau × capacité
    for host in (AC, ACP):
        e = entries[host]
        stock = val(e, "stored_energy_grid") + val(e, "stored_energy_solar")
        expected = val(e, "electric_level") / 100 * val(e, "usable_capacity")
        assert close(stock, expected, 0.01), (host, stock, expected)
    attrs = w.entity(hass, g, "stored_energy_grid").extra_state_attributes
    assert attrs["initial_share"] is not None and 0 < attrs["initial_share"] < 100, attrs
    ok(f"Stocks = niveau × capacité ; part encore issue du stock de départ : {attrs['initial_share']:.0f} %")

    # Tableau Énergie : kWh, total croissant
    for key in ("energy_charged_grid", "energy_charged_solar"):
        d = w.entity(hass, entries[AC], key).entity_description
        assert str(d.state_class).endswith("total_increasing") and str(d.native_unit_of_measurement) == "kWh", (
            key, d.state_class, d.native_unit_of_measurement)
    ok("energy_charged_grid / energy_charged_solar : kWh, total croissant (tableau Énergie)")
    await asyncio.sleep(1)


if __name__ == "__main__":
    unit_tests()
    import sim_world as w

    w.run(integration)
    print(f"\n{len(RESULTS)} vérifications OK")
