"""
Authentication Commands

`outpost auth login`        — opens the browser for GitHub OAuth, stores the bearer token
`outpost auth key generate` — exchanges that token for a permanent API key
"""

from typing import Optional

import click
import httpx
import webbrowser
from rich.console import Console

from outpost.config import get_endpoint, get_token, load_config, save_config

console = Console()


@click.group()
def auth():
    """Authentication commands."""


@auth.command()
@click.option("--endpoint", default=None, help="API base URL (defaults to http://localhost:8000)")
def login(endpoint: Optional[str]):
    """
    Open the browser to log in via GitHub, then paste back the token.

    The browser flow lands on the *frontend's* /callback page, since that's
    where the API delivers the JWT (in the URL fragment). Copy the token
    shown there and paste it here. A smoother device-code-style flow that
    skips the copy/paste step can replace this in a later phase.
    """
    api_url = endpoint or get_endpoint()
    console.print(f"Opening browser to [cyan]{api_url}/auth/github[/cyan] …")
    webbrowser.open(f"{api_url}/auth/github")

    token = click.prompt("Paste the token shown after login completes")
    save_config({**load_config(), "endpoint": api_url, "token": token})
    console.print("[green]✓[/green] Logged in. Run [bold]outpost auth key generate[/bold] next.")


@auth.group()
def key():
    """API key management."""


@key.command("generate")
def generate_key():
    """Exchange your login token for a persistent CLI API key."""
    token = get_token()
    if not token:
        console.print("[red]✗ Not logged in.[/red] Run [bold]outpost auth login[/bold] first.")
        raise SystemExit(1)

    api_url = get_endpoint()
    resp = httpx.post(
        f"{api_url}/auth/api-key",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 401:
        console.print("[red]✗ Your login token has expired.[/red] Run [bold]outpost auth login[/bold] again.")
        raise SystemExit(1)
    resp.raise_for_status()

    result = resp.json()
    cfg = load_config()
    cfg["api_key"] = result["api_key"]
    save_config(cfg)
    console.print("[green]✓[/green] API key saved to [dim]~/.outpost/config.yaml[/dim]")
    console.print("[yellow]Note:[/yellow] this key will not be shown again.")