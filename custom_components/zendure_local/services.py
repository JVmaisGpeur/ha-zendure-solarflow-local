"""Services de l'intégration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

SERVICE_SET_EXTERNAL_CONTROL = "set_external_control"
ATTR_DEVICE_ID = "device_id"
ATTR_ACTIVE = "active"
ATTR_CONTROLLER = "controller"
ATTR_CONTROLLED_KEYS = "controlled_keys"

SET_EXTERNAL_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ACTIVE): cv.boolean,
        vol.Optional(ATTR_CONTROLLER): cv.string,
        vol.Optional(ATTR_CONTROLLED_KEYS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    }
)


def _target_for_device(hass: HomeAssistant, device_id: str):
    """Batterie ou groupe (cible chargée) correspondant à un appareil de l'intégration."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_device", translation_placeholders={"device": device_id}
        )
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            continue
        if entry.state is not ConfigEntryState.LOADED or getattr(entry, "runtime_data", None) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="device_not_loaded", translation_placeholders={"device": device.name or device_id}
            )
        return entry.runtime_data
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="not_zendure_device", translation_placeholders={"device": device.name or device_id}
    )


@callback
def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_EXTERNAL_CONTROL):
        return

    async def set_external_control(call: ServiceCall) -> None:
        target = _target_for_device(hass, call.data[ATTR_DEVICE_ID])
        target.external.async_set(
            call.data[ATTR_ACTIVE],
            call.data.get(ATTR_CONTROLLER),
            call.data.get(ATTR_CONTROLLED_KEYS),
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_EXTERNAL_CONTROL, set_external_control, schema=SET_EXTERNAL_CONTROL_SCHEMA
    )
