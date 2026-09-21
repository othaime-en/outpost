"""
HTTP Client

Thin wrapper over httpx. `OutpostClient` is the API-key-authenticated
client used by every command except the auth ones (which use a bearer
token instead, since the API key doesn't exist yet at that point).

`follow_redirects=True` matters here, not just as a nicety: FastAPI's
default `redirect_slashes` behavior means the collection routes
(`GET/POST /environments`, `GET /audit`, `GET /teams`) are registered as
`.../` and issue a 307 for the no-slash form. httpx does not follow
redirects by default, so calling these without either matching the
trailing slash exactly or enabling this would silently return an empty,
un-parseable body instead of the real response.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Optional, TypeVar

import httpx
from rich.console import Console

from outpost.config import get_api_key, get_endpoint

console = Console()

DEFAULT_TIMEOUT = 30.0

F = TypeVar("F", bound=Callable[..., Any])


class ApiError(Exception):
    """
    Raised for any non-2xx response that isn't handled as a special case
    (currently just 401, which prints its own message and exits directly).
    `detail` is the API's own `{"detail": "..."}` message when present,
    else a generic fallback built from the raw response body/status.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def handle_api_errors(fn: F) -> F:
    """
    Command decorator: turns an ApiError into a clean one-line message and
    exit code 1 instead of a raw traceback. Every command that talks to
    the API should be wrapped in this — network/timeout errors and 401s
    are already handled inside OutpostClient itself and exit on their own,
    so this only needs to catch the general case.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ApiError as exc:
            console.print(f"[red]✗ {exc.detail}[/red]")
            raise SystemExit(1) from exc

    return wrapper  # type: ignore[return-value]


class OutpostClient:
    def __init__(self) -> None:
        self.base = get_endpoint().rstrip("/")
        self.key = get_api_key()

    def _headers(self) -> dict[str, str]:
        if not self.key:
            console.print(
                "[red]✗ No API key configured.[/red] "
                "Run [bold]outpost auth key generate[/bold] first."
            )
            raise SystemExit(1)
        return {"X-API-Key": self.key}

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text or f"HTTP {response.status_code}"
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
        return response.text or f"HTTP {response.status_code}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base}{path}"
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers(),
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
                **kwargs,
            )
        except httpx.ConnectError as exc:
            console.print(
                f"[red]✗ Could not reach {self.base}.[/red] "
                "Check that the API endpoint is correct and reachable "
                "(see [bold]~/.outpost/config.yaml[/bold])."
            )
            raise SystemExit(1) from exc
        except httpx.TimeoutException as exc:
            console.print(f"[red]✗ Request to {url} timed out after {DEFAULT_TIMEOUT:.0f}s.[/red]")
            raise SystemExit(1) from exc

        if response.status_code == 401:
            console.print(
                "[red]✗ Unauthorized.[/red] Your API key may be invalid or revoked — "
                "run [bold]outpost auth key generate[/bold] to issue a new one."
            )
            raise SystemExit(1)

        if response.status_code >= 400:
            raise ApiError(response.status_code, self._extract_detail(response))

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        return self._request("POST", path, json=json or {})

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def patch(self, path: str, json: dict[str, Any]) -> Any:
        return self._request("PATCH", path, json=json)