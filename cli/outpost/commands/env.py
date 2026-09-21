"""
Environment Commands

Thin CLI surface over app/routers/environments.py. Every command here maps
1:1 to a real endpoint — no client-side logic beyond team-slug resolution
(see `_resolve_team_id`) and output formatting.

`--team` accepts a slug, display name, or raw UUID (see
`_resolve_team_id`) — the API itself requires a `team_id`, but forcing CLI
users to go find a UUID first would be hostile. Resolution is done via
`GET /teams/`, which already only ever returns the caller's own
memberships (or every team, for a super_admin) — so it doubles as the
same membership check the API would apply on the real create call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import click
from rich.markdown import Markdown

from outpost.client import ApiError, OutpostClient, handle_api_errors
from outpost.render import console, environment_detail, environments_table

VALID_ENV_TYPES = ("dev", "staging")
VALID_HEALTH_STATUSES = ("HEALTHY", "DEGRADED", "UNKNOWN")
# Kept in sync with app/routers/environments.py's VALID_ENV_STATUSES.
VALID_ENV_STATUSES = (
    "PENDING",
    "PROVISIONING",
    "RUNNING",
    "EXPIRING",
    "PAUSING",
    "PAUSED",
    "RESUMING",
    "DESTROYING",
    "DESTROYED",
    "FAILED",
)


@click.group()
def env():
    """Environment lifecycle commands."""


def _resolve_team_id(client: OutpostClient, team: str) -> str:
    """
    Accept a team's slug, display name, or raw ID and return its ID.
    Raises SystemExit(1) with a helpful message (including the caller's
    actual team list) if nothing — or more than one thing — matches.
    """
    teams = client.get("/teams/") or []

    for t in teams:
        if t["id"] == team:
            return t["id"]

    matches = [t for t in teams if team.lower() in (t["slug"].lower(), t["name"].lower())]
    if len(matches) == 1:
        return matches[0]["id"]

    if not matches:
        console.print(f"[red]✗ No team matching '{team}' found among your memberships.[/red]")
    else:
        console.print(f"[red]✗ '{team}' matches more than one team — use the exact slug.[/red]")

    if teams:
        console.print("Your teams:")
        for t in teams:
            console.print(f"  [bold]{t['slug']}[/bold]  ({t['name']})")
    else:
        console.print("You don't belong to any team yet — create one in the web UI first.")
    raise SystemExit(1)


@env.command()
@click.option("--name", required=True, help="Environment name — lowercase alphanumeric and hyphens only.")
@click.option("--team", required=True, help="Team slug, name, or ID this environment belongs to.")
@click.option("--type", "env_type", required=True, type=click.Choice(VALID_ENV_TYPES), help="Environment type.")
@click.option("--ttl", "ttl_hours", default=24, show_default=True, type=click.IntRange(1, 168), help="Hours until auto-destroy.")
@click.option("--region", default="us-east-1", show_default=True, help="AWS region to provision into.")
@handle_api_errors
def create(name: str, team: str, env_type: str, ttl_hours: int, region: str) -> None:
    """Request a new environment. Returns immediately (202) — Terraform runs async."""
    client = OutpostClient()
    team_id = _resolve_team_id(client, team)

    try:
        result = client.post(
            "/environments/",
            json={
                "name": name,
                "team_id": team_id,
                "env_type": env_type,
                "ttl_hours": ttl_hours,
                "aws_region": region,
            },
        )
    except ApiError as exc:
        # 422 from CreateEnvironmentRequest's field_validators (bad name
        # pattern, etc.) — surface the validator's own message directly.
        console.print(f"[red]✗ {exc.detail}[/red]")
        raise SystemExit(1) from exc

    console.print(f"[green]✓[/green] Environment requested — status: [bold]{result['status']}[/bold]")
    console.print(f"  ID: [bold]{result['env_id']}[/bold]")
    console.print(f"  Track it: [bold]outpost env status {result['env_id']}[/bold]")


@env.command("list")
@click.option("--status", "statuses", multiple=True, type=click.Choice(VALID_ENV_STATUSES), help="Filter by status. Repeatable.")
@click.option("--team", default=None, help="Filter to one team (slug, name, or ID).")
@click.option("--type", "env_type", default=None, type=click.Choice(VALID_ENV_TYPES))
@click.option("--health", "health_status", default=None, type=click.Choice(VALID_HEALTH_STATUSES))
@click.option("--expiring-within", "expiring_within_hours", type=int, default=None, help="Only RUNNING environments expiring within N hours.")
@click.option("--include-destroyed", is_flag=True, default=False, help="Include DESTROYED environments.")
@click.option("--mine", "created_by_me", is_flag=True, default=False, help="Only environments you created.")
@click.option("--sort-by", type=click.Choice(["created_at", "expires_at", "cost_estimate_usd"]), default="created_at", show_default=True)
@click.option("--sort-dir", type=click.Choice(["asc", "desc"]), default="desc", show_default=True)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output raw JSON instead of a table.")
@handle_api_errors
def list_envs(
    statuses: tuple[str, ...],
    team: Optional[str],
    env_type: Optional[str],
    health_status: Optional[str],
    expiring_within_hours: Optional[int],
    include_destroyed: bool,
    created_by_me: bool,
    sort_by: str,
    sort_dir: str,
    as_json: bool,
) -> None:
    """List environments visible to you, across all of your team memberships by default."""
    client = OutpostClient()
    params: dict[str, Any] = {"sort_by": sort_by, "sort_dir": sort_dir}

    if statuses:
        params["status"] = list(statuses)
    if team:
        params["team_id"] = _resolve_team_id(client, team)
    if env_type:
        params["env_type"] = env_type
    if health_status:
        params["health_status"] = health_status
    if expiring_within_hours is not None:
        params["expiring_within_hours"] = expiring_within_hours
    if include_destroyed:
        params["include_destroyed"] = "true"
    if created_by_me:
        params["created_by_me"] = "true"

    envs = client.get("/environments/", params=params) or []

    if as_json:
        console.print_json(data=envs)
        return
    if not envs:
        console.print("[dim]No environments found.[/dim]")
        return
    console.print(environments_table(envs))


@env.command()
@click.argument("env_id")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output raw JSON instead of a detail view.")
@handle_api_errors
def status(env_id: str, as_json: bool) -> None:
    """Show full detail for one environment."""
    client = OutpostClient()
    result = client.get(f"/environments/{env_id}")
    if as_json:
        console.print_json(data=result)
        return
    console.print(environment_detail(result))


@env.command()
@click.argument("env_id")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip the confirmation prompt.")
@handle_api_errors
def destroy(env_id: str, yes: bool) -> None:
    """
    Destroy an environment (or cancel it immediately, if still PENDING —
    see routers/environments.py's docstring, "CANCELLING A PENDING
    ENVIRONMENT," for why that's a different path under the hood).
    """
    if not yes:
        click.confirm(
            f"Destroy environment {env_id}? This tears down real AWS infrastructure.",
            abort=True,
        )
    client = OutpostClient()
    result = client.delete(f"/environments/{env_id}")
    console.print(f"[green]✓[/green] Environment [bold]{env_id}[/bold] — status: [bold]{result['status']}[/bold]")


@env.command()
@click.argument("env_id")
@handle_api_errors
def pause(env_id: str) -> None:
    """Pause a RUNNING or EXPIRING environment (ECS scaled to 0, RDS stopped — reversible)."""
    client = OutpostClient()
    result = client.post(f"/environments/{env_id}/pause")
    console.print(f"[green]✓[/green] Environment [bold]{env_id}[/bold] — status: [bold]{result['status']}[/bold]")


@env.command()
@click.argument("env_id")
@handle_api_errors
def resume(env_id: str) -> None:
    """Resume a PAUSED environment. Grants a fresh TTL window on success."""
    client = OutpostClient()
    result = client.post(f"/environments/{env_id}/resume")
    console.print(f"[green]✓[/green] Environment [bold]{env_id}[/bold] — status: [bold]{result['status']}[/bold]")


@env.command()
@click.argument("env_id")
@click.option("--hours", "extend_hours", required=True, type=click.IntRange(1, 168), help="Hours to add to the current TTL.")
@handle_api_errors
def extend(env_id: str, extend_hours: int) -> None:
    """
    Extend an environment's TTL. From EXPIRING, this also cancels the
    grace period outright and returns it to RUNNING.
    """
    client = OutpostClient()
    result = client.patch(f"/environments/{env_id}/ttl", json={"extend_hours": extend_hours})
    console.print(f"[green]✓[/green] New expiry: [bold]{result['expires_at']}[/bold]")


@env.command()
@click.argument("env_id")
@click.option("--output", "-o", "output_path", type=click.Path(dir_okay=False, writable=True), default=None, help="Save to a file instead of printing.")
@handle_api_errors
def runbook(env_id: str, output_path: Optional[str]) -> None:
    """Show (or save) the auto-generated runbook for an environment."""
    client = OutpostClient()
    result = client.get(f"/environments/{env_id}/runbook")

    if output_path:
        Path(output_path).write_text(result["content_md"])
        console.print(f"[green]✓[/green] Runbook saved to [bold]{output_path}[/bold]")
    else:
        console.print(Markdown(result["content_md"]))