"""Z4 (v1.7.0) : branchement du comptage de provenance sur une batterie.

Le comptage (provenance.py) se fait à chaque lecture de la batterie déjà faite par le
coordinateur ; il lit aussi la puissance au compteur, celle que la régulation lit déjà.
Dans un groupe, la puissance au compteur du groupe est partagée entre ses batteries au
prorata de leur puissance de charge : la somme des batteries égale le groupe.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .provenance import Provenance, combine

STORE_VERSION = 1
SAVE_DELAY = 60  # s


def _f(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0


def now_ts() -> float:
    return dt_util.utcnow().timestamp()


class ProvenanceKeeper:
    """Tient le comptage d'une batterie, le met à jour et le garde au redémarrage."""

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.state = Provenance()
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.provenance.{coordinator.config_entry.entry_id}")
        self._unsub = None

    async def async_start(self) -> None:
        self.state = Provenance.from_dict(await self._store.async_load())
        # Écouteur ajouté avant les entités : le comptage est à jour quand elles s'affichent
        self._unsub = self.coordinator.async_add_listener(self._on_update)
        self._on_update()

    def shutdown(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        self.hass.async_create_task(self._store.async_save(self.state.as_dict()))

    # ------------------------------------------------------------ compteur
    def _meter(self) -> float | None:
        """Puissance au compteur attribuée à cette batterie (W, + soutirage), ou None."""
        from .group import find_group_entry  # import tardif : group importe des modules lourds

        c = self.coordinator
        gentry = find_group_entry(self.hass, c.config_entry.entry_id)
        hub = getattr(gentry, "runtime_data", None) if gentry is not None else None
        if hub is not None and hub.regulator is not None:
            if not hub.regulator.sensor:
                return None
            meter = hub.regulator._read_grid()
            if meter is None:
                return None
            total = sum(_f(m.props.get("gridInputPower")) for m in hub._coordinators().values())
            mine = _f(c.props.get("gridInputPower"))
            return meter if total <= 0 else meter * mine / total
        reg = c.regulator
        if reg is None or not reg.sensor:
            return None
        return reg._read_grid()

    @callback
    def _on_update(self) -> None:
        c = self.coordinator
        t = now_ts()
        if c.available:
            p = c.props
            self.state.sample(
                t,
                p.get("gridInputPower"),
                self._meter(),
                p.get("solarInputPower"),
                p.get("outputPackPower"),
                c.soc,
                c.usable_capacity,
            )
        else:
            # Batterie injoignable : rien n'est compté jusqu'à la prochaine lecture
            self.state.sample(t, 0, None, 0, 0, None, None)
        self._store.async_delay_save(self.state.as_dict, SAVE_DELAY)

    def values(self) -> dict[str, float | None]:
        return combine([self.state], now_ts())


def group_values(hub) -> dict[str, float | None]:
    """Valeurs d'un groupe : somme de ses batteries."""
    parts = [getattr(c, "provenance", None) for c in hub._coordinators().values()]
    return combine([k.state for k in parts if k is not None], now_ts())
