"""Assistant de configuration : saisie de l'IP ou découverte automatique."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # HA >= 2025.1
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover - anciennes versions
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .api import ZendureApi, ZendureError
from .const import (
    CONF_DEADBAND,
    CONF_GRID_SENSOR,
    CONF_IMPORT_LIMIT,
    CONF_INVERT_GRID,
    CONF_MAX_POWER,
    CONF_MIN_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_TARGET,
    CONF_USE_RAM,
    DEFAULT_DEADBAND,
    DEFAULT_IMPORT_LIMIT,
    DEFAULT_MAX_POWER,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TARGET,
    DEFAULT_USE_RAM,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


def _title(report: dict[str, Any]) -> str:
    product = report.get("product") or "SolarFlow"
    return f"Zendure {product}"


class ZendureConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configuration d'une batterie Zendure."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._report: dict[str, Any] = {}

    async def _async_probe(self, host: str) -> dict[str, Any]:
        api = ZendureApi(async_get_clientsession(self.hass), host)
        return await api.async_get_report()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                report = await self._async_probe(host)
            except ZendureError:
                errors["base"] = "cannot_connect"
            else:
                sn = report.get("sn")
                if not sn:
                    errors["base"] = "no_serial"
                else:
                    await self.async_set_unique_id(sn)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    return self.async_create_entry(title=_title(report), data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        host = str(discovery_info.host)
        try:
            report = await self._async_probe(host)
        except ZendureError:
            return self.async_abort(reason="cannot_connect")
        sn = report.get("sn")
        if not sn:
            return self.async_abort(reason="no_serial")
        await self.async_set_unique_id(sn)
        # Si l'IP a changé (DHCP), on la met à jour automatiquement
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._host, self._report = host, report
        self.context["title_placeholders"] = {"name": _title(report)}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=_title(self._report), data={CONF_HOST: self._host})
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": _title(self._report), "host": self._host or ""},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return ZendureOptionsFlow()


class ZendureOptionsFlow(OptionsFlow):
    """Options : fréquence de lecture, puissance max, écriture en RAM."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                vol.Required(
                    CONF_MAX_POWER, default=opts.get(CONF_MAX_POWER, DEFAULT_MAX_POWER)
                ): vol.All(vol.Coerce(int), vol.Range(min=100, max=5000)),
                vol.Required(
                    CONF_USE_RAM, default=opts.get(CONF_USE_RAM, DEFAULT_USE_RAM)
                ): bool,
                # --- Zéro injection ---
                vol.Optional(
                    CONF_GRID_SENSOR,
                    description={"suggested_value": opts.get(CONF_GRID_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Required(
                    CONF_INVERT_GRID, default=opts.get(CONF_INVERT_GRID, False)
                ): bool,
                vol.Required(
                    CONF_TARGET, default=opts.get(CONF_TARGET, DEFAULT_TARGET)
                ): vol.All(vol.Coerce(int), vol.Range(min=-1000, max=1000)),
                vol.Required(
                    CONF_IMPORT_LIMIT, default=opts.get(CONF_IMPORT_LIMIT, DEFAULT_IMPORT_LIMIT)
                ): vol.All(vol.Coerce(int), vol.Range(min=500, max=36000)),
                vol.Required(
                    CONF_DEADBAND, default=opts.get(CONF_DEADBAND, DEFAULT_DEADBAND)
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
                vol.Required(
                    CONF_MIN_INTERVAL, default=opts.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
