"""Coordinateur : interroge la batterie à intervalle régulier."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ZendureApi, ZendureError
from .const import (
    AC_MODE_CHARGE,
    AC_MODE_DISCHARGE,
    CONF_MAX_POWER,
    CONF_SCAN_INTERVAL,
    CONF_USE_RAM,
    DEFAULT_MAX_POWER,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USE_RAM,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ZendureCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Récupère le rapport complet de la batterie."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ZendureApi) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {api.host}",
            update_interval=timedelta(seconds=interval),
            # Relecture quasi immédiate après chaque commande
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=0.5, immediate=True),
        )
        self.normal_interval = timedelta(seconds=interval)
        self.api = api
        self.sn: str = entry.unique_id or ""
        # Dernière consigne envoyée via l'entité « Consigne de puissance »
        self.power_setpoint: float = 0
        self.regulator = None  # ZendureRegulator, créé dans __init__.py

    @property
    def max_power(self) -> int:
        return int(self.config_entry.options.get(CONF_MAX_POWER, DEFAULT_MAX_POWER))

    @property
    def use_ram(self) -> bool:
        return bool(self.config_entry.options.get(CONF_USE_RAM, DEFAULT_USE_RAM))

    @property
    def props(self) -> dict[str, Any]:
        return (self.data or {}).get("properties", {})

    @property
    def battery_ac_power(self) -> float | None:
        """Puissance AC réelle de la batterie : + décharge vers la maison, − charge."""
        p = self.props
        out, inp = p.get("outputHomePower"), p.get("gridInputPower")
        if out is None and inp is None:
            return None
        return float(out or 0) - float(inp or 0)

    @property
    def packs(self) -> list[dict[str, Any]]:
        return (self.data or {}).get("packData", []) or []

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.async_get_report()
        except ZendureError as err:
            raise UpdateFailed(str(err)) from err
        if not self.sn and data.get("sn"):
            self.sn = data["sn"]
        return data

    # ------------------------------------------------------------------ écriture
    async def async_write(self, properties: dict[str, Any], *, volatile: bool = False) -> None:
        """Écrit des propriétés puis met à jour l'état local et rafraîchit.

        volatile=True : commandes fréquentes (puissance, mode) écrites en RAM
        (smartMode=1) pour ne pas user la mémoire flash, si l'option est active.
        """
        props = dict(properties)
        if volatile and self.use_ram:
            props["smartMode"] = 1
        try:
            await self.api.async_write(self.sn, props)
        except ZendureError as err:
            raise HomeAssistantError(str(err)) from err
        # Mise à jour optimiste, la lecture suivante confirmera
        if self.data is not None:
            self.data.setdefault("properties", {}).update(props)
            self.async_update_listeners()
        await self.async_request_refresh()

    async def async_set_power(self, watts: float) -> None:
        """Consigne unique : >0 décharge vers la maison, <0 charge, 0 = repos."""
        watts = max(-self.max_power, min(self.max_power, int(round(watts))))
        if watts > 0:
            props = {"acMode": AC_MODE_DISCHARGE, "outputLimit": watts, "inputLimit": 0}
        elif watts < 0:
            props = {"acMode": AC_MODE_CHARGE, "inputLimit": -watts, "outputLimit": 0}
        else:
            props = {"inputLimit": 0, "outputLimit": 0}
        await self.async_write(props, volatile=True)
        self.power_setpoint = watts
        self.async_update_listeners()
