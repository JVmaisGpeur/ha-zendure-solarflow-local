"""Entités de base, communes à une batterie et à un groupe de batteries."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, pretty_model


class ZendureEntity(Entity):
    """Rattache l'entité à son appareil (batterie ou groupe) et suit ses mises à jour.

    `self.coordinator` est la cible : ZendureCoordinator (batterie) ou ZendureGroupHub (groupe).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    # Suivre aussi les changements du régulateur (mode, état, apprentissage)
    _follow_regulator = False

    def __init__(self, coordinator, key: str) -> None:
        self.coordinator = coordinator
        if getattr(coordinator, "is_group", False):
            entry = coordinator.config_entry
            self._attr_unique_id = f"group_{entry.entry_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"group_{entry.entry_id}")},
                manufacturer=MANUFACTURER,
                name=entry.title,
            )
        else:
            data = coordinator.data or {}
            sn = coordinator.sn
            self._attr_unique_id = f"{sn}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, sn)},
                manufacturer=MANUFACTURER,
                model=pretty_model(data.get("product")),
                name=f"Zendure {pretty_model(data.get('product'))}",
                serial_number=sn,
                sw_version=str(data["version"]) if data.get("version") is not None else None,
                configuration_url=coordinator.api.base_url + "/properties/report",
            )

    @property
    def is_group(self) -> bool:
        return bool(getattr(self.coordinator, "is_group", False))

    @property
    def regulator(self):
        return self.coordinator.regulator

    @property
    def available(self) -> bool:
        return bool(self.coordinator.last_update_success)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))
        if self._follow_regulator and self.coordinator.regulator is not None:
            self.async_on_remove(self.coordinator.regulator.add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
