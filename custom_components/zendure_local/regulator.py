"""Régulateur : applique le mode de fonctionnement choisi.

Convention : puissance réseau > 0 = soutirage, < 0 = injection (Shelly Pro 3EM).
Consigne batterie > 0 = décharge vers la maison, < 0 = charge.

| Mode                   | Vise au compteur        | Consigne autorisée |
|------------------------|-------------------------|--------------------|
| Couplage intelligent   | cible (0 W)             | charge et décharge |
| Décharge intelligente  | cible (0 W)             | décharge seulement |
| Charge intelligente    | soutirage max (6000 W)  | charge seulement   |
| Stocker le solaire     | cible (0 W)             | charge seulement   |
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_DEADBAND,
    CONF_GRID_SENSOR,
    CONF_IMPORT_LIMIT,
    CONF_INVERT_GRID,
    CONF_MIN_INTERVAL,
    CONF_TARGET,
    DEFAULT_DEADBAND,
    DEFAULT_IMPORT_LIMIT,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_TARGET,
    MODE_MANUAL,
    MODE_OFF,
    MODE_SMART,
    MODE_SMART_CHARGE,
    MODE_SMART_DISCHARGE,
    MODE_SOLAR,
)
from .coordinator import ZendureCoordinator

_LOGGER = logging.getLogger(__name__)

GAIN = 0.8  # on corrige 80 % de l'écart à chaque pas pour éviter les oscillations
WATT_UNITS = {"W": 1.0, "kW": 1000.0}
REGULATED_MODES = (MODE_SMART, MODE_SMART_DISCHARGE, MODE_SMART_CHARGE, MODE_SOLAR)


class ZendureRegulator:
    def __init__(self, hass: HomeAssistant, coordinator: ZendureCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        opts = coordinator.config_entry.options
        self.sensor: str | None = opts.get(CONF_GRID_SENSOR) or None
        self.invert = bool(opts.get(CONF_INVERT_GRID, False))
        self._target = float(opts.get(CONF_TARGET, DEFAULT_TARGET))
        self._import_limit = float(opts.get(CONF_IMPORT_LIMIT, DEFAULT_IMPORT_LIMIT))
        self._deadband = float(opts.get(CONF_DEADBAND, DEFAULT_DEADBAND))
        self._interval = timedelta(seconds=int(opts.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)))
        self.mode = MODE_MANUAL
        self.status = "manuel"
        self.last_grid: float | None = None
        self._unsub: Callable[[], None] | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------ API
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    async def async_set_mode(self, mode: str, *, apply: bool = True) -> None:
        if mode in REGULATED_MODES and not self.sensor:
            raise HomeAssistantError(
                "Ce mode a besoin d'un capteur réseau : Configurer l'intégration → « Capteur réseau »."
            )
        self.stop()
        self.mode = mode
        if mode == MODE_OFF:
            self.status = "arrêt"
            if apply:
                await self._send(0)
        elif mode == MODE_MANUAL:
            self.status = "manuel"
        else:
            self.status = "démarrage"
            self._unsub = async_track_time_interval(self.hass, self._tick, self._interval)
            self.hass.async_create_task(self._async_regulate())
        self._notify()

    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    # ------------------------------------------------------------ régulation
    def _read_grid(self) -> float | None:
        state = self.hass.states.get(self.sensor) if self.sensor else None
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        value *= WATT_UNITS.get(state.attributes.get("unit_of_measurement", "W"), 1.0)
        return -value if self.invert else value

    @callback
    def _tick(self, _now) -> None:
        if not self._lock.locked():
            self.hass.async_create_task(self._async_regulate())

    async def _async_regulate(self) -> None:
        async with self._lock:
            if self.mode not in REGULATED_MODES:
                return
            c = self.coordinator
            grid = self._read_grid()
            self.last_grid = grid
            if grid is None:
                self.status = "capteur indisponible → repos"
                if c.power_setpoint != 0:
                    await self._send(0)
                self._notify()
                return

            mx = c.max_power
            if self.mode == MODE_SMART:
                target, lo, hi = self._target, -mx, mx
            elif self.mode == MODE_SMART_DISCHARGE:
                target, lo, hi = self._target, 0, mx
            elif self.mode == MODE_SMART_CHARGE:
                target, lo, hi = self._import_limit, -mx, 0
            else:  # MODE_SOLAR
                target, lo, hi = self._target, -mx, 0

            error = grid - target
            if abs(error) < self._deadband:
                self.status = "stable"
                self._notify()
                return

            new = max(lo, min(hi, c.power_setpoint + GAIN * error))

            # Pas de décharge batterie vide, pas de charge batterie pleine
            p = c.props
            soc = p.get("electricLevel")
            min_soc = (p.get("minSoc") or 0) / 10
            max_soc = (p.get("socSet") or 1000) / 10
            if soc is not None and new > 0 and soc <= min_soc:
                new, self.status = 0, "batterie vide"
            elif soc is not None and new < 0 and soc >= max_soc:
                new, self.status = 0, "batterie pleine"
            else:
                self.status = "décharge" if new > 0 else "charge" if new < 0 else "repos"

            new = round(new / 10) * 10
            if new != c.power_setpoint:
                await self._send(new)
            self._notify()

    async def _send(self, watts: float) -> None:
        try:
            await self.coordinator.async_set_power(watts)
        except HomeAssistantError as err:
            self.status = f"erreur : {err}"
            _LOGGER.warning("Régulation Zendure : %s", err)
