"""Entité de base partagée."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ZendureCoordinator


class ZendureEntity(CoordinatorEntity[ZendureCoordinator]):
    """Rattache chaque entité à l'appareil Zendure."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZendureCoordinator, key: str) -> None:
        super().__init__(coordinator)
        data = coordinator.data or {}
        sn = coordinator.sn
        self._attr_unique_id = f"{sn}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            manufacturer=MANUFACTURER,
            model=data.get("product") or "SolarFlow",
            name=f"Zendure {data.get('product') or 'SolarFlow'}",
            serial_number=sn,
            sw_version=str(data["version"]) if data.get("version") is not None else None,
            configuration_url=coordinator.api.base_url + "/properties/report",
        )
