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


def reversals(bat: w.FakeBattery, window: float = 1.0) -> int:
    """Consignes contradictoires : A → B → A en moins de `window` secondes."""
    c = bat.commands
    return sum(
        1 for (t0, a), (_t1, b), (t2, a2) in zip(c, c[1:], c[2:], strict=False)
        if a2 == a and b != a and t2 - t0 < window
    )


async def s_group_slow_meter_no_reversal(loop):
    """Compteur lent (5 s) et bruité : une injection de 300 W est corrigée, sans consignes
    contradictoires (bug 1.4 : redispatch du groupe pendant une commande en cours)."""
    stubs.ISSUES.clear()
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP], "options": {}})
    bats[AC].write_latency, bats[ACP].write_latency = 0.02, 0.4  # réponses à des vitesses différentes
    await select(hass, g, "strategy", "simultaneous")
    world = w.World(loop, hass, bats, seed=5, noise=40, meter_period=5.0)
    world.load = 2040
    world.start()
    # Commande directe : la batterie rapide ne doit pas recevoir l'ancienne part juste après
    await select(hass, g, "operating_mode", "manual")
    hub = g.runtime_data
    await hub.async_set_power(2040)
    await asyncio.sleep(10)
    t_cmd = loop.time()
    await hub.async_set_power(1900)
    await asyncio.sleep(5)
    for b in bats.values():
        sent = [v for t, v in b.commands if t >= t_cmd]
        assert sent == [950], f"consignes envoyées après 1900 W : {sent}"
    await select(hass, g, "operating_mode", "smart")
    await asyncio.sleep(180)
    t0 = loop.time()
    world.load = 1740  # la maison consomme 300 W de moins : injection
    await asyncio.sleep(90)
    rev = sum(reversals(b) for b in bats.values())
    assert rev == 0, f"{rev} consignes contradictoires"
    back = next((x[0] for x in world.log if x[0] > t0 and x[1] > -100), None)
    assert back is not None and back - t0 <= 20, f"injection corrigée en {None if back is None else back - t0:.0f} s"
    late = [x[1] for x in world.log if x[0] > t0 + 40]
    assert abs(statistics.mean(late)) < 50, f"écart moyen {statistics.mean(late):.0f} W"
    # Commande perdue par la batterie : relue, constatée absente, renvoyée
    await select(hass, g, "operating_mode", "manual")
    bats[AC].drop_writes = 1
    t_cmd = loop.time()
    await hub.async_set_power(1600)
    await asyncio.sleep(20)
    assert bats[AC].props["outputLimit"] == 800, bats[AC].props
    resend = next(t for t, v in bats[AC].commands if t > t_cmd and v == 800) - t_cmd
    ok(f"Commande perdue par une batterie : renvoyée après {resend:.0f} s, consigne en place")
    ok(f"Compteur lent (5 s, bruit 40 W) : injection de 300 W corrigée en {back - t0:.0f} s, "
       f"aucune consigne contradictoire, écart moyen ensuite {statistics.mean(late):.0f} W")


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


# ---------------------------------------------------------------- v1.6.0 : commandes de puissance
def remember(hass, entry, keys):
    """Ce que Home Assistant mémorise à l'arrêt (valeur + attributs)."""
    for ent in hass.entities[entry.entry_id]:
        if ent.translation_key in keys:
            stubs.RESTORE[ent.unique_id] = ent.native_value
            stubs.RESTORE_ATTRS[ent.unique_id] = dict(ent.extra_state_attributes or {})


async def s_caps_default_no_effect(loop):
    """Sans réglage, les trois commandes sont sans effet (valeurs par défaut)."""
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP], "options": {}})
    for e in (*entries.values(), g):
        reg = e.runtime_data.regulator
        assert reg.charge_power_limit is None and reg.discharge_power_limit is None and reg.excluded_power == 0
        assert not reg.caps_active
    gc = w.entity(hass, g, "charge_power_limit")
    assert gc.native_value == g.runtime_data.max_charge_power, gc.native_value
    assert w.entity(hass, g, "excluded_power").native_value == 0
    ok("Commandes de puissance par défaut : aucun plafond, 0 W non couvert (comportement v1.5.0)")


async def s_charge_cap(loop):
    """Plafond de charge 600 W, mode smart, surplus 1 500 W : 600 W chargés, 900 W injectés."""
    hass, integ, bats, entries, _ = await w.setup(loop, {ACP: SPECS[ACP]})
    e = entries[ACP]
    world = w.World(loop, hass, bats, seed=3)
    world.load, world.solar = 400, 1900  # surplus 1 500 W
    world.start()
    await set_number(hass, e, "charge_power_limit", 600)
    await select(hass, e, "operating_mode", "smart")
    await asyncio.sleep(60)
    late = [x for x in world.log if x[0] > loop.time() - 20]
    charge = statistics.mean(-x[2][ACP][0] for x in late)
    grid = statistics.mean(x[1] for x in late)
    assert abs(charge - 600) <= 20 and abs(grid + 900) <= 40, (charge, grid)
    assert max(-v for _t, v in bats[ACP].commands if v is not None) <= 600
    assert e.runtime_data.regulator.state == "charge_capped"
    ok(f"Plafond de charge 600 W (surplus 1 500 W) : charge {charge:.0f} W, {-grid:.0f} W injectés, état charge_capped")


async def s_discharge_cap_zero(loop):
    """Plafond de décharge 0 W avec 1 000 W de consommation : aucune décharge."""
    hass, integ, bats, entries, _ = await w.setup(loop, {ACP: SPECS[ACP]})
    e = entries[ACP]
    world = w.World(loop, hass, bats, seed=4)
    world.load = 1000
    world.start()
    await select(hass, e, "operating_mode", "smart")
    await asyncio.sleep(30)
    await set_number(hass, e, "discharge_power_limit", 0)
    await asyncio.sleep(30)
    late = [x for x in world.log if x[0] > loop.time() - 15]
    assert max(x[2][ACP][0] for x in late) <= 0, late[-1]
    assert statistics.mean(x[1] for x in late) > 950
    assert e.runtime_data.regulator.state == "discharge_capped"
    # Manuel : la consigne est plafonnée aussi
    await set_number(hass, e, "power_setpoint", 800)
    await asyncio.sleep(5)
    assert bats[ACP].props["outputLimit"] == 0 and e.runtime_data.regulator.state == "discharge_capped"
    await set_number(hass, e, "discharge_power_limit", 2400)  # = maximum : plus de plafond
    await asyncio.sleep(5)
    assert e.runtime_data.regulator.discharge_power_limit is None
    assert bats[ACP].props["outputLimit"] == 800
    ok("Plafond de décharge 0 W (maison 1 000 W) : aucune décharge, état discharge_capped ; "
       "en manuel aussi, et retour à 800 W quand le plafond est levé")


async def s_group_charge_cap(loop):
    """Groupe de deux batteries, plafond de charge 1 000 W : le total ne le dépasse jamais."""
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP], "options": {}})
    world = w.World(loop, hass, bats, seed=6)
    world.load, world.solar = 300, 3300  # surplus 3 000 W
    world.start()
    await select(hass, g, "strategy", "simultaneous")
    await set_number(hass, g, "charge_power_limit", 1000)
    await select(hass, g, "operating_mode", "smart")
    await asyncio.sleep(90)
    totals = [sum(-v[0] for v in x[2].values()) for x in world.log if x[0] > 20]
    assert max(totals) <= 1000 + 5, max(totals)
    last = world.log[-1][2]
    assert last[AC][0] < 0 and last[ACP][0] < 0, last  # les deux chargent (stratégie simultanée)
    assert g.runtime_data.regulator.state == "charge_capped"
    ok(f"Groupe, plafond de charge 1 000 W : total max {max(totals):.0f} W, réparti "
       f"({-last[AC][0]} W / {-last[ACP][0]} W)")


async def s_excluded_power(loop):
    """Puissance à ne pas couvrir 2 400 W, maison 500 W, solaire 1 000 W : décharge ≤ 500 W."""
    hass, integ, bats, entries, _ = await w.setup(loop, {ACP: SPECS[ACP]}, options={"solar_sensor": w.SOLAR})
    e = entries[ACP]
    world = w.World(loop, hass, bats, seed=7)
    world.load, world.extra, world.solar = 500, 2400, 1000  # chauffe-eau 2 400 W en marche
    world.start()
    await set_number(hass, e, "excluded_power", 2400)
    await select(hass, e, "operating_mode", "smart")
    await asyncio.sleep(60)
    late = [x for x in world.log if x[0] > loop.time() - 20]
    dis = statistics.mean(x[2][ACP][0] for x in late)
    assert 430 <= dis <= 500 and max(x[2][ACP][0] for x in late) <= 500, dis
    assert e.runtime_data.regulator.state == "load_excluded"
    # Surplus solaire : la charge n'est pas modifiée, aucune charge réseau
    world.extra, world.solar = 0, 2000  # surplus 1 500 W
    await asyncio.sleep(60)
    late = [x for x in world.log if x[0] > loop.time() - 20]
    charge = statistics.mean(-x[2][ACP][0] for x in late)
    assert abs(charge - 1500) <= 60 and statistics.mean(x[1] for x in late) < 40, charge
    assert e.runtime_data.regulator.state == "regulating"
    ok(f"Puissance à ne pas couvrir 2 400 W : décharge {dis:.0f} W (maison 500 W), état load_excluded ; "
       f"avec surplus, charge solaire inchangée ({charge:.0f} W), pas de charge réseau")


async def s_pilot_expiry_and_manual_restart(loop):
    """Valeur d'un pilote : remise par défaut à l'expiration ; valeur manuelle : gardée au redémarrage."""
    stubs.RESTORE.clear()
    stubs.RESTORE_ATTRS.clear()
    hass, integ, bats, entries, _ = await w.setup(loop, {ACP: SPECS[ACP]})
    e = entries[ACP]
    ext = e.runtime_data.external
    ext.async_set(True, "Pilote de test", ["discharge_power_limit"])
    await set_number(hass, e, "discharge_power_limit", 0)
    ent = w.entity(hass, e, "discharge_power_limit")
    assert ent.native_value == 0 and ent.extra_state_attributes["set_by"] == "Pilote de test"
    await asyncio.sleep(29 * 60)
    assert e.runtime_data.regulator.discharge_power_limit == 0
    await asyncio.sleep(2 * 60)
    assert e.runtime_data.regulator.discharge_power_limit is None
    assert ent.native_value == e.runtime_data.max_discharge_power
    # Retrait explicite d'une déclaration : même effet
    ext.async_set(True, "Pilote de test", ["excluded_power"])
    await set_number(hass, e, "excluded_power", 1200)
    ext.async_set(False)
    assert e.runtime_data.regulator.excluded_power == 0
    # Valeur réglée à la main, sans pilote : gardée au redémarrage
    await set_number(hass, e, "charge_power_limit", 700)
    # Valeur d'un pilote dont la déclaration a expiré pendant l'arrêt : non restaurée
    ext.async_set(True, "Pilote de test", ["excluded_power"])
    await set_number(hass, e, "excluded_power", 900)
    remember(hass, e, ("charge_power_limit", "excluded_power"))
    uid = w.entity(hass, e, "excluded_power").unique_id
    stubs.RESTORE_ATTRS[uid]["set_by_until"] = "2000-01-01T00:00:00+00:00"
    await hass.config_entries.async_reload(e.entry_id)
    reg = e.runtime_data.regulator
    assert reg.charge_power_limit == 700 and reg.excluded_power == 0, (reg.charge_power_limit, reg.excluded_power)
    ok("Pilote qui ne renouvelle pas : plafond de décharge 0 W levé après 30 min ; retrait = remise à 0 ; "
       "valeur manuelle (700 W) gardée au redémarrage, valeur d'un pilote expiré non restaurée")


async def s_no_flash_writes(loop):
    """Écrire les commandes toutes les minutes ne provoque aucune écriture en mémoire flash."""
    hass, integ, bats, entries, _ = await w.setup(loop, {ACP: SPECS[ACP]})
    e = entries[ACP]
    world = w.World(loop, hass, bats, seed=8)
    world.load, world.solar = 400, 1900
    world.start()
    await select(hass, e, "operating_mode", "smart")
    flash: list[dict] = []
    api = e.runtime_data.api
    orig = api.async_write

    async def spy(sn, props):
        if "smartMode" not in props or props.get("smartMode") != 1:
            flash.append(props)
        await orig(sn, props)

    api.async_write = spy
    for i in range(10):
        await set_number(hass, e, "charge_power_limit", 300 + 100 * i)
        await set_number(hass, e, "excluded_power", 100 * i)
        await set_number(hass, e, "discharge_power_limit", 1000 + 50 * i)
        await asyncio.sleep(60)
    assert not flash, flash[:3]
    ok("Commandes de puissance écrites chaque minute pendant 10 min : aucune écriture hors RAM (smartMode=1)")


async def s_calibrating(loop):
    """calibrating suit socStatus ; groupe : vrai si une batterie calibre ; alerte après 72 h."""
    stubs.ISSUES.clear()
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": [AC, ACP], "options": {}})
    cal = w.entity(hass, entries[AC], "calibrating")
    gcal = w.entity(hass, g, "calibrating")
    assert cal.is_on is False and gcal.is_on is False
    bats[AC].soc_status = 1
    await entries[AC].runtime_data.async_refresh()
    assert cal.is_on is True and gcal.is_on is True
    assert gcal.extra_state_attributes["batteries"] == [entries[AC].title]
    await asyncio.sleep(73 * 3600)
    await entries[AC].runtime_data.async_refresh()
    assert any(i.startswith("calibration_stuck") for i in stubs.ISSUES), stubs.ISSUES
    bats[AC].soc_status = 0
    await entries[AC].runtime_data.async_refresh()
    assert cal.is_on is False and not any(i.startswith("calibration_stuck") for i in stubs.ISSUES)
    assert w.entity(hass, entries[AC], "calibration_time").native_value == 43200
    ok("Calibration : suit socStatus, groupe vrai avec la liste des batteries, alerte Réparations après 72 h, levée à la fin")


SCENARIOS = [
    s_single_battery_unchanged, s_grid_charge_target_and_import, s_restart_persistence, s_circuit_limit,
    s_group_soc_balance_converges, s_simultaneous, s_priority_switchover, s_degraded,
    s_member_settings_and_leave, s_leave_and_delete, s_group_slow_meter_no_reversal,
    s_caps_default_no_effect, s_charge_cap, s_discharge_cap_zero, s_group_charge_cap, s_excluded_power,
    s_pilot_expiry_and_manual_restart, s_no_flash_writes, s_calibrating,
]

if __name__ == "__main__":
    import sys
    only = sys.argv[1:]
    for sc in SCENARIOS:
        if only and sc.__name__ not in only:
            continue
        w.run(sc)
    print(f"\n{len(RESULTS)} vérifications OK")
