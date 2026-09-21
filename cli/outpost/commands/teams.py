"""
Team Commands

Deliberately minimal and read-only. Full team management (create,
add/remove members, promote/demote) lives in the web UI and isn't
duplicated here. This exists
because `outpost env create --team <slug>` needs something for a user to
check their own slugs against, and "list your teams" is one obvious,
low-risk command to expose while that need exists.
"""

from __future__ import annotations

import click
from rich.table import Table

from outpost.client import OutpostClient, handle_api_errors
from outpost.render import console


@click.group()
def teams():
    """Team commands."""


@teams.command("list")
@handle_api_errors
def list_teams() -> None:
    """List teams you belong to (every team, if you're a super_admin)."""
    client = OutpostClient()
    result = client.get("/teams/") or []

    if not result:
        console.print("[dim]No teams found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("NAME")
    table.add_column("SLUG")
    table.add_column("ID")
    for t in result:
        table.add_row(t["name"], t["slug"], t["id"])
    console.print(table)