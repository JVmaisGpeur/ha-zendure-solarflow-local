"""Recherche des batteries Zendure sur le réseau local.

1. mDNS (« _zendure._tcp ») : rapide, quand la batterie s'annonce.
2. À défaut, balayage du sous-réseau local (/24 au plus) : une requête
   GET /properties/report par adresse, avec un délai court.
Ne lève jamais d'exception : en cas de souci, la liste est simplement vide.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

SERVICE_TYPE = "_zendure._tcp.local."
MDNS_WAIT = 3.0  # s
PROBE_TIMEOUT = aiohttp.ClientTimeout(total=2)
SCAN_CONCURRENCY = 48
MAX_SCAN_HOSTS = 254


@dataclass(frozen=True)
class FoundBattery:
    host: str
    sn: str
    product: str | None


async def _async_probe(session: aiohttp.ClientSession, host: str) -> FoundBattery | None:
    try:
        async with session.get(f"http://{host}/properties/report", timeout=PROBE_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data: Any = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
        return None
    if not isinstance(data, dict) or "properties" not in data or not data.get("sn"):
        return None
    return FoundBattery(host=host, sn=str(data["sn"]), product=data.get("product"))


async def _async_mdns_hosts(hass: HomeAssistant) -> set[str]:
    hosts: set[str] = set()
    try:
        from homeassistant.components import zeroconf as ha_zeroconf
        from zeroconf import ServiceStateChange
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

        aiozc = await ha_zeroconf.async_get_async_instance(hass)
        names: set[str] = set()

        def _on_change(zeroconf, service_type, name, state_change) -> None:  # noqa: ARG001
            if state_change is not ServiceStateChange.Removed:
                names.add(name)

        browser = AsyncServiceBrowser(aiozc.zeroconf, [SERVICE_TYPE], handlers=[_on_change])
        try:
            await asyncio.sleep(MDNS_WAIT)
        finally:
            await browser.async_cancel()
        for name in names:
            info = AsyncServiceInfo(SERVICE_TYPE, name)
            if await info.async_request(aiozc.zeroconf, 1500):
                hosts.update(a for a in info.parsed_addresses() if ":" not in a)
    except Exception as err:  # noqa: BLE001 - la recherche ne doit jamais bloquer l'ajout
        _LOGGER.debug("Recherche mDNS impossible : %s", err)
    return hosts


async def _async_subnet_hosts(hass: HomeAssistant) -> list[str]:
    hosts: list[str] = []
    try:
        from homeassistant.components import network

        for adapter in await network.async_get_adapters(hass):
            if not adapter.get("enabled"):
                continue
            for ip in adapter.get("ipv4", []):
                addr = ip.get("address")
                prefix = max(int(ip.get("network_prefix", 24)), 24)  # jamais plus large qu'un /24
                if not addr:
                    continue
                net = ipaddress.ip_network(f"{addr}/{prefix}", strict=False)
                if net.is_loopback or net.is_link_local:
                    continue
                hosts.extend(str(h) for h in net.hosts() if str(h) != addr)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Lecture des interfaces réseau impossible : %s", err)
    return list(dict.fromkeys(hosts))[: MAX_SCAN_HOSTS * 2]


async def _async_probe_all(session: aiohttp.ClientSession, hosts) -> list[FoundBattery]:
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def one(host: str) -> FoundBattery | None:
        async with sem:
            return await _async_probe(session, host)

    results = await asyncio.gather(*(one(h) for h in hosts))
    found: dict[str, FoundBattery] = {}
    for item in results:
        if item is not None:
            found.setdefault(item.sn, item)
    return list(found.values())


async def async_find_batteries(hass: HomeAssistant) -> list[FoundBattery]:
    """Batteries joignables en local, sans doublon (clé : numéro de série)."""
    session = async_get_clientsession(hass)
    found = await _async_probe_all(session, await _async_mdns_hosts(hass))
    if not found:
        found = await _async_probe_all(session, await _async_subnet_hosts(hass))
    return sorted(found, key=lambda b: tuple(int(p) for p in b.host.split(".")))


async def async_energy_sensors(hass: HomeAssistant) -> dict[str, Any]:
    """Capteurs de puissance déclarés dans le tableau de bord Énergie de HA.

    Retourne {grid_sensor, invert_grid, solar_sensor} pour ce qui est trouvé.
    Convention HA : la puissance réseau est positive quand la maison soutire,
    comme ici. Un capteur à deux sens séparés (de / vers le réseau) est ignoré.
    """
    found: dict[str, Any] = {}
    try:
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
        sources = (manager.data or {}).get("energy_sources", []) if manager else []
    except Exception as err:  # noqa: BLE001 - tableau Énergie absent ou format inattendu
        _LOGGER.debug("Tableau Énergie illisible : %s", err)
        return found
    for src in sources:
        kind = src.get("type")
        power = src.get("power_config") or {}
        if kind == "grid" and "grid_sensor" not in found:
            # Signe inversé : « stat_rate_negate » (booléen) ; certaines versions
            # rangent à la place l'entité dans « stat_rate_inverted ».
            negate = bool(power.get("stat_rate_negate") or src.get("stat_rate_negate"))
            rate = power.get("stat_rate") or src.get("stat_rate")
            inverted = power.get("stat_rate_inverted")
            if rate:
                found["grid_sensor"], found["invert_grid"] = rate, negate
            elif isinstance(inverted, str) and inverted:
                found["grid_sensor"], found["invert_grid"] = inverted, True
        elif kind == "solar" and "solar_sensor" not in found:
            rate = src.get("stat_rate") or power.get("stat_rate")
            if rate:
                found["solar_sensor"] = rate
    # On ne propose que des entités qui existent encore
    for key in ("grid_sensor", "solar_sensor"):
        if key in found and hass.states.get(found[key]) is None:
            del found[key]
    if "grid_sensor" not in found:
        found.pop("invert_grid", None)
    return found
