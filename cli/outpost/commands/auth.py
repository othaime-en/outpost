"""
Authentication Commands

`outpost auth login`        — log in via GitHub and get a usable API key in one step
`outpost auth key generate` — re-issue an API key from an existing (unexpired) login token

DEFAULT LOGIN FLOW: a short-lived local HTTP server on 127.0.0.1, matching
the "loopback interface redirection" pattern `gh auth login`, `gcloud auth
login`, and VS Code all use — see api/app/routers/auth.py's CLI-login
constants block for the server-side half of this and why it's safe
without signing `state`.

This replaced the original copy/paste flow, which turned out to be
fundamentally broken, not just clunky: the web UI's AuthCallback.tsx
reads the token from the URL fragment, scrubs it from the visible URL,
and redirects into the dashboard within the same render pass — there was
never a point at which a human could actually read and copy it. `--manual`
exists for the one case the loopback flow can't cover (CLI running over
SSH on a different machine than the browser) and talks to a dedicated
backend-rendered page instead (`state=cli-manual`) rather than that route.
"""

from __future__ import annotations

import html as html_module
import http.server
import socket
import threading
import webbrowser
from typing import Optional
from urllib.parse import parse_qs, urlparse

import click
import httpx
from rich.console import Console

from outpost.config import get_endpoint, get_token, load_config, save_config

console = Console()

CALLBACK_PATH = "/callback"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 120


@click.group()
def auth():
    """Authentication commands."""


def _free_loopback_port() -> int:
    """Ask the OS for an available port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """
    Handles exactly one meaningful request: GET /callback?token=...
    Everything else (a stray favicon request, etc.) gets a plain 404 and
    does NOT signal completion — the server keeps waiting for the real
    callback rather than shutting down on the first thing that arrives.
    """

    def do_GET(self) -> None:  # noqa: N802 - stdlib-mandated method name
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        token = params.get("token", [None])[0]
        error = params.get("error", [None])[0]
        self.server.token = token  # type: ignore[attr-defined]
        self.server.error = error  # type: ignore[attr-defined]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if token:
            body = "<html><body><h3>Login complete.</h3><p>You can close this tab and return to your terminal.</p></body></html>"
        else:
            safe_error = html_module.escape(error or "no token received")
            body = f"<html><body><h3>Login failed.</h3><p>{safe_error}</p></body></html>"
        self.wfile.write(body.encode("utf-8"))

        self.server.received.set()  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # silence BaseHTTPRequestHandler's default request logging


@auth.command()
@click.option("--endpoint", default=None, help="API base URL (defaults to http://localhost:8000).")
@click.option(
    "--manual",
    is_flag=True,
    default=False,
    help="Skip the local callback server — for SSH/headless sessions where the browser is on a different machine than this CLI.",
)
@click.option("--timeout", default=DEFAULT_LOGIN_TIMEOUT_SECONDS, show_default=True, help="Seconds to wait for login to complete.")
def login(endpoint: Optional[str], manual: bool, timeout: int) -> None:
    """Log in via GitHub and generate a CLI API key in one step."""
    api_url = endpoint or get_endpoint()

    if manual:
        _login_manual(api_url)
        return

    port = _free_loopback_port()
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.token = None  # type: ignore[attr-defined]
    server.error = None  # type: ignore[attr-defined]
    server.received = threading.Event()  # type: ignore[attr-defined]

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()

    login_url = f"{api_url}/auth/github?state=cli:{port}"
    console.print("Opening your browser to log in via GitHub…")
    if not webbrowser.open(login_url):
        console.print("[yellow]Couldn't open a browser automatically.[/yellow] Open this URL manually:")
        console.print(f"  [cyan]{login_url}[/cyan]")

    completed = server.received.wait(timeout=timeout)  # type: ignore[attr-defined]
    server.shutdown()
    thread.join()
    server.server_close()

    if not completed:
        console.print(
            f"[red]✗ Timed out after {timeout}s waiting for login.[/red] "
            "Run the command again, or use [bold]--manual[/bold] if the browser is on a different machine than this CLI."
        )
        raise SystemExit(1)

    token = server.token  # type: ignore[attr-defined]
    if not token:
        console.print(f"[red]✗ Login failed:[/red] {server.error or 'no token received'}")  # type: ignore[attr-defined]
        raise SystemExit(1)

    _finish_login(api_url, token)


def _login_manual(api_url: str) -> None:
    """
    Fallback for a CLI running on a different machine than the browser
    that completes the login (SSH, headless boxes). Talks to a dedicated
    backend page (state=cli-manual) — see api/app/routers/auth.py — built
    specifically to display the token, unlike the SPA's own /callback
    route.
    """
    login_url = f"{api_url}/auth/github?state=cli-manual"
    console.print("Open this URL in any browser — it does not need to be on this machine:")
    console.print(f"  [cyan]{login_url}[/cyan]")
    token = click.prompt("Paste the token shown after login completes")
    _finish_login(api_url, token)


def _finish_login(api_url: str, token: str) -> None:
    """Shared tail of both login paths: immediately exchanges the
    short-lived bearer token for a permanent API key, so `login` alone is
    enough — no separate `key generate` step needed for the common case."""
    try:
        resp = httpx.post(f"{api_url}/auth/api-key", headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    except httpx.ConnectError:
        console.print(f"[red]✗ Could not reach {api_url}.[/red] Check the endpoint and try again.")
        raise SystemExit(1)

    if resp.status_code == 401:
        console.print("[red]✗ Login token was rejected (expired or invalid).[/red] Run [bold]outpost auth login[/bold] again.")
        raise SystemExit(1)
    resp.raise_for_status()

    result = resp.json()
    save_config({**load_config(), "endpoint": api_url, "token": token, "api_key": result["api_key"]})
    console.print("[green]✓[/green] Logged in — API key saved to [dim]~/.outpost/config.yaml[/dim]")


@auth.group()
def key() -> None:
    """API key management."""


@key.command("generate")
@click.option("--endpoint", default=None, help="API base URL (defaults to http://localhost:8000).")
def generate_key(endpoint: Optional[str]) -> None:
    """
    Re-issue an API key without a full login — useful if you need to
    rotate your key but still have a fresh (<15 min old) login token
    lying around. For the common case, just run `outpost auth login`
    instead; it does this automatically.
    """
    api_url = endpoint or get_endpoint()
    token = get_token()
    if not token:
        console.print("[red]✗ No login token on file.[/red] Run [bold]outpost auth login[/bold].")
        raise SystemExit(1)
    _finish_login(api_url, token)