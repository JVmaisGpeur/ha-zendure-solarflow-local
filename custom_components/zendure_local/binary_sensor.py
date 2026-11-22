"""Capteurs binaires : défaut, chauffage, réseau, by-pass."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZendureConfigEntry
from .entity import ZendureEntity

# (description, propriété zenSDK)
BINARY_SENSORS: tuple[tuple[BinarySensorEntityDescription, str], ...] = (
    (BinarySensorEntityDescription(key="error", translation_key="error",
     device_class=BinarySensorDeviceClass.PROBLEM, entity_category=EntityCategory.DIAGNOSTIC), "is_error"),
    (BinarySensorEntityDescription(key="heating", translation_key="heating",
     device_class=BinarySensorDeviceClass.HEAT), "heatState"),
    (BinarySensorEntityDescription(key="grid", translation_key="grid",
     device_class=BinarySensorDeviceClass.POWER), "gridState"),
    (BinarySensorEntityDescription(key="bypass", translation_key="bypass"), "pass"),
    (BinarySensorEntityDescription(key="reverse_flow", translation_key="reverse_flow",
     entity_category=EntityCategory.DIAGNOSTIC), "reverseState"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    if getattr(c, "is_group", False):
        return
    async_add_entities(ZendureBinarySensor(c, d, prop) for d, prop in BINARY_SENSORS)


class ZendureBinarySensor(ZendureEntity, BinarySensorEntity):
    def __init__(self, coordinator, description: BinarySensorEntityDescription, prop: str) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._prop = prop

    @property
    def is_on(self) -> bool | None:
        v = self.coordinator.props.get(self._prop)
        return None if v is None else bool(int(v))
