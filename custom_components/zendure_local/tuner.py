"""Réglage automatique de la régulation (auto-apprentissage passif).

Ce module ne dépend pas de Home Assistant : il reçoit des observations horodatées
et en déduit les paramètres de régulation adaptés à l'installation.

Ce qu'il apprend :
- rythme du compteur : intervalle entre deux mesures du capteur réseau ;
- bruit de la maison : fluctuation du compteur quand rien ne change ;
- réponse de la batterie : délai avant réaction et temps pour atteindre une consigne ;
- gain : réduit si une correction dépasse la cible, augmenté si elle est trop timide.

Les paramètres restent dans des bornes sûres et on garde les valeurs par défaut
tant qu'il n'y a pas assez de mesures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import pairwise
import statistics
from typing import Any

# Bornes des paramètres appris
GAIN_MIN, GAIN_MAX = 0.5, 1.0
DEADBAND_MIN, DEADBAND_MAX = 15.0, 80.0
GAP_MIN, GAP_MAX = 0.5, 10.0
SETTLE_MIN, SETTLE_MAX = 3.0, 20.0

MIN_STEP = 150.0  # W : seules les commandes assez grandes servent à mesurer la réponse
RESPONSE_WINDOW = 25.0  # s : au-delà, la batterie n'a pas suivi (limite, SOC…) → ignoré
MIN_RESPONSES = 3  # mesures de réponse avant d'utiliser les valeurs apprises
NOISE_WINDOW = 20  # échantillons pour estimer le bruit


def _ema(old: float | None, new: float, alpha: float) -> float:
    return new if old is None else old + alpha * (new - old)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class TunerState:
    """Ce qui est appris et conservé entre deux redémarrages."""

    meter_period: float | None = None  # s
    noise: float | None = None  # W (écart-type)
    dead_time: float | None = None  # s avant que la batterie commence à réagir
    response_time: float | None = None  # s pour atteindre ~85 % de la consigne
    gain: float = 0.9
    responses: int = 0
    overshoots: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TunerState:
        if not data:
            return cls()
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


@dataclass
class _Step:
    t_cmd: float
    start: float  # puissance réelle au moment de la commande
    target: float  # consigne envoyée
    error_sign: int  # sens de l'écart au compteur au moment de la commande
    t_react: float | None = None
    done: bool = False
    overshoot: bool = False
    weight: float = 1.0


@dataclass
class AutoTuner:
    """Apprend les caractéristiques de l'installation."""

    default_gain: float = 0.9
    default_deadband: float = 25.0
    default_gap: float = 1.0
    default_settle: float = 6.0
    state: TunerState = field(default_factory=TunerState)

    _last_meter_t: float | None = None
    _samples: list[float] = field(default_factory=list)
    _step: _Step | None = None
    _last_cmd_t: float = -1e9
    _dirty: bool = False

    # ------------------------------------------------------------- paramètres
    @property
    def ready(self) -> bool:
        return self.state.responses >= MIN_RESPONSES

    @property
    def gain(self) -> float:
        return _clamp(self.state.gain, GAIN_MIN, GAIN_MAX) if self.ready else self.default_gain

    @property
    def trim_delay(self) -> float:
        """Calme demandé avant d'affiner dans la zone morte : deux mesures du compteur."""
        period = self.state.meter_period or 1.0
        return _clamp(2 * period + 2, 6.0, 12.0)

    @property
    def deadband(self) -> float:
        if self.state.noise is None:
            return self.default_deadband
        return _clamp(2.0 * self.state.noise, DEADBAND_MIN, DEADBAND_MAX)

    @property
    def min_gap(self) -> float:
        if self.state.meter_period is None:
            return self.default_gap
        return _clamp(0.9 * self.state.meter_period, GAP_MIN, GAP_MAX)

    @property
    def settle_timeout(self) -> float:
        if not self.ready or self.state.response_time is None:
            return self.default_settle
        return _clamp(1.5 * self.state.response_time + 1.0, SETTLE_MIN, SETTLE_MAX)

    def take_dirty(self) -> bool:
        """Vrai si l'état a changé depuis le dernier appel (pour sauvegarder)."""
        dirty, self._dirty = self._dirty, False
        return dirty

    def reset(self) -> None:
        self.state = TunerState(gain=self.default_gain)
        self._samples.clear()
        self._step = None
        self._last_meter_t = None
        self._dirty = True

    # ------------------------------------------------------------- observations
    def on_meter(self, t: float, grid: float, error: float, battery_steady: bool = False) -> None:
        """Nouvelle mesure du compteur.

        grid : puissance réseau (W), error : écart à la cible,
        battery_steady : la batterie a atteint sa consigne (elle ne bouge plus).
        """
        if self._last_meter_t is not None:
            dt = t - self._last_meter_t
            if 0.05 < dt < 60:
                self.state.meter_period = _ema(self.state.meter_period, dt, 0.05)
        self._last_meter_t = t

        # Bruit : variation d'une mesure à la suivante tant que la batterie est stable.
        # Les petites corrections dues au bruit ne l'empêchent donc pas d'être mesuré.
        if battery_steady:
            self._samples.append(grid)
            if len(self._samples) >= 2:
                diffs = [b - a for a, b in pairwise(self._samples)]
                diffs = [d for d in diffs if abs(d) < 300]  # un vrai changement de conso n'est pas du bruit
                if len(self._samples) >= NOISE_WINDOW and len(diffs) >= NOISE_WINDOW // 2:
                    # Estimateur robuste (écart absolu médian) : les vrais changements de
                    # consommation de la maison ne gonflent plus le « bruit » ni la zone morte.
                    med = statistics.median(diffs)
                    mad = statistics.median(abs(d - med) for d in diffs)
                    sd = 1.4826 * mad / 1.414  # écart-type d'une différence = √2 × bruit
                    self.state.noise = _ema(self.state.noise, sd, 0.1)
                    self._dirty = True
                    self._samples.clear()
        else:
            self._samples.clear()

        # Dépassement : l'écart change de signe nettement pendant la réponse
        s = self._step
        if s is not None and not s.overshoot and s.t_react is not None:
            if error * s.error_sign < 0 and abs(error) > 2 * self.deadband:
                s.overshoot = True

    def on_command(self, t: float, measured: float | None, target: float, error: float, weight: float = 1.0) -> None:
        """Une nouvelle consigne vient d'être envoyée."""
        self._last_cmd_t = t
        if self._step is not None and not self._step.done:
            self._close_step(t, interrupted=True)
        if measured is None or abs(target - measured) < MIN_STEP:
            self._step = None
            return
        self._step = _Step(t, measured, target, 1 if error > 0 else -1, weight=weight)

    def on_battery(self, t: float, measured: float | None) -> None:
        """Nouvelle lecture de la puissance réelle de la batterie."""
        s = self._step
        if s is None or measured is None or s.done:
            return
        span = s.target - s.start
        progress = (measured - s.start) / span if span else 1.0
        if s.t_react is None and progress > 0.1:
            s.t_react = t
        if progress >= 0.85:
            s.done = True
            dead = (s.t_react or t) - s.t_cmd
            resp = t - s.t_cmd
            a = 0.3 * s.weight
            self.state.dead_time = _ema(self.state.dead_time, dead, min(a, 1.0))
            self.state.response_time = _ema(self.state.response_time, resp, min(a, 1.0))
            self.state.responses += 1
            self._dirty = True
            # Laisse la fenêtre ouverte pour détecter un dépassement ; clôture plus tard
        elif t - s.t_cmd > RESPONSE_WINDOW:
            self._step = None  # la batterie n'a pas suivi (limite atteinte) : on ignore

    def on_tick(self, t: float, error: float) -> None:
        """Appel régulier : clôture la mesure en cours une fois la batterie stabilisée."""
        s = self._step
        if s is None or not s.done:
            return
        if t - s.t_cmd > self.settle_timeout + 2:
            # Écart encore important dans le même sens → correction trop timide
            timid = error * s.error_sign > 0 and abs(error) > 3 * self.deadband
            self._adapt_gain(s.overshoot, timid)
            self._step = None

    def _close_step(self, t: float, interrupted: bool) -> None:
        s = self._step
        if s and s.done:
            self._adapt_gain(s.overshoot, False)
        self._step = None

    def _adapt_gain(self, overshoot: bool, timid: bool) -> None:
        g = self.state.gain
        if overshoot:
            g *= 0.9
            self.state.overshoots += 1
        elif timid:
            g *= 1.05
        else:
            g += 0.01 * (self.default_gain - g)  # retour doux vers la valeur par défaut
        self.state.gain = _clamp(g, GAIN_MIN, GAIN_MAX)
        self._dirty = True
