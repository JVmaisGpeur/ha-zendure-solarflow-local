"""Assistant de configuration : saisie de l'IP ou découverte automatique."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # HA >= 2025.1
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover - anciennes versions
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .api import ZendureApi, ZendureError
from .const import (
    CONF_DEADBAND,
    CONF_FAST_SCAN,
    CONF_GRID_SENSOR,
    CONF_IMPORT_LIMIT,
    CONF_INVERT_GRID,
    CONF_MAX_POWER,
    CONF_MAX_SOC,
    CONF_MIN_INTERVAL,
    CONF_MIN_SOC,
    CONF_SCAN_INTERVAL,
    CONF_SOLAR_SENSOR,
    CONF_TARGET,
    CONF_USE_RAM,
    DEFAULT_DEADBAND,
    DEFAULT_FAST_SCAN,
    DEFAULT_IMPORT_LIMIT,
    DEFAULT_MAX_POWER,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TARGET,
    DEFAULT_USE_RAM,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    pretty_model,
)


def _title(report: dict[str, Any]) -> str:
    return f"Zendure {pretty_model(report.get('product'))}"


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
    """Options : niveaux de charge, lecture, régulation."""

    def _coordinator(self):
        entry = self.config_entry
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
        return None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        coordinator = self._coordinator()
        if user_input is not None:
            data = dict(user_input)
            # Les niveaux de charge vont dans la batterie, pas dans les options
            min_soc, max_soc = data.pop(CONF_MIN_SOC, None), data.pop(CONF_MAX_SOC, None)
            if coordinator is not None:
                props = coordinator.props
                write = {}
                if min_soc is not None and int(min_soc) * 10 != props.get("minSoc"):
                    write["minSoc"] = int(min_soc) * 10
                if max_soc is not None and int(max_soc) * 10 != props.get("socSet"):
                    write["socSet"] = int(max_soc) * 10
                if write:
                    try:
                        await coordinator.async_write(write)
                    except HomeAssistantError:
                        errors["base"] = "write_failed"
            if not errors:
                return self.async_create_entry(data=data)

        opts = self.config_entry.options
        fields: dict = {}
        if coordinator is not None:
            props = coordinator.props
            cur_min = round((props.get("minSoc") or 100) / 10)
            cur_max = round((props.get("socSet") or 1000) / 10)
            fields[vol.Required(CONF_MIN_SOC, default=cur_min)] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=50, step=1, unit_of_measurement="%", mode="box")
            )
            fields[vol.Required(CONF_MAX_SOC, default=cur_max)] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=70, max=100, step=1, unit_of_measurement="%", mode="box")
            )
        schema = vol.Schema(
            {
                **fields,
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
                vol.Optional(
                    CONF_SOLAR_SENSOR,
                    description={"suggested_value": opts.get(CONF_SOLAR_SENSOR)},
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
                vol.Required(
                    CONF_FAST_SCAN, default=opts.get(CONF_FAST_SCAN, DEFAULT_FAST_SCAN)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
