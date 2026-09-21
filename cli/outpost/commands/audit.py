"""
Audit Log Commands

Thin CLI surface over app/routers/audit.py — read-only, paginated,
team-scoped the same way the API scopes it (a non-super_admin sees rows
for any team they belong to, plus anything they personally did).
"""

from __future__ import annotations

from typing import Optional

import click

from outpost.client import OutpostClient, handle_api_errors
from outpost.render import audit_table, console


@click.group()
def audit():
    """Audit log commands."""


@audit.command("list")
@click.option("--env", "environment_id", default=None, help="Filter to one environment ID.")
@click.option("--action", default=None, help="Filter by exact action name, e.g. ENV_CREATED.")
@click.option("--actor-type", default=None, type=click.Choice(["user", "system", "cron"]))
@click.option("--page", default=1, type=click.IntRange(min=1), show_default=True)
@click.option("--page-size", default=50, type=click.IntRange(1, 200), show_default=True)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output raw JSON instead of a table.")
@handle_api_errors
def list_audit(
    environment_id: Optional[str],
    action: Optional[str],
    actor_type: Optional[str],
    page: int,
    page_size: int,
    as_json: bool,
) -> None:
    """List audit log entries visible to you."""
    client = OutpostClient()
    params: dict[str, object] = {"page": page, "page_size": page_size}
    if environment_id:
        params["environment_id"] = environment_id
    if action:
        params["action"] = action
    if actor_type:
        params["actor_type"] = actor_type

    result = client.get("/audit/", params=params)

    if as_json:
        console.print_json(data=result)
        return

    items = result["items"]
    if not items:
        console.print("[dim]No audit log entries found.[/dim]")
        return

    console.print(audit_table(items))
    console.print(f"[dim]Page {result['page']} — {len(items)} of {result['total']} total[/dim]")