"""Sélecteurs : sens AC (charge/décharge) et mode hors-réseau."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ZendureConfigEntry
from .const import MODE_MANUAL, MODES
from .coordinator import ZendureCoordinator
from .entity import ZendureEntity

AC_MODES = {1: "charge", 2: "discharge"}
GRID_OFF_MODES = {0: "standard", 1: "economic", 2: "closed"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ZendureConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
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
        coordinator: ZendureCoordinator,
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
    """Mode de fonctionnement : Arrêt, Manuel, Couplage / Décharge / Charge intelligente, Stocker le solaire."""

    _attr_translation_key = "operating_mode"
    _attr_options = MODES

    def __init__(self, coordinator: ZendureCoordinator) -> None:
        super().__init__(coordinator, "operating_mode")

    @property
    def _reg(self):
        return self.coordinator.regulator

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._reg.add_listener(self.async_write_ha_state))
        last = await self.async_get_last_state()
        if last is not None and last.state in MODES and last.state != MODE_MANUAL:
            try:
                await self._reg.async_set_mode(last.state, apply=False)
            except Exception:  # noqa: BLE001 - capteur retiré entre-temps
                await self._reg.async_set_mode(MODE_MANUAL, apply=False)

    @property
    def current_option(self) -> str | None:
        return self._reg.mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "statut": self._reg.status,
            "capteur_reseau": self._reg.sensor,
            "inverser_signe": self._reg.invert,
            "puissance_reseau": self._reg.last_grid,
            "consigne": self.coordinator.power_setpoint,
        }

    async def async_select_option(self, option: str) -> None:
        await self._reg.async_set_mode(option)
