"""Interrupteur « Réglage automatique » de la régulation."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ZendureConfigEntry
from .entity import ZendureEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ZendureAutoTuneSwitch(entry.runtime_data)])


class ZendureAutoTuneSwitch(ZendureEntity, SwitchEntity, RestoreEntity):
    """Activé : la régulation s'adapte seule à l'installation. Désactivé : valeurs de « Configurer »."""

    _attr_translation_key = "auto_tune"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "auto_tune")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self.coordinator.regulator.auto = not (last is not None and last.state == STATE_OFF)

    @property
    def is_on(self) -> bool:
        return self.coordinator.regulator.auto

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.regulator.auto = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.regulator.auto = False
        self.async_write_ha_state()
