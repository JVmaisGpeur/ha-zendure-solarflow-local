"""Capteurs : puissances, niveau, températures, énergie cumulée, packs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ZendureConfigEntry
from .coordinator import ZendureCoordinator
from .entity import ZendureEntity

PACK_STATES = {0: "standby", 1: "charging", 2: "discharging"}


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _deci_kelvin(value: Any) -> float | None:
    v = _num(value)
    return None if v is None else round((v - 2731) / 10, 1)


def _scaled(factor: float) -> Callable[[Any], float | None]:
    def conv(value: Any) -> float | None:
        v = _num(value)
        return None if v is None else round(v * factor, 2)

    return conv


def _int16_current(value: Any) -> float | None:
    v = _num(value)
    if v is None:
        return None
    v = int(v) & 0xFFFF
    if v >= 0x8000:
        v -= 0x10000
    return round(v / 10, 1)


def _battery_power(p: dict[str, Any]) -> float | None:
    charge, discharge = _num(p.get("outputPackPower")), _num(p.get("packInputPower"))
    if charge is None and discharge is None:
        return None
    return (charge or 0) - (discharge or 0)


def _remain_time(p: dict[str, Any]) -> float | None:
    v = _num(p.get("remainOutTime"))
    # La batterie renvoie une valeur « infinie » (≈ 59940) quand elle ne se décharge pas
    return None if v is None or v >= 50000 else v


@dataclass(frozen=True, kw_only=True)
class ZendureSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


def _prop(name: str, conv: Callable[[Any], Any] = _num) -> Callable[[dict[str, Any]], Any]:
    return lambda p: conv(p.get(name))


W = dict(
    native_unit_of_measurement=UnitOfPower.WATT,
    device_class=SensorDeviceClass.POWER,
    state_class=SensorStateClass.MEASUREMENT,
)

SENSORS: tuple[ZendureSensorDescription, ...] = (
    ZendureSensorDescription(
        key="electric_level",
        translation_key="electric_level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_prop("electricLevel"),
    ),
    ZendureSensorDescription(key="battery_power", translation_key="battery_power", value_fn=_battery_power, **W),
    ZendureSensorDescription(key="charge_power", translation_key="charge_power", value_fn=_prop("outputPackPower"), **W),
    ZendureSensorDescription(key="discharge_power", translation_key="discharge_power", value_fn=_prop("packInputPower"), **W),
    ZendureSensorDescription(key="output_home_power", translation_key="output_home_power", value_fn=_prop("outputHomePower"), **W),
    ZendureSensorDescription(key="grid_input_power", translation_key="grid_input_power", value_fn=_prop("gridInputPower"), **W),
    ZendureSensorDescription(key="solar_input_power", translation_key="solar_input_power", value_fn=_prop("solarInputPower"), **W),
    ZendureSensorDescription(key="grid_off_power", translation_key="grid_off_power", value_fn=_prop("gridOffPower"), **W),
    ZendureSensorDescription(
        key="remain_out_time",
        translation_key="remain_out_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        value_fn=_remain_time,
    ),
    ZendureSensorDescription(
        key="pack_state",
        translation_key="pack_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(PACK_STATES.values()),
        value_fn=lambda p: PACK_STATES.get(int(p["packState"])) if p.get("packState") is not None else None,
    ),
    ZendureSensorDescription(
        key="temperature",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_prop("hyperTmp", _deci_kelvin),
    ),
    ZendureSensorDescription(
        key="pack_num",
        translation_key="pack_num",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_prop("packNum"),
    ),
    ZendureSensorDescription(
        key="rssi",
        translation_key="rssi",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_prop("rssi"),
    ),
    ZendureSensorDescription(
        key="fault_level",
        translation_key="fault_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_prop("faultLevel"),
    ),
)

PACK_SENSORS: tuple[ZendureSensorDescription, ...] = (
    ZendureSensorDescription(
        key="soc", translation_key="pack_soc",
        native_unit_of_measurement=PERCENTAGE, device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT, value_fn=_prop("socLevel"),
    ),
    ZendureSensorDescription(
        key="temp", translation_key="pack_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT, value_fn=_prop("maxTemp", _deci_kelvin),
    ),
    ZendureSensorDescription(
        key="voltage", translation_key="pack_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT, device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT, value_fn=_prop("totalVol", _scaled(0.01)),
    ),
    ZendureSensorDescription(
        key="current", translation_key="pack_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE, device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT, value_fn=_prop("batcur", _int16_current),
    ),
    ZendureSensorDescription(
        key="cell_max", translation_key="pack_cell_max",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT, device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_prop("maxVol", _scaled(0.01)),
    ),
    ZendureSensorDescription(
        key="cell_min", translation_key="pack_cell_min",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT, device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_prop("minVol", _scaled(0.01)),
    ),
)

# (clé, propriété de puissance) pour les compteurs d'énergie (tableau de bord Énergie)
ENERGY_SENSORS = (
    ("energy_charged", "outputPackPower"),
    ("energy_discharged", "packInputPower"),
    ("energy_output_home", "outputHomePower"),
    ("energy_grid_input", "gridInputPower"),
)


# Paramètres appris par le réglage automatique (diagnostic)
TUNING_SENSORS: tuple[tuple[str, str | None, Callable[[Any], Any]], ...] = (
    ("tune_meter_period", UnitOfTime.SECONDS, lambda r: r.tuner.state.meter_period),
    ("tune_noise", UnitOfPower.WATT, lambda r: r.tuner.state.noise),
    ("tune_dead_time", UnitOfTime.SECONDS, lambda r: r.tuner.state.dead_time),
    ("tune_response_time", UnitOfTime.SECONDS, lambda r: r.tuner.state.response_time),
    ("tune_gain", None, lambda r: r.gain),
    ("tune_deadband", UnitOfPower.WATT, lambda r: r.deadband),
    ("tune_responses", None, lambda r: r.tuner.state.responses),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [ZendureSensor(coordinator, d) for d in SENSORS]
    entities += [ZendureEnergySensor(coordinator, key, prop) for key, prop in ENERGY_SENSORS]
    entities += [ZendureTuningSensor(coordinator, *d) for d in TUNING_SENSORS]
    for idx, _pack in enumerate(coordinator.packs):
        entities += [ZendurePackSensor(coordinator, d, idx) for d in PACK_SENSORS]
    async_add_entities(entities)


class ZendureSensor(ZendureEntity, SensorEntity):
    entity_description: ZendureSensorDescription

    def __init__(self, coordinator: ZendureCoordinator, description: ZendureSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        try:
            return self.entity_description.value_fn(self.coordinator.props)
        except (TypeError, ValueError, KeyError):
            return None


class ZendurePackSensor(ZendureEntity, SensorEntity):
    entity_description: ZendureSensorDescription

    def __init__(self, coordinator: ZendureCoordinator, description: ZendureSensorDescription, idx: int) -> None:
        super().__init__(coordinator, f"pack{idx + 1}_{description.key}")
        self.entity_description = description
        self._idx = idx
        self._attr_translation_placeholders = {"pack": str(idx + 1)}

    @property
    def available(self) -> bool:
        return super().available and len(self.coordinator.packs) > self._idx

    @property
    def native_value(self) -> Any:
        packs = self.coordinator.packs
        if len(packs) <= self._idx:
            return None
        try:
            return self.entity_description.value_fn(packs[self._idx])
        except (TypeError, ValueError, KeyError):
            return None


class ZendureEnergySensor(ZendureEntity, RestoreSensor):
    """Compteur kWh calculé en intégrant la puissance (méthode des rectangles à gauche)."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    MAX_GAP = 300  # s : au-delà, on n'extrapole pas (batterie injoignable)

    def __init__(self, coordinator: ZendureCoordinator, key: str, prop: str) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._prop = prop
        self._total = 0.0
        self._last_power: float | None = None
        self._last_time = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            restored = _num(last.native_value)
            if restored is not None:
                self._total = restored
        self._sample()

    def _sample(self) -> None:
        now = dt_util.utcnow()
        power = _num(self.coordinator.props.get(self._prop)) if self.coordinator.last_update_success else None
        if self._last_power is not None and self._last_time is not None:
            dt = (now - self._last_time).total_seconds()
            if 0 < dt <= self.MAX_GAP:
                self._total += max(self._last_power, 0) * dt / 3_600_000
        self._last_power, self._last_time = power, now

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sample()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        return round(self._total, 3)


class ZendureTuningSensor(ZendureEntity, SensorEntity):
    """Ce que la régulation a appris de l'installation."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ZendureCoordinator, key: str, unit: str | None, fn) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._attr_native_unit_of_measurement = unit
        self._fn = fn
        self._attr_suggested_display_precision = 0 if unit == UnitOfPower.WATT or key == "tune_responses" else 1
        if key == "tune_gain":
            self._attr_suggested_display_precision = 2

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.regulator.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> Any:
        value = self._fn(self.coordinator.regulator)
        return None if value is None else round(float(value), 3)
