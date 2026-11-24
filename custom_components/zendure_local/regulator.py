"""Régulateur : applique le mode de fonctionnement choisi.

Il pilote une « cible » : une batterie (ZendureCoordinator) ou un groupe de batteries
(ZendureGroupHub), qui exposent la même interface (feasible, async_set_power, …).

Conventions de signe :
- compteur réseau : + = soutirage, − = injection ;
- consigne (power_setpoint) : + = décharge vers la maison, − = charge.

| Mode                   | Comportement                                                  |
|------------------------|---------------------------------------------------------------|
| Couplage intelligent   | surplus → charge, manque → décharge (cible 0 W au compteur)   |
| Décharge intelligente  | manque → décharge, ne charge jamais                           |
| Charge intelligente    | surplus → charge, ne décharge jamais                          |
| Stocker le solaire     | charge toute la production solaire (capteur solaire requis),  |
|                        | sinon se comporte comme « Charge intelligente »               |
| Charge réseau          | charge sur le réseau sans dépasser import_limit au compteur,  |
|                        | jusqu'au SOC cible de charge (hystérésis 3 points)            |
| Pilotée par le groupe  | batterie membre : ne commande rien, le groupe s'en charge     |
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
import math
import time

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DEADBAND,
    CONF_FAST_SCAN,
    CONF_GRID_SENSOR,
    CONF_IMPORT_LIMIT,
    CONF_INVERT_GRID,
    CONF_MIN_INTERVAL,
    CONF_SOLAR_SENSOR,
    CONF_TARGET,
    DEFAULT_CHARGE_TARGET_SOC,
    DEFAULT_DEADBAND,
    DEFAULT_FAST_SCAN,
    DEFAULT_IMPORT_LIMIT,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_TARGET,
    DOMAIN,
    MODE_GRID_CHARGE,
    MODE_GROUP,
    MODE_MANUAL,
    MODE_OFF,
    MODE_SMART,
    MODE_SMART_CHARGE,
    MODE_SMART_DISCHARGE,
    MODE_SOLAR,
    STATE_CHARGE_CAPPED,
    STATE_DISCHARGE_CAPPED,
    STATE_ERROR,
    STATE_LOAD_EXCLUDED,
    STATE_GRID_CHARGING,
    STATE_GROUP,
    STATE_IMPORT_LIMITED,
    STATE_MANUAL,
    STATE_OFF,
    STATE_REGULATING,
    STATE_SENSOR_UNAVAILABLE,
)
from .tuner import AutoTuner, TunerState

_LOGGER = logging.getLogger(__name__)

GAIN = 0.9  # part de l'écart corrigée à chaque calcul (valeur fixe)
SETTLE_TIMEOUT = 6.0  # s : au-delà, on n'attend plus que la batterie atteigne la consigne
SAFETY_TICK = timedelta(seconds=5)  # recalcul de secours si le capteur ne bouge pas
WATT_UNITS = {"W": 1.0, "kW": 1000.0}
REGULATED_MODES = (MODE_SMART, MODE_SMART_DISCHARGE, MODE_SMART_CHARGE, MODE_SOLAR, MODE_GRID_CHARGE)
STEADY_TOLERANCE = 120.0  # W : batterie considérée comme stable autour de sa consigne
STEP_TEST_W = 300.0  # W : échelon du bouton « Mesurer la réponse »
STEP_TEST_S = 12  # s : durée d'observation de l'échelon
STORE_VERSION = 1
# Affinage fin : un petit écart qui dure n'est pas du bruit, on le corrige quand même
TRIM_DELAY = 12.0  # s de calme (sans commande) avant d'affiner
TRIM_MIN = 5.0  # W : en dessous, l'écart moyen est négligeable
TRIM_ALPHA = 0.15  # lissage de la moyenne glissante de l'écart
IMPORT_LIMIT_MARGIN = 50.0  # W : en dessous de la charge max possible → limité par le soutirage


class ZendureRegulator:
    def __init__(self, hass: HomeAssistant, target) -> None:
        """target : ZendureCoordinator (batterie) ou ZendureGroupHub (groupe)."""
        self.hass = hass
        self.coordinator = target
        opts = target.config_entry.options
        self.sensor: str | None = opts.get(CONF_GRID_SENSOR) or None
        self.solar_sensor: str | None = opts.get(CONF_SOLAR_SENSOR) or None
        self.invert = bool(opts.get(CONF_INVERT_GRID, False))
        self._target = float(opts.get(CONF_TARGET, DEFAULT_TARGET))
        self._deadband = float(opts.get(CONF_DEADBAND, DEFAULT_DEADBAND))
        self._min_gap = float(opts.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL))
        self._fast_scan = timedelta(seconds=int(opts.get(CONF_FAST_SCAN, DEFAULT_FAST_SCAN)))
        # Réglables à chaud (entités import_limit et charge_target_soc, restaurées au démarrage)
        self.import_limit = float(opts.get(CONF_IMPORT_LIMIT, DEFAULT_IMPORT_LIMIT))
        self.charge_target_soc = float(DEFAULT_CHARGE_TARGET_SOC)
        # Commandes de puissance (v1.6.0), jamais écrites dans la batterie.
        # None = aucun plafond ; 0 = rien à ne pas couvrir.
        self.charge_power_limit: float | None = None
        self.discharge_power_limit: float | None = None
        self.excluded_power: float = 0.0
        self._manual_wanted: float | None = None  # consigne manuelle demandée (avant plafonds)
        self._last_run = 0.0
        self._last_cmd = 0.0
        self._pending: Callable[[], None] | None = None
        self._rerun = False
        self.mode = MODE_MANUAL
        self.state = STATE_MANUAL  # clé de regulation_state
        self.last_grid: float | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._last_error = 0.0
        self._err_avg: float | None = None
        self.testing = False
        # Réglage automatique (activable / désactivable par un interrupteur)
        self.auto = True
        self.tuner = AutoTuner(
            default_gain=GAIN,
            default_deadband=self._deadband,
            default_gap=self._min_gap,
            default_settle=SETTLE_TIMEOUT,
        )
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.tuner.{target.config_entry.entry_id}")
        self._unsub_battery = target.async_add_listener(self._on_battery)

    # ------------------------------------------------------------ paramètres
    @property
    def gain(self) -> float:
        return self.tuner.gain if self.auto else GAIN

    @property
    def deadband(self) -> float:
        return self.tuner.deadband if self.auto else self._deadband

    @property
    def trim_delay(self) -> float:
        return self.tuner.trim_delay if self.auto else TRIM_DELAY

    @property
    def min_gap(self) -> float:
        return self.tuner.min_gap if self.auto else self._min_gap

    @property
    def settle_timeout(self) -> float:
        return self.tuner.settle_timeout if self.auto else SETTLE_TIMEOUT

    @property
    def regulating(self) -> bool:
        return self.mode in REGULATED_MODES

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
        if self.coordinator.available:
            self.tuner.on_battery(time.monotonic(), self.coordinator.battery_ac_power)
            self._save_later()

    def _target_for_mode(self) -> float:
        return self.import_limit if self.mode == MODE_GRID_CHARGE else self._target

    @callback
    def _on_grid(self, *_args) -> None:
        grid = self._read_grid()
        if grid is not None and self.regulating and not self.testing:
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
        sp0 = c.power_setpoint
        up, _ = c.feasible(sp0 + STEP_TEST_W)
        down, _ = c.feasible(sp0 - STEP_TEST_W)
        if abs(up - sp0) >= STEP_TEST_W - 1:
            step = STEP_TEST_W
        elif abs(down - sp0) >= STEP_TEST_W - 1:
            step = -STEP_TEST_W
        else:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="measure_impossible")
        self.testing = True
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

    def _set_state(self, state: str) -> None:
        self.state = state

    async def async_set_mode(self, mode: str, *, apply: bool = True) -> None:
        if mode in REGULATED_MODES and not self.sensor:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="grid_sensor_required")
        self.stop()
        self.mode = mode
        self._manual_wanted = self.coordinator.power_setpoint if mode == MODE_MANUAL else None
        if mode == MODE_OFF:
            self._set_state(STATE_OFF)
            if apply:
                await self._send(0)
        elif mode == MODE_MANUAL:
            self._set_state(STATE_MANUAL)
        elif mode == MODE_GROUP:
            # Batterie membre : son groupe la pilote, son propre régulateur ne commande plus rien
            self._set_state(STATE_GROUP)
        else:
            self._set_state(STATE_GRID_CHARGING if mode == MODE_GRID_CHARGE else STATE_REGULATING)
            # Réagit à chaque nouvelle mesure du compteur (ex. Shelly : ~1 s)
            self._unsubs.append(async_track_state_change_event(self.hass, [self.sensor], self._on_grid))
            if self.solar_sensor:
                self._unsubs.append(async_track_state_change_event(self.hass, [self.solar_sensor], self._on_event))
            # … et à chaque nouvelle lecture de la batterie
            self._unsubs.append(self.coordinator.async_add_listener(self._schedule))
            self._unsubs.append(async_track_time_interval(self.hass, self._on_event, SAFETY_TICK))
            # Lecture rapide de la batterie pendant la régulation
            self.coordinator.set_fast_polling(self._fast_scan)
            self._schedule()
        self._notify()

    def stop(self) -> None:
        was_regulating = bool(self._unsubs)
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._pending:
            self._pending()
            self._pending = None
        if was_regulating:
            self.coordinator.set_fast_polling(None)

    # ------------------------------------------------------------ déclenchement
    @callback
    def _on_event(self, *_args) -> None:
        self._schedule()

    @callback
    def _schedule(self) -> None:
        """Lance un calcul tout de suite, ou dès que le délai minimum est écoulé."""
        if not self.regulating or self.testing:
            return
        if self._lock.locked():
            self._rerun = True
            return
        wait = self.min_gap - (time.monotonic() - self._last_run)
        if wait <= 0.05:  # délai restant négligeable : on calcule tout de suite
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
        value = self._read_power(self.sensor)
        if value is None:
            return None
        return -value if self.invert else value

    async def _async_regulate(self) -> None:
        async with self._lock:
            self._last_run = time.monotonic()
            try:
                await self._regulate_once()
            except Exception:  # noqa: BLE001 - la régulation ne doit jamais s'arrêter sur une erreur
                _LOGGER.exception("Erreur de régulation")
                self._set_state(STATE_ERROR)
                self._notify()
            finally:
                if self._rerun:
                    self._rerun = False
                    self.hass.loop.call_soon(self._schedule)

    async def _regulate_once(self) -> None:
        if not self.regulating:
            return
        c = self.coordinator
        grid = self._read_grid()
        self.last_grid = grid
        if grid is None:
            # Capteur muet : par sécurité on met la batterie au repos
            self._set_state(STATE_SENSOR_UNAVAILABLE)
            if c.power_setpoint != 0:
                await self._send(0)
            self._notify()
            return

        mx = c.max_power
        charge_target = self.charge_target_soc if self.mode == MODE_GRID_CHARGE else None
        sp = c.power_setpoint
        solar = self._read_power(self.solar_sensor) if self.mode == MODE_SOLAR else None

        if self.mode == MODE_SOLAR and solar is not None:
            # Stocker le solaire : on charge exactement ce que produisent les panneaux
            new = -max(0.0, min(solar, mx))
            if abs(new - sp) < self.deadband:
                await self._finish(sp, sp, charge_target, stable=True)
                return
        else:
            if self.mode == MODE_SMART:
                target, lo, hi = self._target, -mx, mx
            elif self.mode == MODE_SMART_DISCHARGE:
                target, lo, hi = self._target, 0, mx
            elif self.mode == MODE_GRID_CHARGE:
                target, lo, hi = self.import_limit, -mx, 0
            else:  # MODE_SMART_CHARGE, ou MODE_SOLAR sans capteur solaire
                target, lo, hi = self._target, -mx, 0

            error = grid - target
            self._last_error = error
            trim = False
            if abs(error) < self.deadband:
                # Dans la zone morte : on suit la moyenne de l'écart. Le bruit se compense,
                # un écart réel (ex. 16 W soutirés en permanence) reste et sera corrigé.
                self._err_avg = error if self._err_avg is None else self._err_avg + TRIM_ALPHA * (error - self._err_avg)
                if abs(self._err_avg) < TRIM_MIN or time.monotonic() - self._last_cmd < self.trim_delay:
                    await self._finish(sp, sp, charge_target, stable=True)
                    return
                step = round(self._err_avg / 10) * 10 or (10 if self._err_avg > 0 else -10)
                new = max(lo, min(hi, sp + step))
                self._err_avg = None
                trim = True
            else:
                self._err_avg = None

            # La batterie met quelques secondes à atteindre une consigne. Tant qu'elle
            # n'y est pas (lecture faite APRÈS la commande), on ne pousse pas plus loin
            # dans le même sens. Une correction en sens inverse passe tout de suite.
            measured = c.battery_ac_power
            settled = trim or (
                measured is None
                or time.monotonic() - self._last_cmd > self.settle_timeout
                or (c.fresh_since(self._last_cmd) and abs(measured - sp) <= max(40.0, 0.05 * abs(sp)))
            )
            if not trim:
                if self.mode == MODE_GRID_CHARGE and error > 0:
                    # Au-dessus de la limite de soutirage : sens de la sécurité, on corrige
                    # tout l'écart d'un coup avec une petite marge (Z1 : retour < 5 s)
                    new = max(lo, min(hi, sp + error + self.deadband / 2))
                else:
                    new = max(lo, min(hi, sp + self.gain * error))
            if not settled and (new - sp) * (sp - measured) > 0:
                self._notify()
                return

        await self._finish(new, sp, charge_target)

    # ------------------------------------------------------------ plafonds (v1.6.0)
    def house_consumption(self) -> float | None:
        """Consommation de la maison = soutirage + décharge de la batterie + solaire.

        Sans capteur solaire, la production compte pour 0 : la batterie couvre alors
        un peu moins, jamais plus."""
        grid = self.last_grid if self.last_grid is not None else self._read_grid()
        battery = self.coordinator.battery_ac_power
        if grid is None or battery is None:
            return None
        solar = self._read_power(self.solar_sensor) or 0.0
        return grid + battery + max(0.0, solar)

    def apply_caps(self, watts: float) -> tuple[float, str | None]:
        """Plafonds de charge / décharge et puissance à ne pas couvrir.

        Retourne la consigne plafonnée et l'état correspondant si un plafond limite."""
        state = None
        if watts < 0 and self.charge_power_limit is not None and -watts > self.charge_power_limit:
            watts, state = -self.charge_power_limit, STATE_CHARGE_CAPPED
        if watts > 0 and self.discharge_power_limit is not None and watts > self.discharge_power_limit:
            watts, state = self.discharge_power_limit, STATE_DISCHARGE_CAPPED
        if watts > 0 and self.excluded_power > 0:
            house = self.house_consumption()
            # Consommation inconnue : par prudence, rien n'est couvert au-delà de 0.
            # Petite marge (moitié de la zone morte) : le bruit du compteur ne doit pas
            # faire couvrir, même brièvement, une partie des appareils exclus.
            margin = min(self.deadband / 2, 50.0)
            allowed = 0.0 if house is None else max(0.0, house - self.excluded_power - margin)
            allowed = math.floor(allowed / 10) * 10
            if watts > allowed:
                watts, state = allowed, STATE_LOAD_EXCLUDED
                # Pas de va-et-vient au rythme du bruit : la consigne en place est gardée
                # si elle reste sous la limite et à moins d'une zone morte en dessous.
                sp = self.coordinator.power_setpoint
                if 0 < sp <= allowed and allowed - sp < self.deadband:
                    watts = sp
        return watts, state

    @property
    def caps_active(self) -> bool:
        return (
            self.charge_power_limit is not None
            or self.discharge_power_limit is not None
            or self.excluded_power > 0
        )

    async def async_set_manual(self, watts: float) -> None:
        """Consigne manuelle : plafonds appliqués, la demande d'origine est retenue."""
        self._manual_wanted = float(watts)
        capped, cap_state = self.apply_caps(float(watts))
        self._set_state(cap_state or STATE_MANUAL)
        await self.coordinator.async_set_power(capped)
        self._notify()

    @callback
    def settings_changed(self) -> None:
        """Un réglage (plafond, limite…) a changé : prise en compte au cycle suivant."""
        if self.mode == MODE_MANUAL and self._manual_wanted is not None:
            self.hass.async_create_task(self.async_set_manual(self._manual_wanted))
        else:
            self._schedule()

    async def _finish(self, new: float, sp: float, charge_target: float | None, stable: bool = False) -> None:
        """Applique les limites de la cible, choisit l'état, envoie si besoin."""
        c = self.coordinator
        wanted = new
        new, reason = c.feasible(new, charge_target)
        capped, cap_state = self.apply_caps(new)
        if cap_state and not reason:
            reason = cap_state
        new = round(capped / 10) * 10
        if reason:
            self._set_state(reason)
        elif self.mode == MODE_GRID_CHARGE:
            max_charge, _ = c.feasible(-1e9, charge_target)
            limited = new > max_charge + IMPORT_LIMIT_MARGIN and (self.last_grid or 0) >= self.import_limit - self.deadband
            self._set_state(STATE_IMPORT_LIMITED if limited else STATE_GRID_CHARGING)
        else:
            self._set_state(STATE_REGULATING)
        if not stable or new != round(wanted / 10) * 10:
            if new != sp:
                await self._send(new)
        self._notify()

    async def _send(self, watts: float) -> None:
        self._last_cmd = time.monotonic()
        if self.regulating:
            self.tuner.on_command(self._last_cmd, self.coordinator.battery_ac_power, watts, self._last_error)
        try:
            await self.coordinator.async_set_power(watts)
        except HomeAssistantError as err:
            self._set_state(STATE_ERROR)
            _LOGGER.warning("Régulation Zendure : %s", err)
