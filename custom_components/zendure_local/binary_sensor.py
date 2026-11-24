"""Capteurs binaires : défaut, chauffage, réseau, by-pass."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import ZendureConfigEntry
from .const import CALIBRATION_STUCK_HOURS, DOMAIN, pretty_model
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
        async_add_entities([ZendureGroupCalibrating(c)])
        return
    entities: list[BinarySensorEntity] = [ZendureBinarySensor(c, d, prop) for d, prop in BINARY_SENSORS]
    # Créée seulement si l'appareil fournit socStatus
    if "socStatus" in c.props:
        entities.append(ZendureCalibrating(c))
    async_add_entities(entities)


class ZendureBinarySensor(ZendureEntity, BinarySensorEntity):
    def __init__(self, coordinator, description: BinarySensorEntityDescription, prop: str) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._prop = prop

    @property
    def is_on(self) -> bool | None:
        v = self.coordinator.props.get(self._prop)
        return None if v is None else bool(int(v))


class ZendureCalibrating(ZendureEntity, RestoreEntity, BinarySensorEntity):
    """Z3 : la batterie calibre son niveau de charge (socStatus).

    L'appareil mène sa calibration ; l'intégration ne fait que l'afficher.
    Au-delà de 72 h, alerte dans Réparations (calibration bloquée)."""

    _attr_translation_key = "calibrating"
    _attr_icon = "mdi:battery-sync"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "calibrating")
        self._since: datetime | None = None

    @property
    def _issue_id(self) -> str:
        return f"calibration_stuck_{self.coordinator.config_entry.entry_id}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == "on":
            self._since = dt_util.parse_datetime(str(last.attributes.get("since") or ""))
        self._track()

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.calibrating

    def _handle_coordinator_update(self) -> None:
        self._track()
        super()._handle_coordinator_update()

    def _track(self) -> None:
        on = self.coordinator.calibrating
        if on:
            if self._since is None:
                self._since = dt_util.utcnow()
            if dt_util.utcnow() - self._since > timedelta(hours=CALIBRATION_STUCK_HOURS):
                c = self.coordinator
                p = c.props
                ir.async_create_issue(
                    self.hass, DOMAIN, self._issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                    translation_key="calibration_stuck",
                    translation_placeholders={
                        "battery": c.config_entry.title,
                        "model": pretty_model((c.data or {}).get("product")),
                        "sn": str(c.sn or "—"),
                        "hours": str(CALIBRATION_STUCK_HOURS),
                        "versions": ", ".join(
                            f"{k}={p[k]}" for k in ("masterSoftVersion", "dspSoftVersion", "BMSVersion") if k in p
                        ) or "—",
                    },
                )
        elif on is False:
            self._since = None
            if self.hass is not None:
                ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {"since": self._since.isoformat()} if self._since else None


class ZendureGroupCalibrating(ZendureEntity, BinarySensorEntity):
    """Z3 sur un groupe : vrai si au moins une batterie calibre, liste en attribut."""

    _attr_translation_key = "calibrating"
    _attr_icon = "mdi:battery-sync"

    def __init__(self, hub) -> None:
        super().__init__(hub, "calibrating")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.calibrating_members())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"batteries": self.coordinator.calibrating_members()}
