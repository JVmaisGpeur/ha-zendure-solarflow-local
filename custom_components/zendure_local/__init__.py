"""Intégration Home Assistant : Zendure SolarFlow en local (zenSDK)."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import ZendureApi
from .const import DOMAIN, PLATFORMS
from .coordinator import ZendureCoordinator
from .regulator import ZendureRegulator

type ZendureConfigEntry = ConfigEntry[ZendureCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = f"/{DOMAIN}/zendure-solarflow-card.js"
CARD_FILE = Path(__file__).parent / "frontend" / "zendure-solarflow-card.js"


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
    api = ZendureApi(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = ZendureCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    coordinator.regulator = ZendureRegulator(hass, coordinator)
    await coordinator.regulator.async_load()
    entry.async_on_unload(coordinator.regulator.shutdown)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZendureConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ZendureConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
