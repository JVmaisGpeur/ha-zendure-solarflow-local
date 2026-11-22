"""Sélecteurs : mode de fonctionnement, stratégie d'un groupe, sens AC et mode hors-réseau."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ZendureConfigEntry
from .const import DEFAULT_STRATEGY, MODE_GROUP, MODE_MANUAL, MODES, STRATEGIES
from .entity import ZendureEntity
from .group import find_group_entry

AC_MODES = {1: "charge", 2: "discharge"}
GRID_OFF_MODES = {0: "standard", 1: "economic", 2: "closed"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    if getattr(c, "is_group", False):
        async_add_entities([ZendureModeSelect(c), ZendureStrategySelect(c)])
        return
    async_add_entities(
        [
            ZendureModeSelect(c),
            ZendureSelect(c, "ac_mode", "acMode", AC_MODES, volatile=True),
            ZendureSelect(c, "grid_off_mode", "gridOffMode", GRID_OFF_MODES, config=True),
        ]
    )


class ZendureSelect(ZendureEntity, SelectEntity):
    def __init__(
        self,
        coordinator,
        key: str,
        prop: str,
        mapping: dict[int, str],
        *,
        volatile: bool = False,
        config: bool = False,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._prop = prop
        self._map = mapping
        self._reverse = {v: k for k, v in mapping.items()}
        self._volatile = volatile
        self._attr_options = list(mapping.values())
        if config:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str | None:
        v = self.coordinator.props.get(self._prop)
        return None if v is None else self._map.get(int(v))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write({self._prop: self._reverse[option]}, volatile=self._volatile)


class ZendureModeSelect(ZendureEntity, SelectEntity, RestoreEntity):
    """Mode de fonctionnement (clés du contrat d'interface).

    Sur une batterie membre d'un groupe, l'option « group » (Pilotée par le groupe) s'ajoute.
    """

    _attr_translation_key = "operating_mode"
    _follow_regulator = True

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "operating_mode")

    @property
    def _reg(self):
        return self.coordinator.regulator

    def _group_entry(self):
        if self.is_group or self.hass is None:
            return None
        return find_group_entry(self.hass, self.coordinator.config_entry.entry_id)

    @property
    def available(self) -> bool:
        return True

    @property
    def options(self) -> list[str]:
        if self._group_entry() is not None:
            return [*MODES, MODE_GROUP]
        return list(MODES)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        last_mode = last.state if last is not None else None
        member = self._group_entry() is not None
        if member and last_mode in (None, MODE_GROUP):
            mode = MODE_GROUP
        elif last_mode in MODES:
            mode = last_mode
        else:
            mode = MODE_MANUAL  # ex. « group » alors que le groupe a été supprimé
        if mode == MODE_MANUAL:
            return
        try:
            await self._reg.async_set_mode(mode, apply=False)
        except Exception:  # noqa: BLE001 - capteur retiré entre-temps
            await self._reg.async_set_mode(MODE_MANUAL, apply=False)

    @property
    def current_option(self) -> str | None:
        return self._reg.mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "capteur_reseau": self._reg.sensor,
            "inverser_signe": self._reg.invert,
            "capteur_solaire": self._reg.solar_sensor,
            "puissance_reseau": self._reg.last_grid,
            "consigne": self.coordinator.power_setpoint,
        }
        group = self._group_entry()
        if group is not None:
            attrs["group_name"] = group.title
        if self.is_group:
            hub = self.coordinator
            attrs["batteries"] = [
                {"entry_id": eid, "name": hub.member_name(eid), "active": eid in hub.active()} for eid in hub.member_ids
            ]
        return attrs

    async def async_select_option(self, option: str) -> None:
        await self._reg.async_set_mode(option)


class ZendureStrategySelect(ZendureEntity, SelectEntity, RestoreEntity):
    """Stratégie de répartition d'un groupe : simultaneous, soc_balance, priority."""

    _attr_translation_key = "strategy"
    _attr_options = STRATEGIES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "strategy")

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self.coordinator.strategy = last.state if last is not None and last.state in STRATEGIES else DEFAULT_STRATEGY

    @property
    def current_option(self) -> str | None:
        return self.coordinator.strategy

    async def async_select_option(self, option: str) -> None:
        self.coordinator.strategy = option
        self.async_write_ha_state()
        hub = self.coordinator
        if hub.power_setpoint:
            await hub.async_set_power(hub.power_setpoint)  # nouvelle répartition tout de suite
