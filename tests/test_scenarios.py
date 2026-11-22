"""Critères d'acceptation v1.3.0, joués avec le vrai code de l'intégration en temps virtuel.

python3 tests/test_scenarios.py
"""
from __future__ import annotations

import asyncio
import statistics

import ha_stubs as stubs
import sim_world as w

AC = "10.0.0.1"   # SolarFlow 2400 AC, 3 × AB3000, circuit limité à 1200 W
ACP = "10.0.0.2"  # SolarFlow 2400 AC+, I2400 + 2 × AB2000S + 2 × AB3000L
SPECS = {
    AC: dict(sn="AC001", product="solarFlow2400AC", packs=[5, 5, 5], soc=60, min_soc=5, ramp=500, dead=1.2),
    ACP: dict(sn="ACP01", product="solarFlow2400AC+", packs=[500, 350, 300, 350, 300], soc=40, min_soc=9, ramp=800, dead=0.8),
}
RESULTS: list[str] = []


def ok(msg: str) -> None:
    RESULTS.append(msg)
    print("ok ", msg)


async def select(hass, entry, key, option):
    await w.entity(hass, entry, key).async_select_option(option)


async def set_number(hass, entry, key, value):
    await w.entity(hass, entry, key).async_set_native_value(value)


async def limit_ac_circuit(hass, entries, watts=1200):
    ea = entries[AC]
    hass.config_entries.async_update_entry(ea, options={**ea.options, "circuit_limit": watts})
    await hass.config_entries.async_reload(ea.entry_id)


def last_commands(bat: w.FakeBattery, t: float) -> float:
    cmds = [c for c in bat.commands if c[0] <= t]
    return cmds[-1][1] if cmds else 0.0


# ------------------------------------------------------------------------------------------
async def s_grid_charge_target_and_import(loop):
    """Z1 + Z4 : charge réseau, limite de soutirage, gros appareil, SOC cible et hystérésis."""
    stubs.ISSUES.clear()
    spec = {ACP: dict(SPECS[ACP], soc=55)}
    hass, integ, bats, entries, _ = await w.setup(loop, spec)
    e, b = entries[ACP], bats[ACP]
    world = w.World(loop, hass, bats, noise=10)
    world.start()
    await set_number(hass, e, "import_limit", 2000)
    await set_number(hass, e, "charge_target_soc", 60)
    await select(hass, e, "operating_mode", "grid_charge")
    await asyncio.sleep(40)
    g = [x[1] for x in world.log[-10:]]
    assert max(g) <= 2000 + 60, f"soutirage {max(g)} > limite"
    assert -b.ac > 1400, f"devrait charger ~1600 W, charge {-b.ac}"
    # Gros appareil de 1500 W : le soutirage doit revenir sous la limite en moins de 5 s
    world.extra = 1500
    t0 = loop.time()
    await asyncio.sleep(15)
    back = next((t for t, gr, _ in world.log if t > t0 and gr <= 2000 + 40), None)
    assert back is not None and back - t0 <= 5.0, f"retour sous import_limit en {None if back is None else back - t0:.1f} s"
    ok(f"Charge réseau : soutirage revenu sous import_limit {back - t0:.1f} s après un appareil de 1500 W")
    state = w.entity(hass, e, "regulation_state").native_value
    assert state in ("import_limited", "grid_charging"), state
    world.extra = 0
    # Charge jusqu'au SOC cible
    for _ in range(400):
        await asyncio.sleep(10)
        if w.entity(hass, e, "regulation_state").native_value == "target_reached":
            break
    assert w.entity(hass, e, "regulation_state").native_value == "target_reached"
    await asyncio.sleep(60)
    assert abs(b.ac) < 30 and b.soc >= 59.5, f"après cible : {b.ac} W, SOC {b.soc}"
    assert all(c[1] <= 0 for c in b.commands), "jamais de décharge en Charge réseau"
    ok(f"SOC cible 60 % atteint (SOC {b.soc:.1f} %), batterie au repos, aucune décharge")
    # Hystérésis : reprise seulement sous 57 %
    b.soc = 58.2
    await asyncio.sleep(30)
    assert abs(b.ac) < 30, "ne doit pas reprendre à 58 %"
    b.soc = 56.8
    await asyncio.sleep(30)
    assert -b.ac > 500, f"doit reprendre à 56,8 % (charge {b.ac})"
    ok("Hystérésis : pas de reprise à 58 %, reprise à 56,8 % (cible − 3 points)")


async def s_restart_persistence(loop):
    """Z1 / Z4 : import_limit et charge_target_soc survivent à un redémarrage."""
    stubs.RESTORE.clear()
    hass, integ, bats, entries, _ = await w.setup(loop, {ACP: SPECS[ACP]})
    e = entries[ACP]
    await set_number(hass, e, "import_limit", 4300)
    await set_number(hass, e, "charge_target_soc", 72)
    for ent in hass.entities[e.entry_id]:  # ce que Home Assistant mémorise à l'arrêt
        if ent.translation_key in ("import_limit", "charge_target_soc"):
            stubs.RESTORE[ent.unique_id] = ent.native_value
    await hass.config_entries.async_reload(e.entry_id)
    assert w.entity(hass, e, "import_limit").native_value == 4300
    assert w.entity(hass, e, "charge_target_soc").native_value == 72
    ok("import_limit (4300 W) et charge_target_soc (72 %) conservés après redémarrage")


async def s_circuit_limit(loop):
    """Z8 / G12 : une batterie limitée à 1200 W par son circuit ne la dépasse jamais."""
    hass, integ, bats, entries, _ = await w.setup(loop, {AC: SPECS[AC]})
    e = entries[AC]
    hass.config_entries.async_update_entry(e, options={**e.options, "circuit_limit": 1200})
    await hass.config_entries.async_reload(e.entry_id)
    assert w.entity(hass, e, "max_discharge_power").native_value == 1200
    await set_number(hass, e, "power_setpoint", 2400)
    await asyncio.sleep(5)
    assert max(c[1] for c in bats[AC].commands) <= 1200, bats[AC].commands
    ok("Limite de circuit 1200 W : consigne manuelle de 2400 W ramenée à 1200 W")


async def s_group_30min(loop, strategy="soc_balance"):
    """G6, G7, G9, G12 : groupe de deux modèles différents, 30 minutes de vie réelle simulée."""
    stubs.ISSUES.clear()
    hass, integ, bats, entries, g = await w.setup(
        loop, SPECS, group={"hosts": [AC, ACP], "options": {}},
    )
    # La 2400 AC est sur un circuit limité à 1200 W
    ea = entries[AC]
    hass.config_entries.async_update_entry(ea, options={**ea.options, "circuit_limit": 1200})
    await hass.config_entries.async_reload(ea.entry_id)
    await select(hass, g, "strategy", strategy)
    await select(hass, g, "operating_mode", "smart")
    world = w.World(loop, hass, bats, seed=3, noise=15)
    world.start()
    # Programme : consommation et surplus solaire qui changent toutes les 1 à 3 minutes
    steps = [400, 1500, 2900, 800, -1200, -2500, 300, 3600, 1000, -600, 200, 2000, -1800, 600, 1200]
    windows = []
    t_start = loop.time()
    for load in steps:
        world.load = load
        t0 = loop.time()
        await asyncio.sleep(120)
        windows.append((t0, loop.time(), load))
    duration = (loop.time() - t_start) / 60
    # G6 : à chaque instant, les dernières consignes envoyées ont le même signe
    times = sorted({c[0] for b in bats.values() for c in b.commands})
    for t in times:
        a, p = last_commands(bats[AC], t), last_commands(bats[ACP], t)
        assert not (a > 0 > p or p > 0 > a), f"G6 : signes opposés à t={t}: {a} / {p}"
    # G7 / Z8 : jamais au-dessus des limites
    assert max(abs(c[1]) for c in bats[AC].commands) <= 1200
    assert max(abs(c[1]) for c in bats[ACP].commands) <= 2400
    # Pas d'oscillation : après 25 s, le compteur est stable dans chaque palier atteignable
    worst = 0.0
    for t0, t1, load in windows:
        possible = (1200 + 2400) if load > 0 else (1200 + 2400)
        if abs(load) > possible - 200:
            continue
        g_ = [x[1] for x in world.log if t0 + 25 <= x[0] < t1]
        sd = statistics.pstdev(g_)
        worst = max(worst, sd)
        assert abs(statistics.mean(g_)) < 40, f"palier {load} W : écart moyen {statistics.mean(g_):.0f} W"
        assert sd < 3 * world.noise, f"palier {load} W : oscillation (écart-type {sd:.0f} W)"
    n_cmd = sum(len(b.commands) for b in bats.values())
    ok(f"Groupe « {strategy} », {duration:.0f} min : jamais de signes opposés, limites respectées, "
       f"pas d'oscillation (écart-type max {worst:.0f} W pour un bruit de {world.noise:.0f} W), {n_cmd} commandes")
    return hass, bats, entries, g, world


async def s_group_soc_balance_converges(loop):
    hass, bats, entries, g, world = await s_group_30min(loop, "soc_balance")
    # Équilibrage : une heure de décharge continue à 1500 W
    gap0 = bats[AC].soc - bats[ACP].soc
    s_ac0, s_acp0 = bats[AC].soc, bats[ACP].soc
    world.load = 1500
    await asyncio.sleep(3600)
    gap1 = bats[AC].soc - bats[ACP].soc
    drop_ac, drop_acp = s_ac0 - bats[AC].soc, s_acp0 - bats[ACP].soc
    assert drop_ac > drop_acp > 0, (drop_ac, drop_acp)
    assert gap0 - gap1 >= 5, f"écart {gap0:.1f} → {gap1:.1f}"
    ok(f"Équilibrage des SOC (1 h à 1500 W) : la plus pleine baisse de {drop_ac:.1f} points, l'autre de "
       f"{drop_acp:.1f} ; écart {gap0:.1f} → {gap1:.1f} points")


async def s_priority_switchover(loop):
    """priorité : la première batterie seule, puis bascule à sa limite (puissance puis SOC)."""
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP]})
    await limit_ac_circuit(hass, entries)
    hass.config_entries.async_update_entry(g, options={**g.options, "priority_order": [entries[AC].entry_id, entries[ACP].entry_id]})
    await hass.config_entries.async_reload(g.entry_id)
    await select(hass, g, "strategy", "priority")
    await select(hass, g, "operating_mode", "smart")
    world = w.World(loop, hass, bats, noise=5)
    world.start()
    world.load = 800
    await asyncio.sleep(60)
    assert bats[AC].ac > 700 and abs(bats[ACP].ac) < 30, (bats[AC].ac, bats[ACP].ac)
    world.load = 2000
    await asyncio.sleep(60)
    assert bats[AC].ac > 1150 and bats[ACP].ac > 600, (bats[AC].ac, bats[ACP].ac)
    ok(f"Priorité : 800 W → 2400 AC seule ; 2000 W → bascule ({bats[AC].ac:.0f} W + {bats[ACP].ac:.0f} W)")
    # La première atteint son SOC min : la suivante prend tout
    bats[AC].soc = 5.0
    world.load = 800
    await asyncio.sleep(60)
    assert abs(bats[AC].ac) < 30 and bats[ACP].ac > 700, (bats[AC].ac, bats[ACP].ac)
    ok("Priorité : la 2400 AC au SOC min, la 2400 AC+ prend le relais")


async def s_simultaneous(loop):
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP]})
    await limit_ac_circuit(hass, entries)
    await select(hass, g, "strategy", "simultaneous")
    await select(hass, g, "operating_mode", "smart")
    world = w.World(loop, hass, bats, noise=5)
    world.start()
    world.load = 1800
    await asyncio.sleep(60)
    ratio = bats[ACP].ac / max(bats[AC].ac, 1)
    assert 1.6 < ratio < 2.4, f"prorata attendu ~2 (2400/1200), obtenu {ratio:.2f}"
    ok(f"Simultanée : répartition au prorata des puissances ({bats[AC].ac:.0f} W / {bats[ACP].ac:.0f} W)")


async def s_degraded(loop):
    """G8 : batterie débranchée en marche, puis retour."""
    stubs.ISSUES.clear()
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP]})
    await select(hass, g, "operating_mode", "smart")
    world = w.World(loop, hass, bats, noise=5)
    world.start()
    world.load = 1500
    await asyncio.sleep(120)
    bats[AC].online = False
    bats[AC].ac = 0.0  # débranchée : elle ne fournit plus rien
    await asyncio.sleep(90)
    rs = w.entity(hass, g, "regulation_state").native_value
    active = w.entity(hass, g, "active_batteries").native_value
    assert rs == "degraded" and active == 1, (rs, active)
    assert any(k.startswith("unavailable_") for k in stubs.ISSUES), stubs.ISSUES
    tail = [x[1] for x in world.log[-15:]]
    assert abs(statistics.mean(tail)) < 60, f"le groupe doit compenser avec l'autre : {statistics.mean(tail):.0f} W"
    ok(f"Batterie débranchée : groupe « degraded », 1 batterie active, alerte Réparations, compteur à {statistics.mean(tail):.0f} W")
    bats[AC].online = True
    await asyncio.sleep(60)
    assert w.entity(hass, g, "active_batteries").native_value == 2
    assert not any(k.startswith("unavailable_") for k in stubs.ISSUES), stubs.ISSUES
    assert w.entity(hass, g, "regulation_state").native_value == "regulating"
    ok("Retour de la batterie : elle reprend sa place, alerte levée")


async def s_member_settings_and_leave(loop):
    """G3 bis et G4 : réglages d'un membre ignorés ; changement de mode = sortie du pilotage."""
    stubs.ISSUES.clear()
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP]})
    ea = entries[AC]
    assert w.entity(hass, ea, "operating_mode").current_option == "group"
    await set_number(hass, ea, "charge_target_soc", 20)
    await set_number(hass, ea, "import_limit", 500)
    attrs = w.entity(hass, ea, "charge_target_soc").extra_state_attributes
    assert attrs == {"ignored_by_group": g.title}, attrs
    await set_number(hass, g, "import_limit", 5000)
    await set_number(hass, g, "charge_target_soc", 100)
    await select(hass, g, "operating_mode", "grid_charge")
    world = w.World(loop, hass, bats, noise=5)
    world.start()
    await asyncio.sleep(60)
    # La 2400 AC (SOC 60 %) charge malgré sa cible à 20 % : c'est la cible du groupe (100 %) qui compte
    assert bats[AC].ac < -300, bats[AC].ac
    ok("Batterie membre : sa cible (20 %) et sa limite (500 W) sont ignorées, celles du groupe s'appliquent")
    # G4 : l'utilisateur met la 2400 AC en manuel → elle sort du pilotage, alerte, le groupe continue
    await select(hass, ea, "operating_mode", "manual")
    await asyncio.sleep(100)
    assert w.entity(hass, g, "regulation_state").native_value == "degraded"
    assert any(k.startswith("left_") for k in stubs.ISSUES), stubs.ISSUES
    n_before = len(bats[AC].commands)
    await asyncio.sleep(30)
    assert len(bats[AC].commands) == n_before, "le groupe ne doit plus commander une batterie sortie"
    ok("Mode changé sur un membre : sortie du pilotage, alerte « n'est plus pilotée », groupe dégradé")
    await select(hass, ea, "operating_mode", "group")
    await asyncio.sleep(10)
    assert not any(k.startswith("left_") for k in stubs.ISSUES)
    assert w.entity(hass, g, "active_batteries").native_value == 2
    ok("Remise sur « Pilotée par le groupe » : elle reprend sa place, alerte levée")


async def s_leave_and_delete(loop):
    """G5 : sortie d'une batterie et suppression du groupe → modes d'avant."""
    hass, integ, bats, entries, _ = await w.setup(loop, SPECS)
    ea, ep = entries[AC], entries[ACP]
    await select(hass, ea, "operating_mode", "smart_discharge")
    await select(hass, ep, "operating_mode", "off")
    g = stubs.ConfigEntry("zendure_local", "Batteries", {"entry_type": "group", "name": "Batteries",
                          "members": [ea.entry_id, ep.entry_id]}, {"grid_sensor": w.GRID})
    await hass.config_entries.add(g)
    assert w.entity(hass, ea, "operating_mode").current_option == "group"
    assert w.entity(hass, ep, "operating_mode").current_option == "group"
    # Retrait d'une batterie : pas possible sous 2 membres → on ajoute d'abord une 3e batterie
    spec3 = dict(sn="AC002", product="solarFlow2400AC", packs=[5, 5], soc=50)
    bats["10.0.0.3"] = w.FakeBattery(loop, **spec3)
    e3 = await hass.config_entries.add(stubs.ConfigEntry("zendure_local", "Zendure 3", {"host": "10.0.0.3"},
                                                          {"grid_sensor": w.GRID}, unique_id="AC002"))
    await select(hass, e3, "operating_mode", "manual")
    hass.config_entries.async_update_entry(g, options={**g.options, "members": [ep.entry_id, e3.entry_id]})
    await hass.config_entries.async_reload(g.entry_id)
    assert w.entity(hass, ea, "operating_mode").current_option == "smart_discharge"
    assert w.entity(hass, e3, "operating_mode").current_option == "group"
    ok("Sortie d'une batterie du groupe : elle retrouve son mode d'avant (Décharge intelligente)")
    await hass.config_entries.remove(g)
    assert w.entity(hass, ep, "operating_mode").current_option == "off"
    assert w.entity(hass, e3, "operating_mode").current_option == "manual"
    ok("Suppression du groupe : chaque batterie retrouve son mode d'avant (Arrêt, Manuel)")


async def s_single_battery_unchanged(loop):
    """Une batterie seule fonctionne comme en v1.2.0 : couplage intelligent au compteur."""
    hass, integ, bats, entries, _ = await w.setup(loop, {ACP: SPECS[ACP]})
    e = entries[ACP]
    await select(hass, e, "operating_mode", "smart")
    world = w.World(loop, hass, bats, noise=10)
    world.start()
    for load in (900, -700, 1500):
        world.load = load
        await asyncio.sleep(90)
        tail = [x[1] for x in world.log[-30:]]
        assert abs(statistics.mean(tail)) < 30, (load, statistics.mean(tail))
    ok("Batterie seule : couplage intelligent toujours à ~0 W au compteur (900 W, surplus 700 W, 1500 W)")


SCENARIOS = [
    s_single_battery_unchanged, s_grid_charge_target_and_import, s_restart_persistence, s_circuit_limit,
    s_group_soc_balance_converges, s_simultaneous, s_priority_switchover, s_degraded,
    s_member_settings_and_leave, s_leave_and_delete,
]

if __name__ == "__main__":
    import sys
    only = sys.argv[1:]
    for sc in SCENARIOS:
        if only and sc.__name__ not in only:
            continue
        w.run(sc)
    print(f"\n{len(RESULTS)} vérifications OK")
