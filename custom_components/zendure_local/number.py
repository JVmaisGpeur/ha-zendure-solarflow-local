"""Réglages : consigne de puissance, limite de soutirage, SOC cible de charge, limites, SOC min/max."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from . import ZendureConfigEntry
from .const import (
    AC_MODE_CHARGE,
    AC_MODE_DISCHARGE,
    MAX_EXCLUDED_POWER,
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
        ZendureChargePowerLimit(c),
        ZendureDischargePowerLimit(c),
        ZendureExcludedPower(c),
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
        if reg is None:
            await self.coordinator.async_set_power(value)
            return
        if reg.mode != MODE_MANUAL:
            await reg.async_set_mode(MODE_MANUAL, apply=False)
        await reg.async_set_manual(value)  # plafonds de charge / décharge appliqués


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
        self.regulator.settings_changed()  # recalcul immédiat avec la nouvelle valeur

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


class _PilotableSetting(_RegulatorSetting):
    """Commande de puissance (v1.6.0), réglable à la main ou par un pilote externe.

    - Valeur gardée dans Home Assistant, jamais écrite dans la batterie.
    - Réglée à la main : conservée au redémarrage.
    - Réglée par un pilote externe qui déclare cette clé : revient au défaut (sans effet)
      quand sa déclaration expire ou est retirée, y compris pendant un arrêt de HA.
    """

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_min_value = 0
    _attr_native_step = 10
    _default: float | None = None  # valeur « sans effet »

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._set_by: str | None = None  # pilote qui a posé la valeur
        self._unsub_until = None

    # -- valeur interne du régulateur <-> valeur affichée
    def _to_display(self, value: float | None) -> float | None:
        return value

    def _from_display(self, value: float) -> float | None:
        return value

    async def async_added_to_hass(self) -> None:
        await ZendureEntity.async_added_to_hass(self)
        ext = self.coordinator.external
        self.async_on_remove(ext.add_listener(self._on_external))
        last_state = await self.async_get_last_state()
        last = await self.async_get_last_number_data()
        if last is None or last.native_value is None or last_state is None:
            return
        set_by = last_state.attributes.get("set_by")
        until = dt_util.parse_datetime(str(last_state.attributes.get("set_by_until") or ""))
        if set_by and (until is None or until <= dt_util.utcnow()):
            return  # pilote disparu pendant l'arrêt : valeur par défaut
        setattr(self.regulator, self._reg_attr, self._from_display(float(last.native_value)))
        if set_by:
            self._set_by = set_by
            # Si le pilote ne renouvelle pas sa déclaration d'ici là, retour au défaut
            self._unsub_until = async_track_point_in_utc_time(self.hass, self._check_pilot, until)
            self.async_on_remove(self._cancel_until)

    def _cancel_until(self) -> None:
        if self._unsub_until is not None:
            self._unsub_until()
            self._unsub_until = None

    @callback
    def _check_pilot(self, _now=None) -> None:
        self._unsub_until = None
        self._on_external()

    @callback
    def _on_external(self) -> None:
        ext = self.coordinator.external
        if self._set_by is None:
            return
        if ext.active and self._key in ext.controlled_keys:
            self.async_write_ha_state()  # nouvelle échéance enregistrée
            return
        # Déclaration expirée ou clé retirée : la batterie n'est jamais bloquée par un pilote disparu
        self._set_by = None
        setattr(self.regulator, self._reg_attr, self._default)
        self.async_write_ha_state()
        self.regulator.settings_changed()

    @property
    def native_value(self) -> float | None:
        return self._to_display(getattr(self.regulator, self._reg_attr))

    async def async_set_native_value(self, value: float) -> None:
        ext = self.coordinator.external
        self._set_by = ext.controller or "external" if ext.active and self._key in ext.controlled_keys else None
        setattr(self.regulator, self._reg_attr, self._from_display(float(value)))
        self.async_write_ha_state()
        self.regulator.settings_changed()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = dict(super().extra_state_attributes or {})
        ext = self.coordinator.external
        if self._set_by:
            attrs["set_by"] = self._set_by
            if ext.expires_at is not None:
                attrs["set_by_until"] = ext.expires_at.isoformat()
        return attrs or None


class _PowerCap(_PilotableSetting):
    """Plafond : la valeur maximale affichée veut dire « aucun plafond »."""

    _max_attr = ""

    @property
    def native_max_value(self) -> float:
        return float(getattr(self.coordinator, self._max_attr) or self.coordinator.max_power)

    def _to_display(self, value: float | None) -> float | None:
        return self.native_max_value if value is None else value

    def _from_display(self, value: float) -> float | None:
        return None if value >= self.native_max_value else max(0.0, value)


class ZendureChargePowerLimit(_PowerCap):
    """Z1 : la batterie ne charge jamais au-delà (solaire ou réseau). 0 = aucune charge."""

    _attr_translation_key = "charge_power_limit"
    _reg_attr = "charge_power_limit"
    _max_attr = "max_charge_power"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "charge_power_limit")


class ZendureDischargePowerLimit(_PowerCap):
    """Z1 : la batterie ne fournit jamais plus à la maison. 0 = aucune décharge."""

    _attr_translation_key = "discharge_power_limit"
    _reg_attr = "discharge_power_limit"
    _max_attr = "max_discharge_power"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "discharge_power_limit")


class ZendureExcludedPower(_PilotableSetting):
    """Z2 : puissance d'appareils que la batterie ne doit pas alimenter (décharge seulement)."""

    _attr_translation_key = "excluded_power"
    _attr_native_max_value = MAX_EXCLUDED_POWER
    _reg_attr = "excluded_power"
    _default = 0.0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "excluded_power")

    def _from_display(self, value: float) -> float | None:
        return max(0.0, value)


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
