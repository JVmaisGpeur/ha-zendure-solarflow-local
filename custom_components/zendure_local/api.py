"""Client HTTP minimal pour l'API locale zenSDK de Zendure.

GET  http://<ip>/properties/report  -> état complet de l'appareil
POST http://<ip>/properties/write   -> {"sn": "...", "properties": {...}}
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=8)


class ZendureError(Exception):
    """Erreur de communication avec la batterie."""


class ZendureApi:
    """Accès à une batterie Zendure en local."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        self._session = session
        self.host = host.strip().removeprefix("http://").rstrip("/")
        # L'API locale supporte mal les requêtes simultanées : on sérialise.
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}"

    async def async_get_report(self) -> dict[str, Any]:
        """Lit toutes les propriétés de l'appareil."""
        async with self._lock:
            try:
                async with self._session.get(
                    f"{self.base_url}/properties/report", timeout=TIMEOUT
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                raise ZendureError(f"Lecture impossible sur {self.host} : {err}") from err
        if not isinstance(data, dict) or "properties" not in data:
            raise ZendureError(f"Réponse inattendue de {self.host} : {data!r}")
        return data

    async def async_write(self, sn: str, properties: dict[str, Any]) -> None:
        """Écrit une ou plusieurs propriétés."""
        payload = {"sn": sn, "properties": properties}
        async with self._lock:
            try:
                async with self._session.post(
                    f"{self.base_url}/properties/write", json=payload, timeout=TIMEOUT
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                raise ZendureError(f"Écriture impossible sur {self.host} : {err}") from err
        if isinstance(data, dict) and data.get("success") is False:
            raise ZendureError(f"La batterie a refusé la commande {properties} : {data}")
