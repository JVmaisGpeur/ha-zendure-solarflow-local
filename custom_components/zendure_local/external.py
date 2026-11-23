"""Pilotage externe déclaré : qui pilote cette batterie (ou ce groupe), et quels réglages.

Un pilote externe (par exemple le Chef d'orchestre énergie) appelle le service
`zendure_local.set_external_control`. La déclaration expire sans renouvellement
(30 min) : un pilote planté ou désinstallé ne bloque jamais l'affichage.
Ce module ne change rien au fonctionnement de la batterie ; il ne fait que déclarer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

EXTERNAL_CONTROL_TIMEOUT = timedelta(minutes=30)
STATE_ACTIVE = "active"
STATE_INACTIVE = "inactive"


class ExternalControl:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.controller: str | None = None
        self.controlled_keys: list[str] = []
        self.expires_at: datetime | None = None
        self._unsub_expire: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def active(self) -> bool:
        return self.expires_at is not None and self.expires_at > dt_util.utcnow()

    @property
    def state(self) -> str:
        return STATE_ACTIVE if self.active else STATE_INACTIVE

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)

        def remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return remove

    @callback
    def async_set(
        self,
        active: bool,
        controller: str | None = None,
        controlled_keys: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Déclare (ou renouvelle) un pilotage externe, ou y met fin."""
        self._cancel_timer()
        if not active:
            self.controller, self.controlled_keys, self.expires_at = None, [], None
        else:
            self.controller = (controller or "").strip() or None
            self.controlled_keys = [str(k) for k in (controlled_keys or []) if str(k).strip()]
            self.expires_at = expires_at or dt_util.utcnow() + EXTERNAL_CONTROL_TIMEOUT
            if self.expires_at <= dt_util.utcnow():
                self.controller, self.controlled_keys, self.expires_at = None, [], None
            else:
                self._unsub_expire = async_track_point_in_utc_time(self.hass, self._expired, self.expires_at)
        self._notify()

    @callback
    def _expired(self, _now: datetime) -> None:
        self._unsub_expire = None
        self.controller, self.controlled_keys, self.expires_at = None, [], None
        self._notify()

    def _cancel_timer(self) -> None:
        if self._unsub_expire is not None:
            self._unsub_expire()
            self._unsub_expire = None

    @callback
    def shutdown(self) -> None:
        self._cancel_timer()
        self._listeners.clear()

    def _notify(self) -> None:
        for update in list(self._listeners):
            update()
