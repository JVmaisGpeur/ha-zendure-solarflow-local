"""Régulateur : applique le mode de fonctionnement choisi.

Convention : puissance réseau > 0 = soutirage, < 0 = injection (Shelly Pro 3EM).
Consigne batterie > 0 = décharge vers la maison, < 0 = charge.

| Mode                   | Comportement                                                  |
|------------------------|---------------------------------------------------------------|
| Couplage intelligent   | surplus → charge, manque → décharge (cible 0 W au compteur)   |
| Décharge intelligente  | manque → décharge, ne charge jamais                           |
| Charge intelligente    | surplus → charge, ne décharge jamais                          |
| Stocker le solaire     | charge toute la production solaire (capteur solaire requis),  |
|                        | sinon se comporte comme « Charge intelligente »               |
| Charge réseau          | charge sur le réseau sans dépasser le soutirage max (6000 W)  |
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
import time

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    CONF_DEADBAND,
    CONF_FAST_SCAN,
    CONF_GRID_SENSOR,
    CONF_IMPORT_LIMIT,
    CONF_INVERT_GRID,
    CONF_MIN_INTERVAL,
    CONF_SOLAR_SENSOR,
    CONF_TARGET,
    DEFAULT_DEADBAND,
    DEFAULT_FAST_SCAN,
    DEFAULT_IMPORT_LIMIT,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_TARGET,
    DOMAIN,
    MODE_GRID_CHARGE,
    MODE_MANUAL,
    MODE_OFF,
    MODE_SMART,
    MODE_SMART_CHARGE,
    MODE_SMART_DISCHARGE,
    MODE_SOLAR,
)
from .coordinator import ZendureCoordinator
from .tuner import AutoTuner, TunerState

_LOGGER = logging.getLogger(__name__)

GAIN = 0.9  # part de l'écart corrigée à chaque calcul (valeur fixe)
SETTLE_TIMEOUT = 6.0  # s : au-delà, on n'attend plus que la batterie atteigne la consigne
STEADY_TOLERANCE = 120.0  # W : batterie considérée comme stable autour de sa consigne
STEP_TEST_W = 300.0  # W : échelon du bouton « Mesurer la réponse »
STEP_TEST_S = 12  # s : durée d'observation de l'échelon
STORE_VERSION = 1
SAFETY_TICK = timedelta(seconds=5)  # recalcul de secours si le capteur ne bouge pas
WATT_UNITS = {"W": 1.0, "kW": 1000.0}
REGULATED_MODES = (MODE_SMART, MODE_SMART_DISCHARGE, MODE_SMART_CHARGE, MODE_SOLAR, MODE_GRID_CHARGE)


class ZendureRegulator:
    def __init__(self, hass: HomeAssistant, coordinator: ZendureCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        opts = coordinator.config_entry.options
        self.sensor: str | None = opts.get(CONF_GRID_SENSOR) or None
        self.solar_sensor: str | None = opts.get(CONF_SOLAR_SENSOR) or None
        self.invert = bool(opts.get(CONF_INVERT_GRID, False))
        self._target = float(opts.get(CONF_TARGET, DEFAULT_TARGET))
        self._import_limit = float(opts.get(CONF_IMPORT_LIMIT, DEFAULT_IMPORT_LIMIT))
        self._deadband = float(opts.get(CONF_DEADBAND, DEFAULT_DEADBAND))
        self._min_gap = float(opts.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL))
        self._fast_scan = timedelta(seconds=int(opts.get(CONF_FAST_SCAN, DEFAULT_FAST_SCAN)))
        self._last_run = 0.0
        self._last_cmd = 0.0
        self._pending: Callable[[], None] | None = None
        self._rerun = False
        self.mode = MODE_MANUAL
        self.status = "manuel"
        self.last_grid: float | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._last_error = 0.0
        self.testing = False
        # Réglage automatique (activable / désactivable par un interrupteur)
        self.auto = True
        self.tuner = AutoTuner(
            default_gain=GAIN,
            default_deadband=self._deadband,
            default_gap=self._min_gap,
            default_settle=SETTLE_TIMEOUT,
        )
        self._store: Store = Store(
            hass, STORE_VERSION, f"{DOMAIN}.tuner.{coordinator.config_entry.entry_id}"
        )
        self._unsub_battery = coordinator.async_add_listener(self._on_battery)

    # ------------------------------------------------------------ paramètres
    @property
    def gain(self) -> float:
        return self.tuner.gain if self.auto else GAIN

    @property
    def deadband(self) -> float:
        return self.tuner.deadband if self.auto else self._deadband

    @property
    def min_gap(self) -> float:
        return self.tuner.min_gap if self.auto else self._min_gap

    @property
    def settle_timeout(self) -> float:
        return self.tuner.settle_timeout if self.auto else SETTLE_TIMEOUT

    # ------------------------------------------------------------ apprentissage
    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.tuner.state = TunerState.from_dict(data)

    def _save_later(self) -> None:
        if self.tuner.take_dirty():
            self._store.async_delay_save(self.tuner.state.as_dict, 60)
            self._notify()

    async def async_reset_learning(self) -> None:
        self.tuner.reset()
        self.tuner.take_dirty()
        await self._store.async_save(self.tuner.state.as_dict())
        self._notify()

    @callback
    def _on_battery(self) -> None:
        if self.coordinator.last_update_success:
            self.tuner.on_battery(time.monotonic(), self.coordinator.battery_ac_power)
            self._save_later()

    def _target_for_mode(self) -> float:
        return self._import_limit if self.mode == MODE_GRID_CHARGE else self._target

    @callback
    def _on_grid(self, *_args) -> None:
        grid = self._read_grid()
        if grid is not None and self.mode in REGULATED_MODES and not self.testing:
            c = self.coordinator
            measured = c.battery_ac_power
            steady = measured is not None and abs(measured - c.power_setpoint) <= STEADY_TOLERANCE
            error = grid - self._target_for_mode()
            now = time.monotonic()
            self.tuner.on_meter(now, grid, error, steady)
            self.tuner.on_tick(now, error)
            self._save_later()
        self._schedule()

    async def async_measure_response(self) -> None:
        """Bouton « Mesurer la réponse » : petit échelon de puissance pour calibrer tout de suite."""
        if self.testing:
            return
        c = self.coordinator
        p = c.props
        soc = p.get("electricLevel")
        min_soc = (p.get("minSoc") or 0) / 10
        max_soc = (p.get("socSet") or 1000) / 10
        sp0 = c.power_setpoint
        if soc is not None and soc > min_soc + 5 and sp0 + STEP_TEST_W <= c.max_power:
            step = STEP_TEST_W
        elif soc is not None and soc < max_soc - 5 and sp0 - STEP_TEST_W >= -c.max_power:
            step = -STEP_TEST_W
        else:
            raise HomeAssistantError("Mesure impossible : batterie trop pleine ou trop vide.")
        self.testing = True
        previous_status = self.status
        self.status = "mesure de la réponse…"
        self._notify()
        try:
            async with self._lock:
                await c.async_refresh()
                self.tuner.on_command(time.monotonic(), c.battery_ac_power, sp0 + step, step, weight=2.0)
                await c.async_set_power(sp0 + step)
                for _ in range(STEP_TEST_S * 2):
                    await asyncio.sleep(0.5)
                    await c.async_refresh()
                    self.tuner.on_battery(time.monotonic(), c.battery_ac_power)
                await c.async_set_power(sp0)
                self.tuner.on_tick(time.monotonic() + 999, 0.0)
                self._last_cmd = time.monotonic()
        finally:
            self.testing = False
            self.status = previous_status
            self._save_later()
            self._notify()
            self._schedule()

    def shutdown(self) -> None:
        self.stop()
        self._unsub_battery()
        self._store.async_delay_save(self.tuner.state.as_dict, 0)

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
            # Réagit à chaque nouvelle mesure du compteur (ex. Shelly : ~1 s)
            self._unsubs.append(async_track_state_change_event(self.hass, [self.sensor], self._on_grid))
            if self.solar_sensor:
                self._unsubs.append(
                    async_track_state_change_event(self.hass, [self.solar_sensor], self._on_event)
                )
            # … et à chaque nouvelle lecture de la batterie
            self._unsubs.append(self.coordinator.async_add_listener(self._schedule))
            self._unsubs.append(async_track_time_interval(self.hass, self._on_event, SAFETY_TICK))
            # Lecture rapide de la batterie pendant la régulation
            self.coordinator.update_interval = self._fast_scan
            self._schedule()
        self._notify()

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._pending:
            self._pending()
            self._pending = None
        self.coordinator.update_interval = self.coordinator.normal_interval

    # ------------------------------------------------------------ déclenchement
    @callback
    def _on_event(self, *_args) -> None:
        self._schedule()

    @callback
    def _schedule(self) -> None:
        """Lance un calcul tout de suite, ou dès que le délai minimum est écoulé."""
        if self.mode not in REGULATED_MODES or self.testing:
            return
        if self._lock.locked():
            self._rerun = True
            return
        wait = self.min_gap - (time.monotonic() - self._last_run)
        if wait <= 0:
            self.hass.async_create_task(self._async_regulate())
        elif self._pending is None:
            self._pending = async_call_later(self.hass, wait, self._on_pending)

    @callback
    def _on_pending(self, _now) -> None:
        self._pending = None
        self._schedule()

    # ------------------------------------------------------------ régulation
    def _read_power(self, entity_id: str | None) -> float | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        return value * WATT_UNITS.get(state.attributes.get("unit_of_measurement", "W"), 1.0)

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

    async def _async_regulate(self) -> None:
        async with self._lock:
            self._last_run = time.monotonic()
            try:
                await self._regulate_once()
            finally:
                if self._rerun:
                    self._rerun = False
                    self.hass.loop.call_soon(self._schedule)

    async def _regulate_once(self) -> None:
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
        solar = self._read_power(self.solar_sensor) if self.mode == MODE_SOLAR else None
        if self.mode == MODE_SOLAR and solar is not None:
            # Stocker le solaire : on charge exactement ce que produisent les panneaux
            new = -max(0.0, min(solar, mx))
            if abs(new - c.power_setpoint) < self.deadband:
                self.status = "stable"
                self._notify()
                return
        else:
            if self.mode == MODE_SMART:
                target, lo, hi = self._target, -mx, mx
            elif self.mode == MODE_SMART_DISCHARGE:
                target, lo, hi = self._target, 0, mx
            elif self.mode == MODE_GRID_CHARGE:
                target, lo, hi = self._import_limit, -mx, 0
            else:  # MODE_SMART_CHARGE, ou MODE_SOLAR sans capteur solaire
                target, lo, hi = self._target, -mx, 0

            error = grid - target
            self._last_error = error
            if abs(error) < self.deadband:
                self.status = "stable"
                self._notify()
                return

            # La batterie met quelques secondes à atteindre une consigne. Tant qu'elle
            # n'y est pas, on ne pousse pas plus loin dans le même sens (sinon :
            # dépassement puis oscillations). Une correction en sens inverse passe
            # tout de suite (ex. la conso chute pendant une montée en puissance).
            sp = c.power_setpoint
            measured = c.battery_ac_power
            settled = (
                measured is None
                or abs(measured - sp) <= max(50.0, 0.15 * abs(sp))
                or time.monotonic() - self._last_cmd > self.settle_timeout
            )
            new = max(lo, min(hi, sp + self.gain * error))
            if not settled and (new - sp) * (sp - measured) > 0:
                self.status = "ajustement en cours"
                self._notify()
                return

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
        self._last_cmd = time.monotonic()
        if self.mode in REGULATED_MODES:
            self.tuner.on_command(
                self._last_cmd, self.coordinator.battery_ac_power, watts, self._last_error
            )
        try:
            await self.coordinator.async_set_power(watts)
        except HomeAssistantError as err:
            self.status = f"erreur : {err}"
            _LOGGER.warning("Régulation Zendure : %s", err)
