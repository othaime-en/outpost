"""
HTTP Client

Thin wrapper over httpx. `IDPClient` is the API-key-authenticated client
used by every command except the auth ones (which use a bearer token
instead, since the API key doesn't exist yet at that point).
"""

from typing import Optional

import httpx
from rich.console import Console

from outpost.config import get_api_key, get_endpoint

console = Console()


class IDPClient:
    def __init__(self) -> None:
        self.base = get_endpoint()
        self.key = get_api_key()

    def _headers(self) -> dict[str, str]:
        if not self.key:
            console.print(
                "[red]✗ No API key configured.[/red] "
                "Run [bold]outpost auth key generate[/bold] first."
            )
            raise SystemExit(1)
        return {"X-API-Key": self.key}

    def get(self, path: str):
        r = httpx.get(f"{self.base}{path}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json: Optional[dict] = None):
        r = httpx.post(f"{self.base}{path}", json=json or {}, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def delete(self, path: str):
        r = httpx.delete(f"{self.base}{path}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def patch(self, path: str, json: dict):
        r = httpx.patch(f"{self.base}{path}", json=json, headers=self._headers())
        r.raise_for_status()
        return r.json()