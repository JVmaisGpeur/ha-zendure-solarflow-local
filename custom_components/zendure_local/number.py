"""Réglages : consigne de puissance, limites de charge/décharge, SOC min/max."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZendureConfigEntry
from .const import AC_MODE_CHARGE, AC_MODE_DISCHARGE, MODE_MANUAL
from .coordinator import ZendureCoordinator
from .entity import ZendureEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            ZendurePowerSetpoint(c),
            ZendureLimit(c, "input_limit", "inputLimit"),
            ZendureLimit(c, "output_limit", "outputLimit"),
            ZendureSoc(c, "soc_set", "socSet", 70, 100),
            ZendureSoc(c, "min_soc", "minSoc", 0, 50),
        ]
    )


class ZendurePowerSetpoint(ZendureEntity, NumberEntity):
    """Une seule entité pour piloter la batterie : + décharge, − charge, 0 repos."""

    _attr_translation_key = "power_setpoint"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_mode = NumberMode.BOX
    _attr_native_step = 10

    def __init__(self, coordinator: ZendureCoordinator) -> None:
        super().__init__(coordinator, "power_setpoint")
        self._attr_native_min_value = -coordinator.max_power
        self._attr_native_max_value = coordinator.max_power

    @property
    def native_value(self) -> float | None:
        p = self.coordinator.props
        mode = p.get("acMode")
        if mode == AC_MODE_DISCHARGE:
            return float(p.get("outputLimit") or 0)
        if mode == AC_MODE_CHARGE:
            return -float(p.get("inputLimit") or 0)
        return self.coordinator.power_setpoint

    async def async_set_native_value(self, value: float) -> None:
        # Toucher la consigne à la main repasse en « Puissance manuelle »
        reg = self.coordinator.regulator
        if reg is not None and reg.mode != MODE_MANUAL:
            await reg.async_set_mode(MODE_MANUAL, apply=False)
        await self.coordinator.async_set_power(value)


class ZendureLimit(ZendureEntity, NumberEntity):
    """inputLimit (charge AC max) / outputLimit (sortie max)."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_mode = NumberMode.BOX
    _attr_native_step = 10
    _attr_native_min_value = 0

    def __init__(self, coordinator: ZendureCoordinator, key: str, prop: str) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._prop = prop
        self._attr_native_max_value = coordinator.max_power

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.props.get(self._prop)
        return None if v is None else float(v)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write({self._prop: int(value)}, volatile=True)


class ZendureSoc(ZendureEntity, NumberEntity):
    """SOC cible / SOC minimum. L'appareil les stocke en dixièmes de %."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ZendureCoordinator, key: str, prop: str, vmin: int, vmax: int) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._prop = prop
        self._attr_native_min_value = vmin
        self._attr_native_max_value = vmax

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.props.get(self._prop)
        return None if v is None else round(float(v) / 10)

    async def async_set_native_value(self, value: float) -> None:
        # Réglage rare : écrit en flash pour survivre à un redémarrage
        await self.coordinator.async_write({self._prop: int(value) * 10})
