"""Chargement réel dans Home Assistant : assistant, entités, options, groupe.

Les batteries sont simulées (API locale remplacée) : aucun accès réseau.
Ignoré si Home Assistant et pytest-homeassistant-custom-component ne sont pas installés
(lancé par le job CI « home-assistant », sous Linux).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

import voluptuous_serialize  # noqa: E402
from homeassistant import config_entries  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.helpers import config_validation as cv  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

DOMAIN = "zendure_local"
REPO_COMPONENTS = str(Path(__file__).resolve().parent.parent / "custom_components")

# Adresses réservées à la documentation (RFC 5737) et numéros de série fictifs
BATTERIES = {
    "192.0.2.10": {"sn": "TESTSN0001", "product": "solarFlow2400AC+"},
    "192.0.2.11": {"sn": "TESTSN0002", "product": "solarFlow800Pro"},
}
WRITES: list[tuple[str, dict]] = []


def _report(host: str) -> dict:
    b = BATTERIES[host]
    return {
        "sn": b["sn"], "product": b["product"], "version": 4,
        "properties": {
            "electricLevel": 55, "minSoc": 100, "socSet": 1000,
            "outputHomePower": 0, "gridInputPower": 0, "packInputPower": 0, "outputPackPower": 0,
            "acMode": 1, "inputLimit": 0, "outputLimit": 0, "chargeMaxLimit": 2400,
            "inverseMaxPower": 2400, "chargeAvailPower": 0, "dischargeAvailPower": 0,
            "derateFlag": 0, "is_error": 0, "hyperTmp": 3031, "packNum": 1,
            "remainOutTime": 59940, "packState": 0, "socStatus": 0, "batCalTime": 43200,
        },
        "packData": [{"sn": "P0", "packType": 500, "socLevel": 55, "maxTemp": 2971,
                      "totalVol": 5080, "batcur": 0, "maxVol": 340, "minVol": 334}],
    }


async def _fake_get_report(self) -> dict:
    return _report(self.host)


async def _fake_write(self, sn: str, properties: dict) -> None:
    WRITES.append((sn, dict(properties)))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations, mock_async_zeroconf, hass):
    """L'historique (recorder) doit être prêt avant Home Assistant ; zeroconf est simulé.

    L'outil de test charge son propre paquet custom_components : on y ajoute le nôtre.
    """
    import custom_components
    from homeassistant import loader

    if REPO_COMPONENTS not in list(custom_components.__path__):
        custom_components.__path__.append(REPO_COMPONENTS)
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    WRITES.clear()
    from custom_components.zendure_local.api import ZendureApi

    with (
        patch.object(ZendureApi, "async_get_report", _fake_get_report),
        patch.object(ZendureApi, "async_write", _fake_write),
        patch("custom_components.zendure_local.config_flow.async_find_batteries", AsyncMock(return_value=[])),
    ):
        yield


def _ecran(r, step_id: str | None = None):
    """Vérifie l'écran affiché et sérialise son formulaire comme le fait l'interface."""
    if step_id is not None:
        assert r.get("step_id") == step_id, (r.get("step_id"), r.get("errors"), r.get("reason"))
    if r["type"] is FlowResultType.FORM:
        assert not r.get("errors"), r["errors"]
        if r.get("data_schema") is not None:
            voluptuous_serialize.convert(r["data_schema"], custom_serializer=cv.custom_serializer)
    return r


def _capteurs_fictifs(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.puissance_reseau", "350", {"device_class": "power", "unit_of_measurement": "W"})
    hass.states.async_set("sensor.production_solaire", "0", {"device_class": "power", "unit_of_measurement": "W"})


async def _ajouter_batterie(hass: HomeAssistant, host: str):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "user"
    assert "battery" in r["menu_options"]
    r = _ecran(await flow.async_configure(r["flow_id"], {"next_step_id": "battery"}), "battery")
    r = _ecran(await flow.async_configure(r["flow_id"], {"host": host}), "sensors")
    r = await flow.async_configure(r["flow_id"], {
        "grid_sensor": "sensor.puissance_reseau", "invert_grid": False,
        "solar_sensor": "sensor.production_solaire"})
    assert r["type"] is FlowResultType.CREATE_ENTRY, r
    await hass.async_block_till_done()
    return r["result"]


def _entites(hass: HomeAssistant, entry) -> dict[str, str]:
    reg = er.async_get(hass)
    return {e.unique_id: e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}


async def _tout_decharger(hass: HomeAssistant) -> None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is config_entries.ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_batterie_assistant_et_chargement(hass: HomeAssistant) -> None:
    _capteurs_fictifs(hass)
    entry = await _ajouter_batterie(hass, "192.0.2.10")
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.unique_id == "TESTSN0001"
    assert entry.title == "Zendure SolarFlow 2400 AC Plus"

    ents = _entites(hass, entry)
    assert len(ents) > 10, sorted(ents)
    soc = [e for u, e in ents.items() if u.startswith("TESTSN0001_") and "level" in u.lower()]
    assert soc, sorted(ents)
    etat = hass.states.get(soc[0])
    assert etat is not None and float(etat.state) == 55, etat
    assert hass.services.has_service(DOMAIN, "set_external_control")

    # Même batterie une seconde fois : refusée
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "battery"})
    r = await flow.async_configure(r["flow_id"], {"host": "192.0.2.10"})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "already_configured"
    await _tout_decharger(hass)


async def test_batterie_options(hass: HomeAssistant) -> None:
    _capteurs_fictifs(hass)
    entry = await _ajouter_batterie(hass, "192.0.2.10")
    opts = hass.config_entries.options
    r = _ecran(await opts.async_init(entry.entry_id), "init")
    noms = {str(k) for k in r["data_schema"].schema}
    assert {"min_soc", "max_soc", "limits", "advanced"} <= noms, noms

    r = await opts.async_configure(r["flow_id"], {
        "min_soc": 15, "max_soc": 100, "grid_sensor": "sensor.puissance_reseau", "invert_grid": False,
        "limits": {"max_charge_power": 1200, "capacity": 2.4}, "advanced": {}})
    assert r["type"] is FlowResultType.CREATE_ENTRY, r
    await hass.async_block_till_done()
    assert ("TESTSN0001", {"minSoc": 150}) in WRITES, WRITES
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert entry.options["max_charge_power"] == 1200
    assert entry.options["scan_interval"] == 10
    assert entry.state is config_entries.ConfigEntryState.LOADED
    await _tout_decharger(hass)


async def test_groupe_assistant_et_options(hass: HomeAssistant) -> None:
    _capteurs_fictifs(hass)
    b1 = await _ajouter_batterie(hass, "192.0.2.10")
    b2 = await _ajouter_batterie(hass, "192.0.2.11")

    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert "group" in r["menu_options"], r["menu_options"]
    r = _ecran(await flow.async_configure(r["flow_id"], {"next_step_id": "group"}), "group")
    r = await flow.async_configure(r["flow_id"], {"name": "Batteries", "members": [b1.entry_id, b2.entry_id]})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "circuit"
    r = _ecran(await flow.async_configure(r["flow_id"], {"next_step_id": "circuit_shared"}), "circuit_shared")
    r = _ecran(await flow.async_configure(r["flow_id"], {"circuit_preset": "3600"}), "sensors")
    r = await flow.async_configure(r["flow_id"], {"grid_sensor": "sensor.puissance_reseau", "invert_grid": False})
    assert r["type"] is FlowResultType.CREATE_ENTRY, r
    group = r["result"]
    await hass.async_block_till_done()
    assert group.state is config_entries.ConfigEntryState.LOADED
    assert group.options["circuit_a_limit"] == 3600
    assert set(group.options["circuit_a_members"]) == {b1.entry_id, b2.entry_id}
    ents = _entites(hass, group)
    assert any(u.startswith(f"group_{group.entry_id}_") for u in ents), sorted(ents)

    opts = hass.config_entries.options
    r = _ecran(await opts.async_init(group.entry_id), "init")
    r = await opts.async_configure(r["flow_id"], {
        "members": [b1.entry_id, b2.entry_id], "grid_sensor": "sensor.puissance_reseau", "invert_grid": False,
        "priority": {"priority_order_1": b2.entry_id}, "circuits": {}, "advanced": {}})
    assert r["type"] is FlowResultType.CREATE_ENTRY, r
    await hass.async_block_till_done()
    group = hass.config_entries.async_get_entry(group.entry_id)
    assert group.options["priority_order"] == [b2.entry_id]
    assert group.state is config_entries.ConfigEntryState.LOADED
    await _tout_decharger(hass)
