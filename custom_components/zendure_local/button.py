"""Boutons : mesurer la réponse de la batterie, réinitialiser l'apprentissage."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZendureConfigEntry
from .entity import ZendureEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities([ZendureMeasureButton(c), ZendureResetLearningButton(c)])


class ZendureMeasureButton(ZendureEntity, ButtonEntity):
    """Petit échelon de 300 W pendant ~12 s pour calibrer la régulation tout de suite."""

    _attr_translation_key = "measure_response"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "measure_response")

    async def async_press(self) -> None:
        await self.coordinator.regulator.async_measure_response()


class ZendureResetLearningButton(ZendureEntity, ButtonEntity):
    _attr_translation_key = "reset_learning"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "reset_learning")

    async def async_press(self) -> None:
        await self.coordinator.regulator.async_reset_learning()
