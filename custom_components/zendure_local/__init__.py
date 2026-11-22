"""Intégration Home Assistant : Zendure SolarFlow en local (zenSDK).

Deux types d'entrées :
- une batterie (entry_type absent ou « battery ») : coordinateur + régulateur ;
- un groupe de batteries (entry_type « group ») : hub qui répartit la consigne entre
  2 à 4 batteries déjà ajoutées, piloté par son propre régulateur.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import ZendureApi
from .const import (
    CONF_CAPACITY,
    CONF_ENTRY_TYPE,
    pretty_model,
    DATA_PREVIOUS_MODES,
    DOMAIN,
    ENTRY_TYPE_GROUP,
    MODE_GROUP,
    MODE_MANUAL,
    PLATFORMS,
)
from .coordinator import ZendureCoordinator
from .group import ZendureGroupHub, group_members, member_coordinator
from .regulator import ZendureRegulator

_LOGGER = logging.getLogger(__name__)

type ZendureConfigEntry = ConfigEntry[ZendureCoordinator | ZendureGroupHub]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = f"/{DOMAIN}/zendure-solarflow-card.js"
CARD_FILE = Path(__file__).parent / "frontend" / "zendure-solarflow-card.js"


def is_group_entry(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GROUP


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Sert la carte Lovelace et la charge automatiquement dans l'interface."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    # ?v=… force le navigateur à recharger la carte après une mise à jour
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ZendureConfigEntry) -> bool:
    if is_group_entry(entry):
        return await _async_setup_group(hass, entry)
    api = ZendureApi(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = ZendureCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    _check_pack_types(hass, entry, coordinator)
    coordinator.regulator = ZendureRegulator(hass, coordinator)
    await coordinator.regulator.async_load()
    entry.async_on_unload(coordinator.regulator.shutdown)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _check_pack_types(hass: HomeAssistant, entry: ConfigEntry, coordinator: ZendureCoordinator) -> None:
    """Z2 : un type de pack inconnu → alerte, sauf si la capacité est saisie dans les options."""
    issue_id = f"unknown_pack_{entry.entry_id}"
    _ = coordinator.usable_capacity  # met à jour unknown_pack_types
    if coordinator.unknown_pack_types and not entry.options.get(CONF_CAPACITY):
        ir.async_create_issue(
            hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key="unknown_pack_type",
            translation_placeholders={
                "battery": f"Zendure {pretty_model((coordinator.data or {}).get('product'))}",
                "types": ", ".join(str(t) for t in sorted(coordinator.unknown_pack_types)),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


async def _async_setup_group(hass: HomeAssistant, entry: ZendureConfigEntry) -> bool:
    hub = ZendureGroupHub(hass, entry)
    hub.regulator = ZendureRegulator(hass, hub)
    await hub.regulator.async_load()
    entry.runtime_data = hub
    await _async_sync_members(hass, entry)
    hub.start()
    entry.async_on_unload(hub.shutdown)
    entry.async_on_unload(hub.regulator.shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_set_battery_mode(hass: HomeAssistant, entry_id: str, mode: str) -> None:
    c = member_coordinator(hass, entry_id)
    if c is None or c.regulator is None:
        return
    try:
        await c.regulator.async_set_mode(mode)
    except HomeAssistantError:
        await c.regulator.async_set_mode(MODE_MANUAL, apply=False)


async def _async_sync_members(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """G4 / G5 : passe les nouvelles batteries en « Pilotée par le groupe » et rend aux
    batteries retirées le mode qu'elles avaient avant d'entrer dans le groupe."""
    previous: dict[str, str] = dict(entry.data.get(DATA_PREVIOUS_MODES, {}))
    members = group_members(entry)
    changed = False
    for eid in members:
        if eid in previous:
            continue
        c = member_coordinator(hass, eid)
        previous[eid] = c.regulator.mode if c is not None and c.regulator is not None else MODE_MANUAL
        if previous[eid] == MODE_GROUP:
            previous[eid] = MODE_MANUAL
        await _async_set_battery_mode(hass, eid, MODE_GROUP)
        changed = True
    for eid in [e for e in previous if e not in members]:
        c = member_coordinator(hass, eid)
        if c is not None and c.regulator is not None and c.regulator.mode == MODE_GROUP:
            await _async_set_battery_mode(hass, eid, previous[eid])
        del previous[eid]
        changed = True
    if changed:
        hass.config_entries.async_update_entry(entry, data={**entry.data, DATA_PREVIOUS_MODES: previous})


async def async_unload_entry(hass: HomeAssistant, entry: ZendureConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Suppression d'un groupe : chaque batterie retrouve son mode d'avant (G5)."""
    if is_group_entry(entry):
        for eid, mode in dict(entry.data.get(DATA_PREVIOUS_MODES, {})).items():
            c = member_coordinator(hass, eid)
            if c is not None and c.regulator is not None and c.regulator.mode == MODE_GROUP:
                await _async_set_battery_mode(hass, eid, mode)
    else:
        ir.async_delete_issue(hass, DOMAIN, f"unknown_pack_{entry.entry_id}")


async def _async_reload(hass: HomeAssistant, entry: ZendureConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
