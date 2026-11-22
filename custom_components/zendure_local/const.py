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
# v1.3.0
CONF_MAX_CHARGE_POWER = "max_charge_power"
CONF_MAX_DISCHARGE_POWER = "max_discharge_power"
CONF_CIRCUIT_LIMIT = "circuit_limit"
CONF_CAPACITY = "capacity"
# Groupe
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_BATTERY = "battery"
ENTRY_TYPE_GROUP = "group"
CONF_NAME = "name"
CONF_MEMBERS = "members"
CONF_PRIORITY = "priority_order"
CONF_CIRCUIT_A_MEMBERS = "circuit_a_members"
CONF_CIRCUIT_A_LIMIT = "circuit_a_limit"
CONF_CIRCUIT_B_MEMBERS = "circuit_b_members"
CONF_CIRCUIT_B_LIMIT = "circuit_b_limit"
CONF_CIRCUIT_A_CHARGE_LIMIT = "circuit_a_charge_limit"
CONF_CIRCUIT_B_CHARGE_LIMIT = "circuit_b_charge_limit"
# Circuits les plus courants : (sortie W, charge W). Repris des « groupes de fusible »
# de l'intégration officielle Zendure-HA, plus les calibres français 10 / 16 / 20 A.
CIRCUIT_PRESETS: dict[str, tuple[int, int]] = {
    "600_1200": (600, 1200),
    "600_2400": (600, 2400),
    "800_1200": (800, 1200),
    "800_2400": (800, 2400),
    "1200": (1200, 1200),
    "2000": (2000, 2000),
    "2300": (2300, 2300),
    "2400": (2400, 2400),
    "3600": (3600, 3600),
    "4000": (4000, 4000),
    "4600": (4600, 4600),
    "5000": (5000, 5000),
}
CIRCUIT_PRESET_CUSTOM = "custom"
DATA_PREVIOUS_MODES = "previous_modes"
MIN_MEMBERS, MAX_MEMBERS = 2, 4

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
MAX_IMPORT_LIMIT = 36000
DEFAULT_CHARGE_TARGET_SOC = 100  # %
CHARGE_TARGET_HYSTERESIS = 3  # points : reprise de la charge sous cible − 3

# Modes de fonctionnement
MODE_OFF = "off"  # Arrêt
MODE_MANUAL = "manual"  # Puissance manuelle
MODE_SMART = "smart"  # Couplage intelligent
MODE_SMART_DISCHARGE = "smart_discharge"  # Décharge intelligente
MODE_SMART_CHARGE = "smart_charge"  # Charge intelligente (surplus solaire uniquement)
MODE_SOLAR = "solar"  # Stocker le solaire (toute la production solaire)
MODE_GRID_CHARGE = "grid_charge"  # Charge réseau
MODE_GROUP = "group"  # Pilotée par le groupe (batterie membre uniquement)
MODES = [
    MODE_OFF,
    MODE_MANUAL,
    MODE_SMART,
    MODE_SMART_DISCHARGE,
    MODE_SMART_CHARGE,
    MODE_SOLAR,
    MODE_GRID_CHARGE,
]

# États de la régulation (capteur regulation_state, contrat d'interface v1)
STATE_OFF = "off"
STATE_MANUAL = "manual"
STATE_REGULATING = "regulating"
STATE_GRID_CHARGING = "grid_charging"
STATE_TARGET_REACHED = "target_reached"
STATE_IMPORT_LIMITED = "import_limited"
STATE_SOC_MAX = "soc_max_reached"
STATE_SOC_MIN = "soc_min_reached"
STATE_SENSOR_UNAVAILABLE = "sensor_unavailable"
STATE_ERROR = "error"
STATE_DEGRADED = "degraded"  # groupe uniquement
STATE_GROUP = "group"  # batterie membre pilotée par son groupe
REGULATION_STATES = [
    STATE_OFF,
    STATE_MANUAL,
    STATE_REGULATING,
    STATE_GRID_CHARGING,
    STATE_TARGET_REACHED,
    STATE_IMPORT_LIMITED,
    STATE_SOC_MAX,
    STATE_SOC_MIN,
    STATE_SENSOR_UNAVAILABLE,
    STATE_ERROR,
]
BATTERY_REGULATION_STATES = [*REGULATION_STATES, STATE_GROUP]
GROUP_REGULATION_STATES = [*REGULATION_STATES, STATE_DEGRADED]

# Stratégies de répartition d'un groupe
STRATEGY_SIMULTANEOUS = "simultaneous"
STRATEGY_SOC_BALANCE = "soc_balance"
STRATEGY_PRIORITY = "priority"
STRATEGIES = [STRATEGY_SIMULTANEOUS, STRATEGY_SOC_BALANCE, STRATEGY_PRIORITY]
DEFAULT_STRATEGY = STRATEGY_SOC_BALANCE

# Capacité des packs selon packType (relevé sur l'API locale, nov. 2026)
PACK_CAPACITY_KWH = {
    5: 2.88,  # AB3000
    300: 1.92,  # AB2000S
    350: 2.88,  # AB3000L
    500: 2.40,  # I2400 (pack intégré de la 2400 AC+)
}
PACK_NAMES = {5: "AB3000", 300: "AB2000S", 350: "AB3000L", 500: "I2400"}
# packType 70 n'est pas unique : pack intégré de 8 kWh sur les modèles « Mix »
# (3000 / 4000 Mix AC+), mais AB1000S (0,96 kWh) sur une SolarFlow 800.
PACK_TYPE_MIX = 70
MIX_INTERNAL_KWH = 8.0
# À défaut de packType connu : 1re lettre du numéro de série du pack
SERIAL_PREFIX_KWH = {"B": 0.96, "C": 1.92, "F": 2.88, "G": 2.88, "J": 2.40}


def pack_capacity(pack: dict, product: str | None) -> float | None:
    """Capacité d'un pack (kWh), ou None si on ne sait pas la déterminer."""
    ptype = pack.get("packType")
    try:
        ptype = int(ptype) if ptype is not None else None
    except (TypeError, ValueError):
        ptype = None
    if ptype == PACK_TYPE_MIX and "mix" in str(product or "").lower():
        return MIX_INTERNAL_KWH
    if ptype in PACK_CAPACITY_KWH:
        return PACK_CAPACITY_KWH[ptype]
    sn = str(pack.get("sn") or "")
    if sn[:1] == "A":
        return 2.40 if sn[3:4] == "3" else 0.96
    return SERIAL_PREFIX_KWH.get(sn[:1])

# Signal envoyé à chaque nouvelle lecture d'une batterie (utilisé par les groupes)
SIGNAL_BATTERY_UPDATE = f"{DOMAIN}_battery_update"

# Valeurs d'acMode (zenSDK)
AC_MODE_CHARGE = 1  # entrée AC : la batterie se charge sur le réseau
AC_MODE_DISCHARGE = 2  # sortie AC : la batterie alimente la maison

PLATFORMS = ["binary_sensor", "button", "number", "select", "sensor", "switch"]


def pretty_model(name: str | None) -> str:
    """« solarFlow3000MixAC+ » → « SolarFlow 3000 Mix AC Plus »."""
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
    # « + » écrit en toutes lettres : sinon « 2400 AC+ » et « 2400 AC » donnent
    # les mêmes identifiants d'entités et HA ajoute « _2 » à la seconde batterie.
    rest = re.sub(r"\s*\+$", " Plus", rest)
    return " ".join(p for p in (head, rest) if p)
