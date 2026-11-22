"""Réglages : consigne de puissance, limite de soutirage, SOC cible de charge, limites, SOC min/max."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZendureConfigEntry
from .const import (
    AC_MODE_CHARGE,
    AC_MODE_DISCHARGE,
    MAX_IMPORT_LIMIT,
    MODE_GROUP,
    MODE_MANUAL,
)
from .entity import ZendureEntity
from .group import find_group_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[NumberEntity] = [
        ZendurePowerSetpoint(c),
        ZendureImportLimit(c),
        ZendureChargeTargetSoc(c),
    ]
    if not getattr(c, "is_group", False):
        entities += [
            ZendureLimit(c, "input_limit", "inputLimit"),
            ZendureLimit(c, "output_limit", "outputLimit"),
            ZendureSoc(c, "soc_set", "socSet", 70, 100),
            ZendureSoc(c, "min_soc", "minSoc", 0, 50),
        ]
    async_add_entities(entities)


class ZendurePowerSetpoint(ZendureEntity, NumberEntity):
    """Une seule entité pour piloter : + décharge, − charge, 0 repos (total réparti pour un groupe)."""

    _attr_translation_key = "power_setpoint"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_mode = NumberMode.BOX
    _attr_native_step = 10

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "power_setpoint")
        self._attr_native_min_value = -coordinator.max_power
        self._attr_native_max_value = coordinator.max_power

    @property
    def native_value(self) -> float | None:
        if self.is_group:
            return self.coordinator.power_setpoint
        p = self.coordinator.props
        mode = p.get("acMode")
        if mode == AC_MODE_DISCHARGE:
            return float(p.get("outputLimit") or 0)
        if mode == AC_MODE_CHARGE:
            return -float(p.get("inputLimit") or 0)
        return self.coordinator.power_setpoint

    async def async_set_native_value(self, value: float) -> None:
        # Toucher la consigne à la main repasse en « Puissance manuelle »
        # (sur une batterie membre, cela la sort du pilotage du groupe : G4)
        reg = self.coordinator.regulator
        if reg is not None and reg.mode != MODE_MANUAL:
            await reg.async_set_mode(MODE_MANUAL, apply=False)
        await self.coordinator.async_set_power(value)


class _RegulatorSetting(ZendureEntity, RestoreNumber):
    """Réglage du régulateur modifiable à chaud et conservé au redémarrage (Z1, Z4).

    Sur une batterie membre d'un groupe, la valeur est conservée mais ignorée (G3 bis) :
    c'est celle du groupe qui s'applique.
    """

    _attr_mode = NumberMode.BOX
    _follow_regulator = True
    _reg_attr = ""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            setattr(self.regulator, self._reg_attr, float(last.native_value))

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        return getattr(self.regulator, self._reg_attr)

    async def async_set_native_value(self, value: float) -> None:
        setattr(self.regulator, self._reg_attr, float(value))
        self.async_write_ha_state()
        self.regulator._schedule()  # noqa: SLF001 - recalcul immédiat avec la nouvelle valeur

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.is_group:
            return None
        reg = self.regulator
        group = find_group_entry(self.hass, self.coordinator.config_entry.entry_id) if self.hass else None
        if group is not None and reg is not None and reg.mode == MODE_GROUP:
            return {"ignored_by_group": group.title}
        return None


class ZendureImportLimit(_RegulatorSetting):
    """Z1 : soutirage maximal au compteur en mode Charge réseau."""

    _attr_translation_key = "import_limit"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_IMPORT_LIMIT
    _attr_native_step = 100
    _reg_attr = "import_limit"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "import_limit")


class ZendureChargeTargetSoc(_RegulatorSetting):
    """Z4 : SOC cible de la charge réseau (hystérésis de 3 points)."""

    _attr_translation_key = "charge_target_soc"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _reg_attr = "charge_target_soc"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "charge_target_soc")


class ZendureLimit(ZendureEntity, NumberEntity):
    """inputLimit (charge AC max) / outputLimit (sortie max)."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_mode = NumberMode.BOX
    _attr_native_step = 10
    _attr_native_min_value = 0

    def __init__(self, coordinator, key: str, prop: str) -> None:
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

    def __init__(self, coordinator, key: str, prop: str, vmin: int, vmax: int) -> None:
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
