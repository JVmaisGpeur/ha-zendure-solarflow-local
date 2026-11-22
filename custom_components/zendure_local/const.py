"""Constantes de l'intégration Zendure SolarFlow Local."""

from __future__ import annotations

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

DEFAULT_SCAN_INTERVAL = 10  # secondes
MIN_SCAN_INTERVAL = 3
MAX_SCAN_INTERVAL = 120
DEFAULT_MAX_POWER = 3000  # W (SolarFlow 3000 Mix AC+)
DEFAULT_USE_RAM = True
DEFAULT_TARGET = 0  # W visés au compteur (0 = ni soutirage ni injection)
DEFAULT_DEADBAND = 25  # W : écart en dessous duquel on ne bouge pas
DEFAULT_MIN_INTERVAL = 5  # s entre deux commandes envoyées à la batterie
DEFAULT_IMPORT_LIMIT = 6000  # W max au compteur pendant la « charge intelligente »

# Modes de fonctionnement
MODE_OFF = "off"  # Arrêt
MODE_MANUAL = "manual"  # Puissance manuelle
MODE_SMART = "smart"  # Couplage intelligent
MODE_SMART_DISCHARGE = "smart_discharge"  # Décharge intelligente
MODE_SMART_CHARGE = "smart_charge"  # Charge intelligente
MODE_SOLAR = "solar"  # Stocker le solaire
MODES = [MODE_OFF, MODE_MANUAL, MODE_SMART, MODE_SMART_DISCHARGE, MODE_SMART_CHARGE, MODE_SOLAR]

# Valeurs d'acMode (zenSDK)
AC_MODE_CHARGE = 1  # entrée AC : la batterie se charge sur le réseau
AC_MODE_DISCHARGE = 2  # sortie AC : la batterie alimente la maison

PLATFORMS = ["binary_sensor", "number", "select", "sensor"]
