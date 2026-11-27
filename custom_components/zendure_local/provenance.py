"""Z4 (v1.7.0) : provenance de l'énergie de charge et stock par origine.

Chaque kWh qui entre dans la batterie est attribué au réseau ou au solaire, à chaque
lecture de la batterie (rectangles à gauche, comme les compteurs d'énergie) :

    P_réseau = min(P_charge, max(0, P_compteur))    P_solaire = P_charge − P_réseau

- P_charge : entrée AC de la batterie (gridInputPower) ; P_compteur : puissance au point
  de livraison, positive en soutirage (la part de cette batterie dans un groupe).
- Les entrées PV en courant continu (solarInputPower) sont toujours solaires.
- L'énergie qui entre dans le pack (outputPackPower) est répartie entre les deux stocks
  au prorata des deux origines de l'entrée à cet instant (pertes de charge déduites).
- Les stocks suivent l'énergie stockée, electric_level × usable_capacity : en décharge
  et au recalage, les deux baissent dans la même proportion (mélange moyen).
- Un stock d'origine inconnue (installation, module ajouté) est compté 50 / 50 ;
  `initial_grid` dit quelle part du stock réseau en vient encore.

Ce module ne fait que compter : aucune requête, aucune écriture vers la batterie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

MAX_GAP = 300.0  # s : au-delà, pas d'intégration (même règle que les compteurs d'énergie)
HOUR = 3600.0
KEEP_HOURS = 25


def _f(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) and v > 0 else 0.0


@dataclass
class Provenance:
    """État pur (sans Home Assistant) du comptage pour une batterie."""

    grid_in: float = 0.0  # kWh côté prise, venus du réseau
    solar_in: float = 0.0  # kWh venus du solaire (AC + PV en continu)
    stock_grid: float | None = None  # kWh dans la batterie, d'origine réseau
    stock_solar: float | None = None
    initial_grid: float = 0.0  # part du stock réseau encore issue d'un stock d'origine inconnue
    capacity: float | None = None  # dernière capacité utile vue (kWh)
    hours: dict[int, list[float]] = field(default_factory=dict)  # heure → [réseau, solaire] chargés
    _last: tuple[float, float, float, float, float] | None = field(default=None, repr=False)

    # ------------------------------------------------------------ mesure
    def sample(
        self,
        t: float,
        p_ac: Any,
        meter: float | None,
        p_pv: Any,
        p_pack: Any,
        level: Any,
        capacity: Any,
    ) -> None:
        """Une lecture de la batterie à l'instant t (secondes).

        meter : puissance au compteur attribuée à cette batterie (W, + soutirage),
        None sans capteur de compteur (toute la charge AC est alors comptée réseau).
        """
        if self._last is not None:
            t0, ac, grid, pv, pack = self._last
            dt = t - t0
            if 0 < dt <= MAX_GAP:
                self._integrate(t0, dt, ac, grid, pv, pack)
        ac, pv, pack = _f(p_ac), _f(p_pv), _f(p_pack)
        grid = ac if meter is None else min(ac, max(0.0, float(meter)))
        self._last = (t, ac, grid, pv, pack)
        self.recalibrate(level, capacity)
        self._prune(t)

    def _integrate(self, t0: float, dt: float, ac: float, grid: float, pv: float, pack: float) -> None:
        k = dt / 3_600_000  # W·s → kWh
        e_grid, e_solar = grid * k, (ac - grid + pv) * k
        self.grid_in += e_grid
        self.solar_in += e_solar
        bucket = self.hours.setdefault(int(t0 // HOUR), [0.0, 0.0])
        bucket[0] += e_grid
        bucket[1] += e_solar
        e_pack = pack * k
        if e_pack <= 0 or self.stock_grid is None or self.stock_solar is None:
            return
        source = ac + pv
        if source > 0:
            share = grid / source
        else:
            total = self.stock_grid + self.stock_solar
            share = self.stock_grid / total if total > 0 else 0.5
        self.stock_grid += e_pack * share
        self.stock_solar += e_pack * (1 - share)

    # ------------------------------------------------------------ recalage
    def recalibrate(self, level: Any, capacity: Any) -> None:
        """Ramène la somme des stocks à electric_level × usable_capacity, proportions gardées."""
        try:
            lvl, cap = float(level), float(capacity)
        except (TypeError, ValueError):
            return
        if not (math.isfinite(lvl) and math.isfinite(cap)) or cap <= 0:
            return
        lvl = min(100.0, max(0.0, lvl))
        target = lvl / 100 * cap
        if self.stock_grid is None or self.stock_solar is None:
            self.stock_grid = self.stock_solar = self.initial_grid = target / 2
            self.capacity = cap
            return
        if self.capacity is not None and cap > self.capacity + 0.01:
            # Module ajouté : son énergie est d'origine inconnue (50 / 50, stock de départ)
            extra = lvl / 100 * (cap - self.capacity)
            self.stock_grid += extra / 2
            self.stock_solar += extra / 2
            self.initial_grid += extra / 2
        self.capacity = cap
        total = self.stock_grid + self.stock_solar
        if total <= 1e-9:
            self.stock_grid = self.stock_solar = target / 2
            self.initial_grid = target / 2
            return
        f = target / total
        self.stock_grid *= f
        self.stock_solar *= f
        self.initial_grid = min(self.initial_grid * f, self.stock_grid)

    # ------------------------------------------------------------ lecture
    @property
    def stored_solar_share(self) -> float | None:
        if self.stock_grid is None or self.stock_solar is None:
            return None
        total = self.stock_grid + self.stock_solar
        return None if total <= 0 else 100 * self.stock_solar / total

    @property
    def initial_share(self) -> float | None:
        """Part (%) du stock réseau encore issue d'un stock d'origine inconnue."""
        if self.stock_grid is None:
            return None
        return 0.0 if self.stock_grid <= 1e-9 else min(100.0, 100 * self.initial_grid / self.stock_grid)

    def last_24h(self, t: float) -> tuple[float, float]:
        start = int((t - 24 * HOUR) // HOUR)
        g = s = 0.0
        for h, (eg, es) in self.hours.items():
            if h > start:
                g += eg
                s += es
        return g, s

    def _prune(self, t: float) -> None:
        oldest = int(t // HOUR) - KEEP_HOURS
        for h in [h for h in self.hours if h < oldest]:
            del self.hours[h]

    # ------------------------------------------------------------ persistance
    def as_dict(self) -> dict[str, Any]:
        return {
            "grid_in": self.grid_in,
            "solar_in": self.solar_in,
            "stock_grid": self.stock_grid,
            "stock_solar": self.stock_solar,
            "initial_grid": self.initial_grid,
            "capacity": self.capacity,
            "hours": {str(h): v for h, v in self.hours.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Provenance:
        p = cls()
        if not isinstance(data, dict):
            return p
        try:
            p.grid_in = float(data.get("grid_in") or 0)
            p.solar_in = float(data.get("solar_in") or 0)
            sg, ss = data.get("stock_grid"), data.get("stock_solar")
            p.stock_grid = None if sg is None else float(sg)
            p.stock_solar = None if ss is None else float(ss)
            p.initial_grid = float(data.get("initial_grid") or 0)
            cap = data.get("capacity")
            p.capacity = None if cap is None else float(cap)
            p.hours = {int(h): [float(v[0]), float(v[1])] for h, v in (data.get("hours") or {}).items()}
        except (TypeError, ValueError, IndexError):
            return cls()
        return p


def combine(parts: list[Provenance], t: float) -> dict[str, float | None]:
    """Valeurs d'un groupe : somme des batteries (et parts recalculées sur les sommes)."""
    values = [p for p in parts if p is not None]
    if not values:
        return dict.fromkeys(
            ("energy_charged_grid", "energy_charged_solar", "stored_energy_grid", "stored_energy_solar",
             "stored_solar_share", "initial_share", "charged_24h_grid", "charged_24h_solar")
        )
    stocked = [p for p in values if p.stock_grid is not None and p.stock_solar is not None]
    sg = sum(p.stock_grid for p in stocked) if stocked else None
    ss = sum(p.stock_solar for p in stocked) if stocked else None
    ig = sum(p.initial_grid for p in stocked)
    g24 = s24 = 0.0
    for p in values:
        g, s = p.last_24h(t)
        g24 += g
        s24 += s
    total = (sg or 0) + (ss or 0)
    return {
        "energy_charged_grid": sum(p.grid_in for p in values),
        "energy_charged_solar": sum(p.solar_in for p in values),
        "stored_energy_grid": sg,
        "stored_energy_solar": ss,
        "stored_solar_share": None if sg is None or total <= 0 else 100 * ss / total,
        "initial_share": None if sg is None else (0.0 if sg <= 1e-9 else min(100.0, 100 * ig / sg)),
        "charged_24h_grid": g24,
        "charged_24h_solar": s24,
    }
