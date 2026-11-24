"""Imitation minimale de Home Assistant pour faire tourner le vrai code de l'intégration.

Seul ce que l'intégration utilise est imité. Une horloge virtuelle permet de simuler
des dizaines de minutes de régulation en quelques secondes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import importlib
import pathlib
import selectors
import sys
import types
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _mod(name: str, **attrs) -> types.ModuleType:
    m = sys.modules.get(name) or types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    parent, _, child = name.rpartition(".")
    if parent:
        setattr(_mod(parent), child, m)
    return m


# ---------------------------------------------------------------- horloge virtuelle
class VirtualClockLoop(asyncio.SelectorEventLoop):
    """Boucle asyncio dont le temps avance instantanément jusqu'au prochain évènement."""

    def __init__(self) -> None:
        self.clock = 1000.0

        class Sel(selectors.DefaultSelector):
            def select(inner, timeout=None):  # noqa: N805
                if timeout:
                    self.clock += timeout
                return super(Sel, inner).select(0)

        super().__init__(Sel())

    def time(self) -> float:
        return self.clock


class FakeTime:
    def __init__(self, loop: VirtualClockLoop) -> None:
        self.loop = loop

    def monotonic(self) -> float:
        return self.loop.clock

    def time(self) -> float:
        return self.loop.clock


# ---------------------------------------------------------------- dépendances tierces
class _VolSchema:
    def __init__(self, schema, *a, **k):
        self.schema = schema

    def __call__(self, data):
        return data


def _marker(key, default=None, description=None, **k):
    return key


_mod("voluptuous", Schema=_VolSchema, Required=_marker, Optional=_marker, All=lambda *a: a[0],
     Coerce=lambda t: t, Range=lambda **k: None, In=lambda *a: None)
_mod("aiohttp", ClientTimeout=lambda **k: None, ClientError=Exception, ClientSession=object)


# ---------------------------------------------------------------- homeassistant.const / core / exceptions
class EntityCategory(enum.StrEnum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class _Units:
    def __getattr__(self, name):
        return name


_const = _mod(
    "homeassistant.const", CONF_HOST="host", STATE_UNAVAILABLE="unavailable", STATE_UNKNOWN="unknown",
    STATE_OFF="off", STATE_ON="on", PERCENTAGE="%", SIGNAL_STRENGTH_DECIBELS_MILLIWATT="dBm",
    EntityCategory=EntityCategory,
)
for _u in ("UnitOfElectricCurrent", "UnitOfElectricPotential", "UnitOfEnergy", "UnitOfPower", "UnitOfTemperature", "UnitOfTime"):
    setattr(_const, _u, types.SimpleNamespace(
        WATT="W", KILO_WATT_HOUR="kWh", VOLT="V", AMPERE="A", CELSIUS="°C", MINUTES="min", SECONDS="s"))


def callback(fn):
    return fn


class HomeAssistant:  # remplacé par FakeHass
    pass


_mod("homeassistant.core", HomeAssistant=HomeAssistant, callback=callback, CALLBACK_TYPE=object, ServiceCall=object)


class HomeAssistantError(Exception):
    def __init__(self, *args, translation_domain=None, translation_key=None, translation_placeholders=None):
        super().__init__(*args or (translation_key,))
        self.translation_key = translation_key


class ConfigEntryNotReady(HomeAssistantError):
    pass


_mod("homeassistant.exceptions", HomeAssistantError=HomeAssistantError, ConfigEntryNotReady=ConfigEntryNotReady,
     ServiceValidationError=type("ServiceValidationError", (HomeAssistantError,), {}))


# ---------------------------------------------------------------- config entries
class ConfigEntryState(enum.Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"


_entry_counter = [0]


class ConfigEntry:
    def __init__(self, domain, title, data, options=None, unique_id=None):
        _entry_counter[0] += 1
        self.entry_id = f"entry{_entry_counter[0]}"
        self.domain, self.title, self.data = domain, title, dict(data)
        self.options = dict(options or {})
        self.unique_id = unique_id
        self.state = ConfigEntryState.NOT_LOADED
        self.runtime_data = None
        self._on_unload: list = []
        self.update_listeners: list = []

    def __class_getitem__(cls, item):
        return cls

    def async_on_unload(self, fn):
        self._on_unload.append(fn)

    def add_update_listener(self, fn):
        self.update_listeners.append(fn)
        return lambda: self.update_listeners.remove(fn)


class ConfigFlow:
    def __init_subclass__(cls, **kwargs):
        pass


_mod("homeassistant.config_entries", ConfigEntry=ConfigEntry, ConfigEntryState=ConfigEntryState,
     ConfigFlow=ConfigFlow, ConfigFlowResult=dict, OptionsFlow=object)


# ---------------------------------------------------------------- helpers
_mod("homeassistant.helpers")
_mod("homeassistant.helpers.config_validation", config_entry_only_config_schema=lambda d: None,
     string=str, boolean=bool, ensure_list=lambda v: v if isinstance(v, list) else [v])
_mod("homeassistant.helpers.typing", ConfigType=dict)
_mod("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
_mod("homeassistant.loader", async_get_integration=None)
_mod("homeassistant.components")
_mod("homeassistant.components.frontend", add_extra_js_url=lambda hass, url: None)
_mod("homeassistant.components.http", StaticPathConfig=lambda *a, **k: None)
_mod("homeassistant.components.zeroconf", ZeroconfServiceInfo=object)
_mod("homeassistant.helpers.service_info")
_mod("homeassistant.helpers.service_info.zeroconf", ZeroconfServiceInfo=object)


class _SelectorAny:
    def __init__(self, *a, **k):
        pass


_mod("homeassistant.helpers.selector", **{n: _SelectorAny for n in (
    "EntitySelector", "EntitySelectorConfig", "NumberSelector", "NumberSelectorConfig",
    "SelectSelector", "SelectSelectorConfig", "SelectOptionDict")})

ISSUES: dict[str, dict] = {}


class IssueSeverity(enum.StrEnum):
    WARNING = "warning"


def async_create_issue(hass, domain, issue_id, **kw):
    ISSUES[issue_id] = kw


def async_delete_issue(hass, domain, issue_id):
    ISSUES.pop(issue_id, None)


_mod("homeassistant.helpers.issue_registry", IssueSeverity=IssueSeverity,
     async_create_issue=async_create_issue, async_delete_issue=async_delete_issue)

_DISPATCH: dict[str, list] = {}


def async_dispatcher_connect(hass, signal, target):
    _DISPATCH.setdefault(signal, []).append(target)
    return lambda: _DISPATCH[signal].remove(target)


def async_dispatcher_send(hass, signal, *args):
    for t in list(_DISPATCH.get(signal, [])):
        t(*args)


_mod("homeassistant.helpers.dispatcher", async_dispatcher_connect=async_dispatcher_connect,
     async_dispatcher_send=async_dispatcher_send)


def async_call_later(hass, delay, cb):
    h = hass.loop.call_later(delay, cb, None)
    return h.cancel


def async_track_state_change_event(hass, entities, cb):
    for e in entities:
        hass.state_listeners.setdefault(e, []).append(cb)

    def remove():
        for e in entities:
            if cb in hass.state_listeners.get(e, []):
                hass.state_listeners[e].remove(cb)

    return remove


def async_track_time_interval(hass, cb, interval):
    stop = {"v": False}

    async def run():
        while not stop["v"]:
            await asyncio.sleep(interval.total_seconds())
            if not stop["v"]:
                cb(None)

    task = hass.loop.create_task(run())

    def cancel():
        stop["v"] = True
        task.cancel()

    return cancel


def async_track_point_in_utc_time(hass, cb, when):
    delay = max(0.0, (when - __import__("homeassistant.util.dt").util.dt.utcnow()).total_seconds())
    h = hass.loop.call_later(delay, cb, when)
    return h.cancel


_mod("homeassistant.helpers.event", async_call_later=async_call_later,
     async_track_point_in_utc_time=async_track_point_in_utc_time,
     async_track_state_change_event=async_track_state_change_event,
     async_track_time_interval=async_track_time_interval)

STORE: dict[str, Any] = {}


class Store:
    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return STORE.get(self.key)

    def async_delay_save(self, fn, delay):
        STORE[self.key] = fn()

    async def async_save(self, data):
        STORE[self.key] = data


_mod("homeassistant.helpers.storage", Store=Store)


class Debouncer:
    def __init__(self, *a, **k):
        pass


_mod("homeassistant.helpers.debounce", Debouncer=Debouncer)


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __init__(self, hass, logger, config_entry=None, name=None, update_interval=None, request_refresh_debouncer=None):
        self.hass, self.config_entry, self.name = hass, config_entry, name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = False
        self._listeners: list = []
        self._task = None

    def __class_getitem__(cls, item):
        return cls

    def async_add_listener(self, cb, context=None):
        self._listeners.append(cb)
        if self._task is None:
            self._task = self.hass.loop.create_task(self._poll())
        return lambda: cb in self._listeners and self._listeners.remove(cb)

    async def _poll(self):
        while True:
            await asyncio.sleep(self.update_interval.total_seconds())
            await self.async_refresh()

    def async_update_listeners(self):
        for cb in list(self._listeners):
            cb()

    async def async_refresh(self):
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except UpdateFailed:
            self.last_update_success = False
        self.async_update_listeners()

    async def async_request_refresh(self):
        await self.async_refresh()

    async def async_config_entry_first_refresh(self):
        await self.async_refresh()
        if not self.last_update_success:
            raise ConfigEntryNotReady("first refresh")


_mod("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=DataUpdateCoordinator,
     UpdateFailed=UpdateFailed, CoordinatorEntity=object)


class DeviceInfo(dict):
    def __init__(self, **kw):
        super().__init__(**kw)


_mod("homeassistant.helpers.device_registry", DeviceInfo=DeviceInfo, async_get=lambda hass: None)

RESTORE: dict[str, Any] = {}  # unique_id → état précédent (pour simuler un redémarrage)
RESTORE_ATTRS: dict[str, dict] = {}  # unique_id → attributs de l'état précédent


class Entity:
    hass = None
    entity_id = None
    _attr_translation_key = None
    _attr_unique_id = None
    _attr_options = None
    _attr_entity_category = None

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def translation_key(self):
        if self._attr_translation_key:
            return self._attr_translation_key
        desc = getattr(self, "entity_description", None)
        return getattr(desc, "translation_key", None)

    @property
    def options(self):
        if self._attr_options is not None:
            return self._attr_options
        desc = getattr(self, "entity_description", None)
        return getattr(desc, "options", None)

    def async_on_remove(self, fn):
        self.__dict__.setdefault("_removers", []).append(fn)

    async def async_added_to_hass(self):
        pass

    def async_write_ha_state(self):
        self.hass.written.append(self)


class RestoreEntity(Entity):
    async def async_get_last_state(self):
        st = RESTORE.get(self.unique_id)
        if st is None:
            return None
        return types.SimpleNamespace(state=str(st), attributes=RESTORE_ATTRS.get(self.unique_id, {}))


_mod("homeassistant.helpers.entity", Entity=Entity)
_mod("homeassistant.helpers.restore_state", RestoreEntity=RestoreEntity)
_mod("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)


@dataclasses.dataclass(frozen=True, kw_only=True)
class EntityDescription:
    key: str
    translation_key: str | None = None
    entity_category: Any = None
    entity_registry_enabled_default: bool = True
    native_unit_of_measurement: str | None = None
    device_class: Any = None
    state_class: Any = None
    options: list | None = None
    suggested_display_precision: int | None = None


class _AnyEnum:
    def __getattr__(self, name):
        return name.lower()


class SensorEntity(Entity):
    pass


class RestoreSensor(RestoreEntity, SensorEntity):
    async def async_get_last_sensor_data(self):
        return None


_mod("homeassistant.components.sensor", SensorEntity=SensorEntity, RestoreSensor=RestoreSensor,
     SensorEntityDescription=EntityDescription, SensorDeviceClass=_AnyEnum(), SensorStateClass=_AnyEnum())


class NumberEntity(Entity):
    pass


class RestoreNumber(RestoreEntity, NumberEntity):
    async def async_get_last_number_data(self):
        v = RESTORE.get(self.unique_id)
        return types.SimpleNamespace(native_value=v) if v is not None else None


_mod("homeassistant.components.number", NumberEntity=NumberEntity, RestoreNumber=RestoreNumber,
     NumberDeviceClass=_AnyEnum(), NumberMode=_AnyEnum())
_mod("homeassistant.components.select", SelectEntity=type("SelectEntity", (Entity,), {}))
_mod("homeassistant.components.switch", SwitchEntity=type("SwitchEntity", (Entity,), {}))
_mod("homeassistant.components.button", ButtonEntity=type("ButtonEntity", (Entity,), {}))
_mod("homeassistant.components.binary_sensor", BinarySensorEntity=type("BinarySensorEntity", (Entity,), {}),
     BinarySensorEntityDescription=EntityDescription, BinarySensorDeviceClass=_AnyEnum())
_mod("homeassistant.util")
def _utcnow():
    """Temps réel, ou temps virtuel de la boucle de test quand elle tourne."""
    import datetime as _dt
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and isinstance(loop, VirtualClockLoop):
        return _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(seconds=loop.time())
    return _dt.datetime.now(_dt.timezone.utc)


_mod("homeassistant.util.dt", utcnow=_utcnow,
     parse_datetime=lambda s: __import__("datetime").datetime.fromisoformat(s) if s else None,
     as_utc=lambda d: d)


# ---------------------------------------------------------------- hass simulé
class FakeConfigEntries:
    def __init__(self, hass):
        self.hass = hass
        self.entries: list[ConfigEntry] = []

    def async_entries(self, domain=None):
        return [e for e in self.entries if domain is None or e.domain == domain]

    def async_get_entry(self, entry_id):
        return next((e for e in self.entries if e.entry_id == entry_id), None)

    def async_update_entry(self, entry, data=None, options=None, title=None):
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)

    async def async_forward_entry_setups(self, entry, platforms):
        integ = self.hass.integration
        for p in platforms:
            mod = importlib.import_module(f"{integ.__name__}.{p}")
            added: list = []
            await mod.async_setup_entry(self.hass, entry, lambda ents, *a, _added=added: _added.extend(ents))
            for ent in added:
                ent.hass = self.hass
                ent.platform_name = p
                self.hass.entities.setdefault(entry.entry_id, []).append(ent)
                await ent.async_added_to_hass()

    async def async_unload_platforms(self, entry, platforms):
        for ent in self.hass.entities.pop(entry.entry_id, []):
            for fn in ent.__dict__.get("_removers", []):
                fn()
        return True

    async def add(self, entry: ConfigEntry):
        self.entries.append(entry)
        ok = await self.hass.integration.async_setup_entry(self.hass, entry)
        entry.state = ConfigEntryState.LOADED if ok else ConfigEntryState.NOT_LOADED
        return entry

    async def unload(self, entry):
        await self.hass.integration.async_unload_entry(self.hass, entry)
        for fn in reversed(entry._on_unload):
            fn()
        entry._on_unload.clear()
        entry.state = ConfigEntryState.NOT_LOADED

    async def async_reload(self, entry_id):
        entry = self.async_get_entry(entry_id)
        await self.unload(entry)
        ok = await self.hass.integration.async_setup_entry(self.hass, entry)
        entry.state = ConfigEntryState.LOADED if ok else ConfigEntryState.NOT_LOADED

    async def remove(self, entry):
        await self.unload(entry)
        self.entries.remove(entry)
        await self.hass.integration.async_remove_entry(self.hass, entry)


class FakeStates(dict):
    pass


class FakeHass:
    def __init__(self, loop):
        self.loop = loop
        self.states = FakeStates()
        self.state_listeners: dict[str, list] = {}
        self.config_entries = FakeConfigEntries(self)
        self.entities: dict[str, list] = {}
        self.written: list = []
        self.data: dict = {}
        self.integration = None

    def async_create_task(self, coro):
        return self.loop.create_task(coro)

    def set_state(self, entity_id, value, unit="W"):
        self.states[entity_id] = types.SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})
        for cb in list(self.state_listeners.get(entity_id, [])):
            cb(None)


def load_integration(loop):
    """Importe le vrai code de l'intégration avec l'horloge virtuelle."""
    sys.path.insert(0, str(ROOT / "custom_components"))
    for name in list(sys.modules):
        if name.startswith("zendure_local"):
            del sys.modules[name]
    integ = importlib.import_module("zendure_local")
    fake_time = FakeTime(loop)
    for sub in ("regulator", "tuner", "group", "coordinator"):
        m = importlib.import_module(f"zendure_local.{sub}")
        if hasattr(m, "time"):
            m.time = fake_time
    return integ
