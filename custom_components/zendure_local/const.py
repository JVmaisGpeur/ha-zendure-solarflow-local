"""Constantes de l'intégration Zendure SolarFlow Local."""

from __future__ import annotations

import re

DOMAIN = "zendure_local"
MANUFACTURER = "Zendure"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_POWER = "max_power"
CONF_USE_RAM = "use_ram"
CONF_GRID_SENSOR = "grid_sensor"
CONF_INVERT_GRID = "invert_grid"
CONF_TARGET = "target_power"
CONF_DEADBAND = "deadband"
CONF_MIN_INTERVAL = "min_interval"
CONF_IMPORT_LIMIT = "import_limit"
CONF_SOLAR_SENSOR = "solar_sensor"
CONF_FAST_SCAN = "fast_scan_interval"
CONF_MIN_SOC = "min_soc"
CONF_MAX_SOC = "max_soc"

DEFAULT_SCAN_INTERVAL = 10  # secondes
MIN_SCAN_INTERVAL = 3
MAX_SCAN_INTERVAL = 120
DEFAULT_MAX_POWER = 3000  # W (SolarFlow 3000 Mix AC+)
DEFAULT_USE_RAM = True
DEFAULT_TARGET = 0  # W visés au compteur (0 = ni soutirage ni injection)
DEFAULT_DEADBAND = 25  # W : écart en dessous duquel on ne bouge pas
DEFAULT_MIN_INTERVAL = 1  # s minimum entre deux calculs de régulation
DEFAULT_FAST_SCAN = 2  # s : lecture de la batterie pendant la régulation
DEFAULT_IMPORT_LIMIT = 6000  # W max au compteur pendant la « charge réseau »

# Modes de fonctionnement
MODE_OFF = "off"  # Arrêt
MODE_MANUAL = "manual"  # Puissance manuelle
MODE_SMART = "smart"  # Couplage intelligent
MODE_SMART_DISCHARGE = "smart_discharge"  # Décharge intelligente
MODE_SMART_CHARGE = "smart_charge"  # Charge intelligente (surplus solaire uniquement)
MODE_SOLAR = "solar"  # Stocker le solaire (toute la production solaire)
MODE_GRID_CHARGE = "grid_charge"  # Charge réseau
MODES = [
    MODE_OFF,
    MODE_MANUAL,
    MODE_SMART,
    MODE_SMART_DISCHARGE,
    MODE_SMART_CHARGE,
    MODE_SOLAR,
    MODE_GRID_CHARGE,
]

# Valeurs d'acMode (zenSDK)
AC_MODE_CHARGE = 1  # entrée AC : la batterie se charge sur le réseau
AC_MODE_DISCHARGE = 2  # sortie AC : la batterie alimente la maison

PLATFORMS = ["binary_sensor", "button", "number", "select", "sensor", "switch"]


def pretty_model(name: str | None) -> str:
    """« solarFlow3000MixAC+ » → « SolarFlow 3000 Mix AC+ »."""
    if not name:
        return "SolarFlow"
    rest = re.sub(r"^zendure\s*", "", str(name), flags=re.I)
    head = ""
    m = re.match(r"^solar\s*flow", rest, flags=re.I)
    if m:
        head, rest = "SolarFlow", rest[m.end():]
    rest = re.sub(r"([a-z])([A-Z0-9])", r"\1 \2", rest)
    rest = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", rest)
    rest = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", rest).strip()
    return " ".join(p for p in (head, rest) if p)
