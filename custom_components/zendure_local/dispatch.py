"""Répartition d'une consigne de groupe entre plusieurs batteries.

Module pur (sans Home Assistant) pour pouvoir être testé simplement.

Règles garanties :
- G6 : toutes les parts ont le signe de la consigne totale (jamais une batterie en charge
  pendant qu'une autre décharge) ;
- G7 : chaque part respecte la limite de sa batterie (0 si elle ne peut pas aller dans ce
  sens : SOC min / max, SOC cible, indisponible) ; le surplus est reporté sur les autres ;
- G9 : la somme ne dépasse jamais ce que les batteries disponibles peuvent faire ;
- G12 : la somme des parts des batteries d'un même circuit ne dépasse jamais sa limite.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SIMULTANEOUS = "simultaneous"
SOC_BALANCE = "soc_balance"
PRIORITY = "priority"
STEP = 10  # W : précision des consignes de la batterie


@dataclass
class Member:
    id: str
    soc: float = 50.0
    min_soc: float = 0.0
    max_soc: float = 100.0
    capacity: float = 1.0  # kWh (pour l'équilibrage des SOC)
    max_charge: float = 0.0  # W, > 0
    max_discharge: float = 0.0  # W, > 0
    can_charge: bool = True  # faux : SOC max, SOC cible atteint, indisponible…
    can_discharge: bool = True  # faux : SOC min, indisponible…


@dataclass
class Circuit:
    members: set[str] = field(default_factory=set)
    limit: float = 0.0  # W, en charge comme en décharge


def _cap(m: Member, sign: int) -> float:
    if sign > 0:
        return m.max_discharge if m.can_discharge else 0.0
    return m.max_charge if m.can_charge else 0.0


def _weight(m: Member, sign: int, strategy: str, cap: float) -> float:
    if strategy == SOC_BALANCE:
        # À SOC égaux, part au prorata de la capacité (kWh) : les SOC évoluent au même rythme.
        # La batterie la plus pleine (décharge) ou la plus vide (charge) prend une part plus
        # grande (marge au carré), ce qui fait converger les SOC.
        room = (m.soc - m.min_soc) if sign > 0 else (m.max_soc - m.soc)
        return max(m.capacity, 0.01) * max(room, 0.5) ** 2
    return cap  # simultané : au prorata de la puissance possible


def _fill(amount: float, ids: list[str], caps: dict[str, float], weights: dict[str, float]) -> dict[str, float]:
    """Répartit amount au prorata des poids sans dépasser les plafonds (remplissage par niveaux)."""
    parts = {i: 0.0 for i in ids}
    active = [i for i in ids if caps[i] > 0 and weights[i] > 0]
    remaining = amount
    for _ in range(len(ids) + 1):
        if remaining <= 1e-9 or not active:
            break
        total_w = sum(weights[i] for i in active)
        over = []
        for i in active:
            share = remaining * weights[i] / total_w
            if parts[i] + share >= caps[i] - 1e-9:
                over.append(i)
        if not over:
            for i in active:
                parts[i] += remaining * weights[i] / total_w
            remaining = 0
            break
        for i in over:
            remaining -= caps[i] - parts[i]
            parts[i] = caps[i]
            active.remove(i)
    return parts


def _apply_circuits(parts: dict[str, float], caps: dict[str, float], circuits: list[Circuit]) -> bool:
    """Réduit les parts des circuits en dépassement ; gèle leurs plafonds. Vrai si changement."""
    changed = False
    for c in circuits:
        ids = [i for i in parts if i in c.members]
        used = sum(parts[i] for i in ids)
        if c.limit > 0 and used > c.limit + 1e-6:
            k = c.limit / used
            for i in ids:
                parts[i] *= k
                caps[i] = parts[i]
            changed = True
    return changed


def capability(members: list[Member], sign: int, circuits: list[Circuit] | None = None) -> float:
    """Puissance maximale possible dans un sens (+1 décharge, −1 charge), circuits compris."""
    return sum(abs(v) for v in dispatch(sign * 1e9, members, SIMULTANEOUS, None, circuits, rounding=False).values())


def dispatch(
    total: float,
    members: list[Member],
    strategy: str = SOC_BALANCE,
    priority_order: list[str] | None = None,
    circuits: list[Circuit] | None = None,
    rounding: bool = True,
) -> dict[str, float]:
    """Retourne la part de chaque batterie (W, + décharge, − charge)."""
    result = {m.id: 0.0 for m in members}
    if not members or abs(total) < 1e-9:
        return result
    sign = 1 if total > 0 else -1
    amount = abs(total)
    circuits = [c for c in (circuits or []) if c.limit > 0 and c.members]
    by_id = {m.id: m for m in members}
    caps = {m.id: _cap(m, sign) for m in members}

    if strategy == PRIORITY:
        order = [i for i in (priority_order or []) if i in by_id]
        order += [m.id for m in members if m.id not in order]
        circuit_left = [c.limit for c in circuits]
        parts = {i: 0.0 for i in order}
        remaining = amount
        for i in order:
            room = caps[i]
            for k, c in enumerate(circuits):
                if i in c.members:
                    room = min(room, circuit_left[k])
            give = max(0.0, min(remaining, room))
            parts[i] = give
            remaining -= give
            for k, c in enumerate(circuits):
                if i in c.members:
                    circuit_left[k] -= give
            if remaining <= 1e-9:
                break
    else:
        ids = [m.id for m in members]
        weights = {i: _weight(by_id[i], sign, strategy, caps[i]) for i in ids}
        parts = _fill(amount, ids, caps, weights)
        # Circuits partagés : on réduit, on gèle, et on reporte le reste sur les autres
        for _ in range(len(circuits) + 2):
            if not _apply_circuits(parts, caps, circuits):
                break
            left = amount - sum(parts.values())
            if left <= 1e-6:
                break
            free = [i for i in ids if caps[i] - parts[i] > 1e-6]
            room = {i: caps[i] - parts[i] for i in free}
            extra = _fill(left, free, room, {i: weights[i] for i in free})
            for i, v in extra.items():
                parts[i] += v

    for i, v in parts.items():
        if rounding:
            v = int(v // STEP) * STEP  # arrondi vers le bas : jamais au-dessus d'une limite
        result[i] = sign * v
    return result
