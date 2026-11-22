"""Contrat d'interface v1 : chaque translation_key existe sur une batterie seule et sur un groupe.

python3 tests/test_contract.py
"""
import asyncio

import sim_world as w

BOTH = {
    "operating_mode": "select", "power_setpoint": "number", "import_limit": "number", "charge_target_soc": "number",
    "electric_level": "sensor", "usable_capacity": "sensor", "available_energy": "sensor", "missing_energy": "sensor",
    "battery_power": "sensor", "max_charge_power": "sensor", "max_discharge_power": "sensor", "regulation_state": "sensor",
}
GROUP_ONLY = {"strategy": "select", "active_batteries": "sensor"}

SPECS = {
    "10.0.0.1": dict(sn="AC001", product="solarFlow2400AC", packs=[5, 5, 5], soc=60, min_soc=5, charge_max=1200, discharge_max=1200),
    "10.0.0.2": dict(sn="ACP01", product="solarFlow2400AC+", packs=[500, 350, 300, 350, 300], soc=40, min_soc=9),
}


def keys(hass, entry):
    return {(e.translation_key, e.platform_name) for e in hass.entities[entry.entry_id]}


async def scenario(loop):
    hass, integ, bats, entries, g = await w.setup(loop, SPECS, group={"hosts": list(SPECS)})
    battery = keys(hass, entries["10.0.0.1"])
    group = keys(hass, g)
    for k, plat in BOTH.items():
        assert (k, plat) in battery, f"batterie : {k} ({plat}) absent"
        assert (k, plat) in group, f"groupe : {k} ({plat}) absent"
    for k, plat in GROUP_ONLY.items():
        assert (k, plat) in group, f"groupe : {k} absent"
        assert (k, plat) not in battery, f"batterie : {k} ne doit pas exister"
    # Valeurs d'enum
    mode_b = w.entity(hass, entries["10.0.0.1"], "operating_mode")
    mode_g = w.entity(hass, g, "operating_mode")
    assert "group" in mode_b.options and "group" not in mode_g.options
    assert set(w.entity(hass, g, "strategy").options) == {"simultaneous", "soc_balance", "priority"}
    rs_g = w.entity(hass, g, "regulation_state")
    assert "degraded" in rs_g.options and "degraded" not in w.entity(hass, entries["10.0.0.1"], "regulation_state").options
    # unique_id : <numéro de série>_<clé> pour une batterie (inchangé depuis v1.0)
    for e in hass.entities[entries["10.0.0.1"].entry_id]:
        assert e.unique_id.startswith("AC001_"), e.unique_id
    # Capacités Z2 (d'après packType)
    cap_ac = w.entity(hass, entries["10.0.0.1"], "usable_capacity").native_value
    cap_acp = w.entity(hass, entries["10.0.0.2"], "usable_capacity").native_value
    cap_g = w.entity(hass, g, "usable_capacity").native_value
    assert cap_ac == 8.64 and cap_acp == 12.0 and abs(cap_g - 20.64) < 1e-6, (cap_ac, cap_acp, cap_g)
    print(f"capacités : 2400 AC {cap_ac} kWh, 2400 AC+ {cap_acp} kWh, groupe {cap_g} kWh")
    print(f"batterie : {len(battery)} entités, groupe : {len(group)} entités")
    await asyncio.sleep(1)


if __name__ == "__main__":
    w.run(scenario)
    print("Contrat d'interface : OK (batterie seule et groupe)")
