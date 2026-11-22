"""Coordinateur : interroge la batterie à intervalle régulier.

Il sert aussi de « cible de régulation » : le régulateur ne parle qu'à cette interface,
qu'un groupe de batteries (group.py) implémente de la même façon.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ZendureApi, ZendureError
from .const import (
    AC_MODE_CHARGE,
    AC_MODE_DISCHARGE,
    CHARGE_TARGET_HYSTERESIS,
    CONF_CAPACITY,
    CONF_CIRCUIT_LIMIT,
    CONF_MAX_CHARGE_POWER,
    CONF_MAX_DISCHARGE_POWER,
    CONF_MAX_POWER,
    CONF_SCAN_INTERVAL,
    CONF_USE_RAM,
    DEFAULT_MAX_POWER,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USE_RAM,
    DOMAIN,
    PACK_CAPACITY_KWH,
    SIGNAL_BATTERY_UPDATE,
    STATE_SOC_MAX,
    STATE_SOC_MIN,
    STATE_TARGET_REACHED,
)

_LOGGER = logging.getLogger(__name__)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ZendureCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Récupère le rapport complet de la batterie."""

    config_entry: ConfigEntry
    is_group = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ZendureApi) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {api.host}",
            update_interval=timedelta(seconds=interval),
            # Relecture quasi immédiate après chaque commande
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=0.5, immediate=True),
        )
        self.normal_interval = timedelta(seconds=interval)
        self.api = api
        self.sn: str = entry.unique_id or ""
        # Dernière consigne envoyée (+ décharge, − charge)
        self.power_setpoint: float = 0
        self.regulator = None  # ZendureRegulator, créé dans __init__.py
        self.last_read: float = 0.0  # instant (monotonic) de la dernière lecture réussie
        # Hystérésis du SOC cible de charge : vrai = cible atteinte, on attend cible − 3 points
        self.target_hold = False
        self.unknown_pack_types: set[int] = set()

    # ------------------------------------------------------------------ réglages
    @property
    def use_ram(self) -> bool:
        return bool(self.config_entry.options.get(CONF_USE_RAM, DEFAULT_USE_RAM))

    def _opt_power(self, key: str) -> float:
        opts = self.config_entry.options
        return float(opts.get(key, opts.get(CONF_MAX_POWER, DEFAULT_MAX_POWER)))

    @property
    def circuit_limit(self) -> float | None:
        v = _num(self.config_entry.options.get(CONF_CIRCUIT_LIMIT))
        return v if v and v > 0 else None

    # ------------------------------------------------------------------ données
    @property
    def props(self) -> dict[str, Any]:
        return (self.data or {}).get("properties", {})

    @property
    def packs(self) -> list[dict[str, Any]]:
        return (self.data or {}).get("packData", []) or []

    @property
    def available(self) -> bool:
        return self.last_update_success and self.data is not None

    @property
    def soc(self) -> float | None:
        return _num(self.props.get("electricLevel"))

    @property
    def min_soc(self) -> float:
        return (_num(self.props.get("minSoc")) or 0) / 10

    @property
    def max_soc(self) -> float:
        return (_num(self.props.get("socSet")) or 1000) / 10

    @property
    def in_fault(self) -> bool:
        """Défaut ou protection : la batterie sort de la répartition d'un groupe."""
        return bool(_num(self.props.get("is_error")))

    @property
    def battery_ac_power(self) -> float | None:
        """Puissance AC réelle de la batterie : + décharge vers la maison, − charge."""
        p = self.props
        out, inp = p.get("outputHomePower"), p.get("gridInputPower")
        if out is None and inp is None:
            return None
        return float(out or 0) - float(inp or 0)

    @property
    def battery_power(self) -> float | None:
        """Puissance côté packs : + charge, − décharge (convention du capteur battery_power)."""
        p = self.props
        charge, discharge = _num(p.get("outputPackPower")), _num(p.get("packInputPower"))
        if charge is None and discharge is None:
            return None
        return (charge or 0) - (discharge or 0)

    # ------------------------------------------------------------------ Z2 / Z3
    @property
    def usable_capacity(self) -> float | None:
        """Capacité en kWh : option si renseignée, sinon somme des packs d'après packType."""
        opt = _num(self.config_entry.options.get(CONF_CAPACITY))
        if opt and opt > 0:
            return opt
        if not self.packs:
            return None
        total, unknown = 0.0, set()
        for pack in self.packs:
            ptype = pack.get("packType")
            cap = PACK_CAPACITY_KWH.get(int(ptype)) if ptype is not None else None
            if cap is None:
                unknown.add(int(ptype) if ptype is not None else -1)
            else:
                total += cap
        self.unknown_pack_types = unknown
        return None if unknown else round(total, 2)

    @property
    def available_energy(self) -> float | None:
        cap, soc = self.usable_capacity, self.soc
        if cap is None or soc is None:
            return None
        return round(max(0.0, cap * (soc - self.min_soc) / 100), 3)

    @property
    def missing_energy(self) -> float | None:
        cap, soc = self.usable_capacity, self.soc
        if cap is None or soc is None:
            return None
        return round(max(0.0, cap * (self.max_soc - soc) / 100), 3)

    # ------------------------------------------------------------------ Z5 / Z8
    def _device_limit(self, max_key: str, avail_key: str) -> float | None:
        p = self.props
        limits = []
        v = _num(p.get(max_key))
        if v and v > 0:
            limits.append(v)
        # La puissance « disponible » vaut 0 au repos batterie pleine : on ne la croit
        # que si elle est > 0 ou que la batterie signale une réduction (derateFlag).
        avail = _num(p.get(avail_key))
        if avail is not None and (avail > 0 or _num(p.get("derateFlag"))):
            limits.append(avail)
        return min(limits) if limits else None

    def _limit(self, opt_key: str, max_key: str, avail_key: str) -> float:
        limits = [self._opt_power(opt_key)]
        if self.circuit_limit:
            limits.append(self.circuit_limit)
        dev = self._device_limit(max_key, avail_key)
        if dev is not None:
            limits.append(dev)
        return max(0.0, min(limits))

    @property
    def max_charge_power(self) -> float:
        return self._limit(CONF_MAX_CHARGE_POWER, "chargeMaxLimit", "chargeAvailPower")

    @property
    def max_discharge_power(self) -> float:
        return self._limit(CONF_MAX_DISCHARGE_POWER, "inverseMaxPower", "dischargeAvailPower")

    @property
    def max_power(self) -> float:
        """Bornes des entités de consigne (la vraie limite dépend du sens)."""
        return max(self._opt_power(CONF_MAX_CHARGE_POWER), self._opt_power(CONF_MAX_DISCHARGE_POWER))

    # ------------------------------------------------------------------ Z4 (hystérésis)
    def update_target_hold(self, target: float | None) -> None:
        soc = self.soc
        if target is None or soc is None:
            self.target_hold = False
            return
        if soc >= target:
            self.target_hold = True
        elif soc <= target - CHARGE_TARGET_HYSTERESIS:
            self.target_hold = False

    # ------------------------------------------------------------------ cible de régulation
    def fresh_since(self, t: float) -> bool:
        """Vrai si la batterie a été relue après l'instant t."""
        return self.last_read > t

    def feasible(self, watts: float, charge_target: float | None = None) -> tuple[float, str | None]:
        """Ramène une consigne dans ce que la batterie peut faire.

        Retourne (consigne possible, raison si elle a été ramenée à 0).
        """
        soc = self.soc
        if watts > 0:
            if soc is not None and soc <= self.min_soc:
                return 0.0, STATE_SOC_MIN
            return min(watts, self.max_discharge_power), None
        if watts < 0:
            if soc is not None and soc >= self.max_soc:
                return 0.0, STATE_SOC_MAX
            if charge_target is not None:
                self.update_target_hold(charge_target)
                if self.target_hold:
                    return 0.0, STATE_TARGET_REACHED
            return max(watts, -self.max_charge_power), None
        return 0.0, None

    def set_fast_polling(self, interval: timedelta | None) -> None:
        self.update_interval = interval or self.normal_interval

    # ------------------------------------------------------------------ lecture
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.async_get_report()
        except ZendureError as err:
            raise UpdateFailed(str(err)) from err
        if not self.sn and data.get("sn"):
            self.sn = data["sn"]
        self.last_read = time.monotonic()
        return data

    def async_update_listeners(self) -> None:
        super().async_update_listeners()
        # Prévient les groupes dont cette batterie fait partie
        async_dispatcher_send(self.hass, SIGNAL_BATTERY_UPDATE, self.config_entry.entry_id)

    # ------------------------------------------------------------------ écriture
    async def async_write(self, properties: dict[str, Any], *, volatile: bool = False) -> None:
        """Écrit des propriétés puis met à jour l'état local et rafraîchit.

        volatile=True : commandes fréquentes (puissance, mode) écrites en RAM
        (smartMode=1) pour ne pas user la mémoire flash, si l'option est active.
        """
        props = dict(properties)
        if volatile and self.use_ram:
            props["smartMode"] = 1
        try:
            await self.api.async_write(self.sn, props)
        except ZendureError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # Mise à jour optimiste, la lecture suivante confirmera
        if self.data is not None:
            self.data.setdefault("properties", {}).update(props)
            self.async_update_listeners()
        await self.async_request_refresh()

    async def async_set_power(self, watts: float) -> None:
        """Consigne unique : >0 décharge vers la maison, <0 charge, 0 = repos.

        Toujours bornée par les limites de la batterie (Z5), circuit compris (Z8).
        """
        watts = int(round(watts))
        if watts > 0:
            watts = int(min(watts, self.max_discharge_power))
        elif watts < 0:
            watts = int(max(watts, -self.max_charge_power))
        if watts > 0:
            props = {"acMode": AC_MODE_DISCHARGE, "outputLimit": watts, "inputLimit": 0}
        elif watts < 0:
            props = {"acMode": AC_MODE_CHARGE, "inputLimit": -watts, "outputLimit": 0}
        else:
            props = {"inputLimit": 0, "outputLimit": 0}
        await self.async_write(props, volatile=True)
        self.power_setpoint = watts
        self.async_update_listeners()
