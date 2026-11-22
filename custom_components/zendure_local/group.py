"""Groupe de batteries : un seul régulateur au compteur, consigne répartie entre 2 à 4 batteries.

Le hub expose la même interface qu'une batterie (ZendureCoordinator) pour le régulateur :
feasible, async_set_power, battery_ac_power, fresh_since, set_fast_polling, …
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import dispatch as dsp
from .const import (
    CONF_CIRCUIT_A_CHARGE_LIMIT,
    CONF_CIRCUIT_A_LIMIT,
    CONF_CIRCUIT_A_MEMBERS,
    CONF_CIRCUIT_B_CHARGE_LIMIT,
    CONF_CIRCUIT_B_LIMIT,
    CONF_CIRCUIT_B_MEMBERS,
    CONF_ENTRY_TYPE,
    CONF_MEMBERS,
    CONF_PRIORITY,
    DEFAULT_STRATEGY,
    DOMAIN,
    ENTRY_TYPE_GROUP,
    MODE_GROUP,
    SIGNAL_BATTERY_UPDATE,
    STATE_SOC_MAX,
    STATE_SOC_MIN,
    STATE_TARGET_REACHED,
)

_LOGGER = logging.getLogger(__name__)

REDISPATCH_TOLERANCE = 50  # W : écart entre la part prévue et la consigne d'un membre
STARTUP_GRACE = 90  # s : pas d'alerte pendant le démarrage (les batteries se chargent)


def group_members(entry: ConfigEntry) -> list[str]:
    return list(entry.options.get(CONF_MEMBERS) or entry.data.get(CONF_MEMBERS) or [])


def find_group_entry(hass: HomeAssistant, battery_entry_id: str) -> ConfigEntry | None:
    """Le groupe dont une batterie fait partie (une batterie n'appartient qu'à un groupe)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GROUP and battery_entry_id in group_members(entry):
            return entry
    return None


def member_coordinator(hass: HomeAssistant, entry_id: str):
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        return None
    coord = getattr(entry, "runtime_data", None)
    return coord if coord is not None and not getattr(coord, "is_group", False) else None


class ZendureGroupHub:
    """Cible de régulation pour un groupe de batteries."""

    is_group = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.config_entry = entry
        self.power_setpoint: float = 0
        self.regulator = None
        self.strategy: str = DEFAULT_STRATEGY
        self._listeners: list[Callable[[], None]] = []
        self._fast: timedelta | None = None
        self._unsub_signal: Callable[[], None] | None = None
        self._started = time.monotonic()
        self._redispatch_lock = asyncio.Lock()
        self._last_redispatch = 0.0
        self._issues: set[str] = set()

    # ------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        self._unsub_signal = async_dispatcher_connect(self.hass, SIGNAL_BATTERY_UPDATE, self._on_member_update)

    def shutdown(self) -> None:
        if self._unsub_signal:
            self._unsub_signal()
        for issue in list(self._issues):
            ir.async_delete_issue(self.hass, DOMAIN, issue)
        self._issues.clear()
        for c in self._coordinators().values():
            c.set_fast_polling(None)

    @property
    def name(self) -> str:
        return self.config_entry.title

    @property
    def member_ids(self) -> list[str]:
        return group_members(self.config_entry)

    def member_name(self, entry_id: str) -> str:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        return entry.title if entry else entry_id

    def _coordinators(self) -> dict[str, Any]:
        out = {}
        for eid in self.member_ids:
            c = member_coordinator(self.hass, eid)
            if c is not None:
                out[eid] = c
        return out

    def is_active(self, c) -> bool:
        """G8 : une batterie injoignable, en défaut ou sortie du pilotage quitte la répartition."""
        return (
            c is not None
            and c.available
            and not c.in_fault
            and c.regulator is not None
            and c.regulator.mode == MODE_GROUP
        )

    def active(self) -> dict[str, Any]:
        return {eid: c for eid, c in self._coordinators().items() if self.is_active(c)}

    @property
    def degraded(self) -> bool:
        return len(self.active()) < len(self.member_ids)

    # ------------------------------------------------------------ écouteurs (comme un coordinateur)
    def async_add_listener(self, cb: Callable[[], None], context: Any = None) -> Callable[[], None]:
        self._listeners.append(cb)

        def remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return remove

    def async_update_listeners(self) -> None:
        for cb in list(self._listeners):
            cb()

    @callback
    def _on_member_update(self, entry_id: str) -> None:
        if entry_id not in self.member_ids:
            return
        c = member_coordinator(self.hass, entry_id)
        if c is not None and self._fast is not None and c.update_interval != self._fast:
            c.set_fast_polling(self._fast)  # batterie rechargée entre-temps
        self._update_issues()
        self.async_update_listeners()
        self._maybe_redispatch()

    # ------------------------------------------------------------ alertes Réparations (G4, G8)
    def _update_issues(self) -> None:
        if time.monotonic() - self._started < STARTUP_GRACE:
            return
        wanted: dict[str, tuple[str, dict[str, str]]] = {}
        coords = self._coordinators()
        for eid in self.member_ids:
            c = coords.get(eid)
            placeholders = {"group": self.name, "battery": self.member_name(eid)}
            if c is not None and c.available and c.regulator is not None and c.regulator.mode != MODE_GROUP:
                wanted[f"left_{self.config_entry.entry_id}_{eid}"] = ("member_left_group", placeholders)
            elif not self.is_active(c):
                wanted[f"unavailable_{self.config_entry.entry_id}_{eid}"] = ("member_unavailable", placeholders)
        for issue_id, (key, ph) in wanted.items():
            if issue_id not in self._issues:
                ir.async_create_issue(
                    self.hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                    translation_key=key, translation_placeholders=ph,
                )
                self._issues.add(issue_id)
        for issue_id in list(self._issues - set(wanted)):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            self._issues.discard(issue_id)

    # ------------------------------------------------------------ valeurs agrégées
    @property
    def available(self) -> bool:
        return bool(self.active())

    @property
    def last_update_success(self) -> bool:
        return self.available

    @property
    def soc(self) -> float | None:
        """SOC global, pondéré par la capacité de chaque batterie."""
        num = den = 0.0
        for c in self.active().values():
            if c.soc is None:
                continue
            w = c.usable_capacity or 1.0
            num += c.soc * w
            den += w
        return round(num / den, 1) if den else None

    def _sum(self, attr: str) -> float | None:
        values = [getattr(c, attr) for c in self.active().values()]
        values = [v for v in values if v is not None]
        return round(sum(values), 3) if values else None

    @property
    def usable_capacity(self) -> float | None:
        return self._sum("usable_capacity")

    @property
    def available_energy(self) -> float | None:
        return self._sum("available_energy")

    @property
    def missing_energy(self) -> float | None:
        return self._sum("missing_energy")

    @property
    def battery_power(self) -> float | None:
        return self._sum("battery_power")

    @property
    def battery_ac_power(self) -> float | None:
        return self._sum("battery_ac_power")

    @property
    def max_power(self) -> float:
        coords = self._coordinators().values()
        return float(sum(c.max_power for c in coords)) or 3000.0

    def _circuits(self) -> list[dsp.Circuit]:
        opts = self.config_entry.options
        out = []
        for mkey, lkey, ckey in (
            (CONF_CIRCUIT_A_MEMBERS, CONF_CIRCUIT_A_LIMIT, CONF_CIRCUIT_A_CHARGE_LIMIT),
            (CONF_CIRCUIT_B_MEMBERS, CONF_CIRCUIT_B_LIMIT, CONF_CIRCUIT_B_CHARGE_LIMIT),
        ):
            members = set(opts.get(mkey) or [])
            try:
                limit = float(opts.get(lkey) or 0)
                charge = float(opts.get(ckey) or 0) or None
            except (TypeError, ValueError):
                limit, charge = 0.0, None
            if len(members) >= 2 and limit > 0:
                out.append(dsp.Circuit(members, limit, charge))
        return out

    def _priority(self) -> list[str]:
        order = [e for e in (self.config_entry.options.get(CONF_PRIORITY) or []) if e in self.member_ids]
        return order + [e for e in self.member_ids if e not in order]

    def _members(self, charge_target: float | None = None, ignore_soc: bool = False) -> list[dsp.Member]:
        out = []
        for eid, c in self.active().items():
            soc = c.soc if c.soc is not None else 50.0
            can_charge = can_discharge = True
            if not ignore_soc:
                can_discharge = soc > c.min_soc
                can_charge = soc < c.max_soc
                if can_charge and charge_target is not None:
                    c.update_target_hold(charge_target)
                    can_charge = not c.target_hold
            out.append(dsp.Member(
                id=eid, soc=soc, min_soc=c.min_soc, max_soc=c.max_soc, capacity=c.usable_capacity or 1.0,
                max_charge=c.max_charge_power, max_discharge=c.max_discharge_power,
                can_charge=can_charge, can_discharge=can_discharge,
            ))
        return out

    @property
    def max_charge_power(self) -> float:
        return dsp.capability(self._members(ignore_soc=True), -1, self._circuits())

    @property
    def max_discharge_power(self) -> float:
        return dsp.capability(self._members(ignore_soc=True), 1, self._circuits())

    # ------------------------------------------------------------ cible de régulation
    def fresh_since(self, t: float) -> bool:
        """G10 : on attend une lecture de TOUTES les batteries actives (la plus lente)."""
        coords = self.active().values()
        return bool(coords) and all(c.fresh_since(t) for c in coords)

    def feasible(self, watts: float, charge_target: float | None = None) -> tuple[float, str | None]:
        if abs(watts) < 1e-9:
            return 0.0, None
        sign = 1 if watts > 0 else -1
        members = self._members(charge_target)
        cap = dsp.capability(members, sign, self._circuits())
        if cap <= 0:
            if sign > 0:
                return 0.0, STATE_SOC_MIN
            coords = self.active().values()
            if charge_target is not None and coords and all(c.target_hold for c in coords):
                return 0.0, STATE_TARGET_REACHED
            return 0.0, STATE_SOC_MAX
        return sign * min(abs(watts), cap), None

    def set_fast_polling(self, interval: timedelta | None) -> None:
        self._fast = interval
        for c in self._coordinators().values():
            c.set_fast_polling(interval)

    async def async_refresh(self) -> None:
        await asyncio.gather(*(c.async_refresh() for c in self.active().values()))

    def parts_for(self, total: float) -> dict[str, float]:
        charge_target = None
        reg = self.regulator
        if reg is not None and reg.mode == "grid_charge":
            charge_target = reg.charge_target_soc
        return dsp.dispatch(total, self._members(charge_target), self.strategy, self._priority(), self._circuits())

    async def async_set_power(self, watts: float) -> None:
        """Répartit la consigne totale entre les batteries actives (G6, G7, G9, G12)."""
        parts = self.parts_for(watts)
        coords = self.active()
        tasks = []
        for eid, c in coords.items():
            part = parts.get(eid, 0.0)
            if int(part) != int(c.power_setpoint):
                tasks.append(c.async_set_power(part))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    _LOGGER.warning("Groupe %s : commande refusée par une batterie : %s", self.name, res)
        self.power_setpoint = float(sum(parts.values()))
        self._last_redispatch = time.monotonic()
        self.async_update_listeners()

    @callback
    def _maybe_redispatch(self) -> None:
        """Un membre a changé (SOC limite, retour, panne) : on recalcule les parts au besoin."""
        if self._redispatch_lock.locked() or time.monotonic() - self._last_redispatch < 2:
            return
        reg = self.regulator
        if reg is None or reg.mode == "off" or reg.testing:
            return
        if not self.power_setpoint:
            return
        parts = self.parts_for(self.power_setpoint)
        coords = self.active()
        if any(abs(parts.get(eid, 0) - c.power_setpoint) >= REDISPATCH_TOLERANCE for eid, c in coords.items()):
            self.hass.async_create_task(self._redispatch())

    async def _redispatch(self) -> None:
        async with self._redispatch_lock:
            await self.async_set_power(self.power_setpoint)
