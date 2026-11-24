"""Monde simulé : batteries Zendure (API locale) + maison + compteur réseau."""

from __future__ import annotations

import asyncio
import random

from ha_stubs import ConfigEntry, FakeHass, VirtualClockLoop, load_integration  # noqa: F401

DOMAIN = "zendure_local"
GRID = "sensor.compteur_reseau"
SOLAR = "sensor.production_solaire"


class FakeBattery:
    """Batterie : délai de réaction, rampe de puissance, SOC, limites du firmware."""

    def __init__(self, loop, sn, product, packs, soc=50.0, min_soc=10, max_soc=100,
                 charge_max=2400, discharge_max=2400, ramp=600.0, dead=1.0):
        self.loop, self.sn, self.product = loop, sn, product
        self.packs = packs  # liste de packType
        self.capacity_wh = sum({5: 2880, 300: 1920, 350: 2880, 500: 2400}.get(p, 2000) for p in packs)
        self.soc = float(soc)
        self.min_soc, self.max_soc = min_soc, max_soc
        self.charge_max, self.discharge_max = charge_max, discharge_max
        self.ramp, self.dead = ramp, dead
        self.ac = 0.0  # + décharge vers la maison, − charge
        self.props = {"acMode": 1, "inputLimit": 0, "outputLimit": 0, "smartMode": 0}
        self.pending: list[tuple[float, dict]] = []
        self.online = True
        self.write_latency = 0.05
        self.drop_writes = 0
        self.soc_status = 0  # 1 = calibration du SOC en cours
        self.fault = 0
        self.commands: list[tuple[float, float]] = []  # (instant, consigne)

    def target(self) -> float:
        p = self.props
        if p.get("acMode") == 2:
            t = min(p.get("outputLimit", 0), self.discharge_max)
            return t if self.soc > self.min_soc else 0.0
        t = -min(p.get("inputLimit", 0), self.charge_max)
        return t if self.soc < self.max_soc else 0.0

    def step(self, dt: float) -> None:
        now = self.loop.time()
        while self.pending and self.pending[0][0] <= now:
            self.props.update(self.pending.pop(0)[1])
        tgt = self.target()
        d = tgt - self.ac
        self.ac += max(-self.ramp * dt, min(self.ramp * dt, d))
        self.soc -= self.ac * dt / 3600 / self.capacity_wh * 100
        self.soc = max(0.0, min(100.0, self.soc))

    def report(self) -> dict:
        ac = round(self.ac)
        return {
            "sn": self.sn, "product": self.product, "version": 4,
            "properties": {
                "electricLevel": int(round(self.soc)), "minSoc": self.min_soc * 10, "socSet": self.max_soc * 10,
                "outputHomePower": max(ac, 0), "gridInputPower": max(-ac, 0),
                "packInputPower": max(ac, 0), "outputPackPower": max(-ac, 0),
                "acMode": self.props.get("acMode"), "inputLimit": self.props.get("inputLimit"),
                "outputLimit": self.props.get("outputLimit"), "chargeMaxLimit": self.charge_max,
                "inverseMaxPower": self.discharge_max, "chargeAvailPower": 0, "dischargeAvailPower": 0,
                "derateFlag": 0, "is_error": self.fault, "hyperTmp": 3031, "packNum": len(self.packs),
                "remainOutTime": 59940, "packState": 0,
                "socStatus": self.soc_status, "batCalTime": 43200,
            },
            "packData": [{"sn": f"P{i}", "packType": t, "socLevel": int(self.soc), "maxTemp": 2971,
                          "totalVol": 5080, "batcur": 0, "maxVol": 340, "minVol": 334} for i, t in enumerate(self.packs)],
        }


def make_api_factory(batteries: dict[str, FakeBattery], api_module):
    class FakeApi:
        def __init__(self, session, host):
            self.host = host
            self.base_url = f"http://{host}"
            self.bat = batteries[host]

        async def async_get_report(self):
            await asyncio.sleep(0.05)
            if not self.bat.online:
                raise api_module.ZendureError("hors ligne")
            return self.bat.report()

        async def async_write(self, sn, properties):
            # Latence réseau différente d'une batterie à l'autre (comme en vrai)
            await asyncio.sleep(self.bat.write_latency)
            if not self.bat.online:
                raise api_module.ZendureError("hors ligne")
            b = self.bat
            if b.drop_writes > 0:  # commande acceptée mais perdue par la batterie
                b.drop_writes -= 1
                b.commands.append((b.loop.time(), None))
                return
            b.pending.append((b.loop.time() + b.dead, dict(properties)))
            tgt = properties.get("outputLimit", 0) if properties.get("acMode") == 2 else -properties.get("inputLimit", 0)
            b.commands.append((b.loop.time(), tgt))

    return FakeApi


class World:
    """Maison : consommation de base + évènements ; compteur publié chaque seconde."""

    def __init__(self, loop, hass, batteries, seed=1, noise=15.0, meter_period=1.0):
        self.loop, self.hass, self.batteries = loop, hass, batteries
        self.meter_period = meter_period
        self.rnd = random.Random(seed)
        self.noise = noise
        self.load = 400.0
        self.extra = 0.0  # gros appareil, surplus solaire (négatif)…
        self.solar = 0.0  # production des panneaux, publiée sur SOLAR
        self.log: list[tuple[float, float, dict]] = []
        self._task = None

    def grid(self) -> float:
        return self.load + self.extra - self.solar - sum(b.ac for b in self.batteries.values())

    async def run(self):
        last_meter = 0.0
        while True:
            for b in self.batteries.values():
                b.step(0.1)
            t = self.loop.time()
            if t - last_meter >= self.meter_period - 1e-6:
                g = self.grid() + self.rnd.gauss(0, self.noise)
                self.hass.set_state(GRID, round(g))
                self.hass.set_state(SOLAR, round(self.solar))
                self.log.append((t, g, {k: (round(b.ac), round(b.soc, 1)) for k, b in self.batteries.items()}))
                last_meter = t
            await asyncio.sleep(0.1)

    def start(self):
        self._task = self.loop.create_task(self.run())


def run(coro_fn):
    loop = VirtualClockLoop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_fn(loop))
    finally:
        for t in asyncio.all_tasks(loop):
            t.cancel()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()


async def setup(loop, specs: dict[str, dict], group: dict | None = None, options: dict | None = None):
    """Crée hass, les batteries et (option) un groupe. Retourne (hass, integ, batteries, entries, group_entry)."""
    hass = FakeHass(loop)
    integ = load_integration(loop)
    hass.integration = integ
    batteries = {host: FakeBattery(loop, **spec) for host, spec in specs.items()}
    import zendure_local.api as api_mod
    integ.ZendureApi = make_api_factory(batteries, api_mod)
    hass.set_state(GRID, 0)
    opts = {"grid_sensor": GRID, "min_interval": 1, "fast_scan_interval": 2, **(options or {})}
    entries = {}
    for host, b in batteries.items():
        e = ConfigEntry(DOMAIN, f"Zendure {b.product}", {"host": host}, dict(opts), unique_id=b.sn)
        entries[host] = await hass.config_entries.add(e)
    gentry = None
    if group is not None:
        members = [entries[h].entry_id for h in group["hosts"]]
        gentry = ConfigEntry(DOMAIN, group.get("name", "Batteries"),
                             {"entry_type": "group", "name": group.get("name", "Batteries"), "members": members},
                             {**opts, **group.get("options", {})})
        await hass.config_entries.add(gentry)
    return hass, integ, batteries, entries, gentry


def entity(hass, entry, key):
    for ent in hass.entities.get(entry.entry_id, []):
        if ent.translation_key == key:
            return ent
    raise KeyError(key)
