"""Assistant de configuration : batterie (IP ou découverte) ou groupe de batteries."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # HA >= 2025.1
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover - anciennes versions
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .api import ZendureApi, ZendureError
from .discovery import async_energy_sensors, async_find_batteries
from .const import (
    CONF_CAPACITY,
    CONF_CIRCUIT_A_CHARGE_LIMIT,
    CONF_CIRCUIT_A_LIMIT,
    CONF_CIRCUIT_A_MEMBERS,
    CONF_CIRCUIT_B_CHARGE_LIMIT,
    CONF_CIRCUIT_B_LIMIT,
    CIRCUIT_PRESET_CUSTOM,
    CIRCUIT_PRESETS,
    CONF_CIRCUIT_B_MEMBERS,
    CONF_CIRCUIT_LIMIT,
    CONF_DEADBAND,
    CONF_ENTRY_TYPE,
    CONF_FAST_SCAN,
    CONF_GRID_SENSOR,
    CONF_IMPORT_LIMIT,
    CONF_INVERT_GRID,
    CONF_MAX_CHARGE_POWER,
    CONF_MAX_DISCHARGE_POWER,
    CONF_MAX_POWER,
    CONF_MAX_SOC,
    CONF_MEMBERS,
    CONF_MIN_INTERVAL,
    CONF_MIN_SOC,
    CONF_NAME,
    CONF_PRIORITY,
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
    ENTRY_TYPE_GROUP,
    MAX_IMPORT_LIMIT,
    MAX_MEMBERS,
    MAX_SCAN_INTERVAL,
    MIN_MEMBERS,
    MIN_SCAN_INTERVAL,
    pretty_model,
)

CONF_SERIALS = "serials"
CONF_CREATE_GROUP = "create_group"
CONF_CIRCUIT_PRESET = "circuit_preset"
DEFAULT_GROUP_NAME = "Batteries"
PRIORITY_KEYS = [f"{CONF_PRIORITY}_{i}" for i in range(1, MAX_MEMBERS + 1)]


def _title(report: dict[str, Any]) -> str:
    return f"Zendure {pretty_model(report.get('product'))}"


def _is_group(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GROUP


def _members_of(entry: ConfigEntry) -> list[str]:
    return list(entry.options.get(CONF_MEMBERS) or entry.data.get(CONF_MEMBERS) or [])


def _battery_choices(hass, exclude_group: str | None = None) -> list[selector.SelectOptionDict]:
    """Batteries ajoutées qui ne sont pas déjà dans un autre groupe (G5)."""
    taken: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if _is_group(entry) and entry.entry_id != exclude_group:
            taken.update(_members_of(entry))
    return [
        selector.SelectOptionDict(value=e.entry_id, label=e.title)
        for e in hass.config_entries.async_entries(DOMAIN)
        if not _is_group(e) and e.entry_id not in taken
    ]


def _power_sensor() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power"))


def _watts(vmin: int, vmax: int, step: int = 10) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=vmin, max=vmax, step=step, unit_of_measurement="W", mode="box")
    )


SECTION_LIMITS = "limits"
SECTION_ADVANCED = "advanced"
SECTION_PRIORITY = "priority"
SECTION_CIRCUITS = "circuits"
SECTIONS = (SECTION_LIMITS, SECTION_ADVANCED, SECTION_PRIORITY, SECTION_CIRCUITS)


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Les sections repliables rangent leurs champs dans un sous-dictionnaire."""
    data: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in SECTIONS and isinstance(value, dict):
            data.update(value)
        else:
            data[key] = value
    return data


def _collapsed(fields: dict) -> section:
    return section(vol.Schema(fields), {"collapsed": True})


def _sensor_fields(opts: dict[str, Any], required: bool = False) -> dict:
    """Capteur au compteur, sens du signe, production solaire.

    Obligatoire à l'ajout ; facultatif dans les options (inutile sur une batterie
    membre d'un groupe, et les modes manuels s'en passent)."""
    grid = vol.Required if required else vol.Optional
    return {
        grid(CONF_GRID_SENSOR, description={"suggested_value": opts.get(CONF_GRID_SENSOR)}): _power_sensor(),
        vol.Required(CONF_INVERT_GRID, default=bool(opts.get(CONF_INVERT_GRID, False))): bool,
        vol.Optional(CONF_SOLAR_SENSOR, description={"suggested_value": opts.get(CONF_SOLAR_SENSOR)}): _power_sensor(),
    }


def _advanced_fields(opts: dict[str, Any]) -> dict:
    """Réglages fins de la régulation : les valeurs par défaut conviennent presque toujours."""
    return {
        vol.Required(CONF_TARGET, default=opts.get(CONF_TARGET, DEFAULT_TARGET)): vol.All(
            vol.Coerce(int), vol.Range(min=-1000, max=1000)
        ),
        vol.Required(CONF_IMPORT_LIMIT, default=opts.get(CONF_IMPORT_LIMIT, DEFAULT_IMPORT_LIMIT)): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_IMPORT_LIMIT)
        ),
        vol.Required(CONF_DEADBAND, default=opts.get(CONF_DEADBAND, DEFAULT_DEADBAND)): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=500)
        ),
        vol.Required(CONF_MIN_INTERVAL, default=opts.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=60)
        ),
        vol.Required(CONF_FAST_SCAN, default=opts.get(CONF_FAST_SCAN, DEFAULT_FAST_SCAN)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10)
        ),
    }


class ZendureConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configuration d'une batterie Zendure ou d'un groupe de batteries."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._report: dict[str, Any] = {}
        self._found: list = []
        self._pending: dict[str, Any] = {}

    async def _async_probe(self, host: str) -> dict[str, Any]:
        api = ZendureApi(async_get_clientsession(self.hass), host)
        return await api.async_get_report()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Cherche d'abord les batteries sur le réseau, puis propose quoi faire."""
        configured = {e.unique_id for e in self.hass.config_entries.async_entries(DOMAIN) if e.unique_id}
        self._found = [b for b in await async_find_batteries(self.hass) if b.sn not in configured]
        options = []
        if self._found:
            options.append("pick")
        options.append("battery")
        if len(_battery_choices(self.hass)) >= MIN_MEMBERS:
            options.append("group")
        return self.async_show_menu(
            step_id="user",
            menu_options=options,
            description_placeholders={"found": str(len(self._found))},
        )

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ajoute en une fois les batteries cochées et, si demandé, crée leur groupe."""
        by_sn = {b.sn: b for b in self._found}
        errors: dict[str, str] = {}
        if user_input is not None:
            chosen = [by_sn[sn] for sn in user_input.get(CONF_SERIALS) or [] if sn in by_sn]
            make_group = bool(user_input.get(CONF_CREATE_GROUP)) and len(chosen) > 1
            if not chosen:
                errors["base"] = "nothing_selected"
            elif make_group and len(chosen) > MAX_MEMBERS:
                errors[CONF_SERIALS] = "members_count"
            else:
                self._pending = {
                    "kind": "pick",
                    "chosen": chosen,
                    "group": make_group,
                    "name": (user_input.get(CONF_NAME) or "").strip() or DEFAULT_GROUP_NAME,
                }
                if make_group:
                    return await self.async_step_circuit()
                return await self.async_step_sensors()

        fields: dict = {
            vol.Required(CONF_SERIALS, default=list(by_sn)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=b.sn, label=f"{_title({'product': b.product})} — {b.host}")
                        for b in self._found
                    ],
                    multiple=True,
                    mode="list",
                )
            )
        }
        if len(self._found) > 1:
            fields[vol.Optional(CONF_CREATE_GROUP, default=True)] = bool
            fields[vol.Optional(CONF_NAME, default=DEFAULT_GROUP_NAME)] = str
        return self.async_show_form(step_id="pick", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """Batterie cochée dans la liste : ajoutée directement, sans autre question."""
        await self.async_set_unique_id(discovery_info["sn"], raise_on_progress=False)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info[CONF_HOST]})
        return self.async_create_entry(
            title=_title({"product": discovery_info.get("product")}),
            data={CONF_HOST: discovery_info[CONF_HOST]},
            options=dict(discovery_info.get("options") or {}),
        )

    async def async_step_battery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
                    self._pending = {"kind": "battery", "title": _title(report), "host": host}
                    return await self.async_step_sensors()

        return self.async_show_form(
            step_id="battery",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """G1 : créer un groupe à partir d'au moins deux batteries déjà ajoutées."""
        errors: dict[str, str] = {}
        choices = _battery_choices(self.hass)
        if len(choices) < MIN_MEMBERS:
            return self.async_abort(reason="not_enough_batteries")
        if user_input is not None:
            members = list(user_input.get(CONF_MEMBERS) or [])
            if not MIN_MEMBERS <= len(members) <= MAX_MEMBERS:
                errors[CONF_MEMBERS] = "members_count"
            else:
                name = user_input[CONF_NAME].strip()
                self._pending = {"kind": "group", "name": name, "members": members}
                return await self.async_step_circuit()
        return self.async_show_form(
            step_id="group",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_MEMBERS): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=choices, multiple=True, mode="list")
                    ),
                }
            ),
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

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._pending = {"kind": "battery", "title": _title(self._report), "host": self._host}
            return await self.async_step_sensors()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": _title(self._report), "host": self._host or ""},
        )

    async def async_step_circuit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Groupe : les batteries sont-elles sur le même circuit électrique ?"""
        return self.async_show_menu(step_id="circuit", menu_options=["circuit_separate", "circuit_shared"])

    async def async_step_circuit_separate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._pending.pop("circuit", None)
        return await self.async_step_sensors()

    async def async_step_circuit_shared(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Circuit commun : la somme des puissances des batteries ne le dépassera jamais."""
        errors: dict[str, str] = {}
        if user_input is not None:
            preset = user_input.get(CONF_CIRCUIT_PRESET, CIRCUIT_PRESET_CUSTOM)
            out = user_input.get(CONF_CIRCUIT_A_LIMIT)
            charge = user_input.get(CONF_CIRCUIT_A_CHARGE_LIMIT)
            if preset in CIRCUIT_PRESETS and not out and not charge:
                out, charge = CIRCUIT_PRESETS[preset]
            if not out:
                errors[CONF_CIRCUIT_A_LIMIT] = "circuit_limit"
            else:
                self._pending["circuit"] = (int(out), int(charge or out))
                return await self.async_step_sensors()
        return self.async_show_form(
            step_id="circuit_shared",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CIRCUIT_PRESET, default="3600"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[*CIRCUIT_PRESETS, CIRCUIT_PRESET_CUSTOM],
                            mode="dropdown",
                            translation_key="circuit_preset",
                        )
                    ),
                    vol.Optional(CONF_CIRCUIT_A_LIMIT): _watts(0, 20000),
                    vol.Optional(CONF_CIRCUIT_A_CHARGE_LIMIT): _watts(0, 20000),
                }
            ),
            errors=errors,
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Capteur de puissance au compteur (obligatoire) et production solaire (facultative)."""
        if user_input is not None:
            options = {
                CONF_GRID_SENSOR: user_input[CONF_GRID_SENSOR],
                CONF_INVERT_GRID: bool(user_input.get(CONF_INVERT_GRID, False)),
            }
            if user_input.get(CONF_SOLAR_SENSOR):
                options[CONF_SOLAR_SENSOR] = user_input[CONF_SOLAR_SENSOR]
            return await self._async_finish(options)
        # Pré-remplis d'après le tableau de bord Énergie, s'il est configuré
        sugg = await async_energy_sensors(self.hass)
        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(_sensor_fields(sugg, required=True)),
        )

    async def _async_finish(self, options: dict[str, Any]) -> ConfigFlowResult:
        pending = self._pending
        kind = pending["kind"]
        if kind == "battery":
            return self.async_create_entry(title=pending["title"], data={CONF_HOST: pending["host"]}, options=options)
        if kind == "group":
            return self._create_group(pending["name"], pending["members"], options)
        # kind == "pick"
        chosen = pending["chosen"]
        if pending["group"]:
            # Chaque batterie a sa propre entrée, puis cet assistant crée le groupe.
            # Les capteurs vont sur le groupe : c'est lui qui régule.
            members: list[str] = []
            for bat in chosen:
                result = await self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_INTEGRATION_DISCOVERY},
                    data={CONF_HOST: bat.host, "sn": bat.sn, "product": bat.product},
                )
                entry = result.get("result")
                if entry is None:  # déjà configurée : on reprend l'entrée existante
                    entry = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, bat.sn)
                if entry is not None:
                    members.append(entry.entry_id)
            taken = {m for e in self.hass.config_entries.async_entries(DOMAIN) if _is_group(e) for m in _members_of(e)}
            members = [m for m in members if m not in taken]
            if len(members) < MIN_MEMBERS:
                return self.async_abort(reason="not_enough_batteries")
            return self._create_group(pending["name"], members, options)
        first, others = chosen[0], chosen[1:]
        for bat in others:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_INTEGRATION_DISCOVERY},
                    data={CONF_HOST: bat.host, "sn": bat.sn, "product": bat.product, "options": options},
                )
            )
        await self.async_set_unique_id(first.sn, raise_on_progress=False)
        self._abort_if_unique_id_configured(updates={CONF_HOST: first.host})
        return self.async_create_entry(
            title=_title({"product": first.product}), data={CONF_HOST: first.host}, options=options
        )

    def _create_group(self, name: str, members: list[str], options: dict[str, Any]) -> ConfigFlowResult:
        options = dict(options)
        if circuit := self._pending.get("circuit"):
            # Toutes les batteries du groupe sur un même circuit (circuit partagé A)
            options[CONF_CIRCUIT_A_MEMBERS] = list(members)
            options[CONF_CIRCUIT_A_LIMIT], options[CONF_CIRCUIT_A_CHARGE_LIMIT] = circuit
        return self.async_create_entry(
            title=name,
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_GROUP, CONF_NAME: name, CONF_MEMBERS: members},
            options=options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return ZendureGroupOptionsFlow() if _is_group(config_entry) else ZendureOptionsFlow()


class ZendureOptionsFlow(OptionsFlow):
    """Options d'une batterie : niveaux de charge, limites, lecture, régulation."""

    def _coordinator(self):
        entry = self.config_entry
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
        return None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        coordinator = self._coordinator()
        if user_input is not None:
            data = _flatten(user_input)
            # Les niveaux de charge vont dans la batterie, pas dans les options
            min_soc, max_soc = data.pop(CONF_MIN_SOC, None), data.pop(CONF_MAX_SOC, None)
            data.pop(CONF_MAX_POWER, None)  # ancienne option unique, remplacée
            # Vide = valeur de l'app Zendure / pas de limite / capacité calculée
            for key in (CONF_MAX_CHARGE_POWER, CONF_MAX_DISCHARGE_POWER, CONF_CIRCUIT_LIMIT, CONF_CAPACITY):
                if not data.get(key):
                    data.pop(key, None)
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
        main: dict = {}
        app_charge = app_discharge = None
        if coordinator is not None:
            props = coordinator.props
            app_charge, app_discharge = coordinator.app_charge_limit, coordinator.app_discharge_limit
            main[vol.Required(CONF_MIN_SOC, default=round((props.get("minSoc") or 100) / 10))] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=50, step=1, unit_of_measurement="%", mode="box")
            )
            main[vol.Required(CONF_MAX_SOC, default=round((props.get("socSet") or 1000) / 10))] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=70, max=100, step=1, unit_of_measurement="%", mode="box")
            )
        main.update(_sensor_fields(opts))
        def _power_opt(key: str):
            # 3000 W était la valeur par défaut des versions précédentes : vide = app Zendure
            v = opts.get(key, opts.get(CONF_MAX_POWER))
            return None if v in (None, DEFAULT_MAX_POWER) else v

        limits = {
            # Vide = limites réglées dans l'app Zendure
            vol.Optional(
                CONF_MAX_CHARGE_POWER, description={"suggested_value": _power_opt(CONF_MAX_CHARGE_POWER)}
            ): _watts(0, 5000),
            vol.Optional(
                CONF_MAX_DISCHARGE_POWER, description={"suggested_value": _power_opt(CONF_MAX_DISCHARGE_POWER)}
            ): _watts(0, 5000),
            vol.Optional(CONF_CIRCUIT_LIMIT, description={"suggested_value": opts.get(CONF_CIRCUIT_LIMIT)}): _watts(
                0, 10000
            ),
            vol.Optional(CONF_CAPACITY, description={"suggested_value": opts.get(CONF_CAPACITY)}): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100, step=0.01, unit_of_measurement="kWh", mode="box")
            ),
        }
        advanced = {
            vol.Required(CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
            ),
            vol.Required(CONF_USE_RAM, default=opts.get(CONF_USE_RAM, DEFAULT_USE_RAM)): bool,
            **_advanced_fields(opts),
        }
        schema = vol.Schema(
            {
                **main,
                vol.Required(SECTION_LIMITS): _collapsed(limits),
                vol.Required(SECTION_ADVANCED): _collapsed(advanced),
            }
        )
        unknown = "—"
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "charge": f"{app_charge:.0f}" if app_charge else unknown,
                "discharge": f"{app_discharge:.0f}" if app_discharge else unknown,
            },
        )


class ZendureGroupOptionsFlow(OptionsFlow):
    """Options d'un groupe : membres, ordre de priorité, circuits partagés, régulation."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        opts = entry.options
        choices = _battery_choices(self.hass, exclude_group=entry.entry_id)
        valid = {c["value"] for c in choices}
        if user_input is not None:
            data = _flatten(user_input)
            members = [m for m in data.get(CONF_MEMBERS) or [] if m in valid]
            if not MIN_MEMBERS <= len(members) <= MAX_MEMBERS:
                errors[CONF_MEMBERS] = "members_count"
            # Ordre de priorité : champs priority_order_1..4 → liste
            order: list[str] = []
            for key in PRIORITY_KEYS:
                v = data.pop(key, None)
                if v and v in members and v not in order:
                    order.append(v)
            data[CONF_PRIORITY] = order
            for ckey in (CONF_CIRCUIT_A_CHARGE_LIMIT, CONF_CIRCUIT_B_CHARGE_LIMIT):
                if not data.get(ckey):
                    data.pop(ckey, None)  # vide = même limite qu'en sortie
            for mkey, lkey in ((CONF_CIRCUIT_A_MEMBERS, CONF_CIRCUIT_A_LIMIT), (CONF_CIRCUIT_B_MEMBERS, CONF_CIRCUIT_B_LIMIT)):
                circuit = [m for m in data.get(mkey) or [] if m in members]
                data[mkey] = circuit
                if circuit and len(circuit) < 2:
                    errors[mkey] = "circuit_members"
                if circuit and not data.get(lkey):
                    errors[lkey] = "circuit_limit"
            data[CONF_MEMBERS] = members
            if not errors:
                return self.async_create_entry(data=data)

        members_now = _members_of(entry)
        order_now = list(opts.get(CONF_PRIORITY) or members_now)
        multi = selector.SelectSelector(selector.SelectSelectorConfig(options=choices, multiple=True, mode="list"))
        single = selector.SelectSelector(selector.SelectSelectorConfig(options=choices, mode="dropdown"))
        fields: dict = {vol.Required(CONF_MEMBERS, default=members_now): multi}
        fields.update(_sensor_fields(opts))
        priority: dict = {}
        for i, key in enumerate(PRIORITY_KEYS):
            suggested = order_now[i] if i < len(order_now) else None
            priority[vol.Optional(key, description={"suggested_value": suggested})] = single
        circuits: dict = {}
        for mkey, lkey, ckey in (
            (CONF_CIRCUIT_A_MEMBERS, CONF_CIRCUIT_A_LIMIT, CONF_CIRCUIT_A_CHARGE_LIMIT),
            (CONF_CIRCUIT_B_MEMBERS, CONF_CIRCUIT_B_LIMIT, CONF_CIRCUIT_B_CHARGE_LIMIT),
        ):
            circuits[vol.Optional(mkey, description={"suggested_value": opts.get(mkey) or []})] = multi
            circuits[vol.Optional(lkey, description={"suggested_value": opts.get(lkey)})] = _watts(0, 20000)
            circuits[vol.Optional(ckey, description={"suggested_value": opts.get(ckey)})] = _watts(0, 20000)
        fields[vol.Required(SECTION_PRIORITY)] = _collapsed(priority)
        fields[vol.Required(SECTION_CIRCUITS)] = _collapsed(circuits)
        fields[vol.Required(SECTION_ADVANCED)] = _collapsed(_advanced_fields(opts))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields), errors=errors)
