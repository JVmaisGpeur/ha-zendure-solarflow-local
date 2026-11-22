"""Recherche des batteries : filtrage des réponses, dédoublonnage, repli sur le sous-réseau."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import ha_stubs  # noqa: E402,F401

from custom_components.zendure_local import discovery as d  # noqa: E402

REPLIES = {
    "192.168.1.20": {"sn": "AC+SN", "product": "solarFlow2400AC+", "properties": {}},
    "192.168.1.21": {"sn": "ACSN", "product": "solarFlow2400AC", "properties": {}},
    "192.168.1.22": {"sn": "AC+SN", "product": "solarFlow2400AC+", "properties": {}},  # doublon
    "192.168.1.30": {"hello": "autre appareil"},
}


class Resp:
    def __init__(self, data):
        self.data, self.status = data, 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        return self.data


class Session:
    def get(self, url, timeout=None):
        host = url.split("/")[2]
        if host not in REPLIES:
            raise d.aiohttp.ClientError("injoignable")
        return Resp(REPLIES[host])


async def run(mdns, subnet):
    async def m(hass):
        return set(mdns)

    async def s(hass):
        return list(subnet)

    d._async_mdns_hosts, d._async_subnet_hosts = m, s
    d.async_get_clientsession = lambda hass: Session()
    return await d.async_find_batteries(None)


ok = True
r = asyncio.run(run(["192.168.1.21"], []))
ok &= [b.sn for b in r] == ["ACSN"]
r = asyncio.run(run([], [f"192.168.1.{i}" for i in range(1, 40)]))
ok &= [(b.host, b.sn) for b in r] == [("192.168.1.20", "AC+SN"), ("192.168.1.21", "ACSN")]
r = asyncio.run(run([], ["192.168.1.30", "192.168.1.99"]))
ok &= r == []
from custom_components.zendure_local.const import pack_capacity  # noqa: E402

ok &= pack_capacity({"packType": 70, "sn": "BO4X1"}, "solarFlow3000MixAC+") == 8.0  # pack intégré Mix
ok &= pack_capacity({"packType": 70, "sn": "BO4X1"}, "solarFlow800") == 0.96  # AB1000S
ok &= pack_capacity({"packType": 500, "sn": "JO4A1"}, "solarFlow2400AC+") == 2.40
ok &= pack_capacity({"packType": 12, "sn": "FO4A1"}, "x") == 2.88  # repli sur le n° de série
ok &= pack_capacity({"packType": 12, "sn": "ZZZ"}, "x") is None
# Tableau de bord Énergie → capteurs proposés
import types  # noqa: E402

PREFS = {"energy_sources": [
    {"type": "solar", "stat_rate": "sensor.pv_power"},
    {"type": "grid", "power_config": {"stat_rate": "sensor.grid_power", "stat_rate_negate": True}},
]}


class _Mgr:
    data = PREFS


async def _get_manager(hass):
    return _Mgr()


sys.modules["homeassistant.components.energy"] = types.ModuleType("homeassistant.components.energy")
sys.modules["homeassistant.components.energy.data"] = types.SimpleNamespace(async_get_manager=_get_manager)


class _States:
    def get(self, eid):
        return object() if eid in ("sensor.pv_power", "sensor.grid_power") else None


hass = types.SimpleNamespace(states=_States())
got = asyncio.run(d.async_energy_sensors(hass))
ok &= got == {"grid_sensor": "sensor.grid_power", "invert_grid": True, "solar_sensor": "sensor.pv_power"}
PREFS["energy_sources"] = [{"type": "grid", "stat_rate": "sensor.absent"}]
ok &= asyncio.run(d.async_energy_sensors(hass)) == {}
print("discovery :", "OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
