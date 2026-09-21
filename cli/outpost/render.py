"""
Shared Terminal Rendering

Table/coloring helpers used by both `env` and `audit` commands, so the two
don't duplicate the same status-coloring and short-ID logic.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()

# Mirrors app/routers/environments.py's VALID_ENV_STATUSES — see that
# module's docstring ("GRACE PERIOD & PAUSE SAFETY NET") for what each of
# the non-obvious ones (EXPIRING/PAUSING/PAUSED/RESUMING) means.
_STATUS_STYLES = {
    "PENDING": "yellow",
    "PROVISIONING": "yellow",
    "RUNNING": "green",
    "EXPIRING": "yellow",
    "PAUSING": "yellow",
    "PAUSED": "cyan",
    "RESUMING": "yellow",
    "DESTROYING": "yellow",
    "DESTROYED": "dim",
    "FAILED": "red bold",
}

_HEALTH_STYLES = {"HEALTHY": "green", "DEGRADED": "yellow", "UNKNOWN": "dim"}


def styled_status(value: str) -> str:
    style = _STATUS_STYLES.get(value, "white")
    return f"[{style}]{value}[/{style}]"


def styled_health(value: str) -> str:
    style = _HEALTH_STYLES.get(value, "dim")
    return f"[{style}]{value}[/{style}]"


def short_id(value: str) -> str:
    """First segment of a UUID — enough to disambiguate in a table, full
    ID always available via `outpost env status <id>`."""
    return value.split("-")[0]


def _cost(value: Any) -> str:
    return f"${value:.2f}" if value is not None else "—"


def environments_table(envs: list[dict[str, Any]]) -> Table:
    table = Table(show_header=True, header_style="bold")
    table.add_column("NAME")
    table.add_column("ID")
    table.add_column("TEAM")
    table.add_column("TYPE")
    table.add_column("STATUS")
    table.add_column("HEALTH")
    table.add_column("EXPIRES_AT")
    table.add_column("COST/MO", justify="right")
    for e in envs:
        table.add_row(
            e["name"],
            short_id(e["id"]),
            e["team_slug"],
            e["env_type"],
            styled_status(e["status"]),
            styled_health(e["health_status"]),
            e["expires_at"],
            _cost(e.get("cost_estimate_usd")),
        )
    return table


def environment_detail(env: dict[str, Any]) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()

    rows = [
        ("ID", env["id"]),
        ("Name", env["name"]),
        ("Team", env["team_slug"]),
        ("Type", env["env_type"]),
        ("Status", styled_status(env["status"])),
        ("Health", styled_health(env["health_status"])),
        ("Created by", env["created_by_username"]),
        ("Created at", env["created_at"]),
        ("Expires at", env["expires_at"]),
        ("TTL (hours)", str(env["ttl_hours"])),
        ("Region", env["aws_region"]),
        ("Cost estimate/mo", _cost(env.get("cost_estimate_usd"))),
    ]
    # Grace-period/pause fields only ever populated in the relevant states
    # — see render._STATUS_STYLES' comment for what these correspond to.
    if env.get("expiring_since"):
        rows.append(("Expiring since", env["expiring_since"]))
    if env.get("paused_at"):
        rows.append(("Paused at", env["paused_at"]))
    if env.get("pause_expires_at"):
        rows.append(("Pause expires at", env["pause_expires_at"]))
    if env.get("destroyed_at"):
        rows.append(("Destroyed at", env["destroyed_at"]))

    for label, value in rows:
        table.add_row(label, value)

    if env.get("outputs"):
        table.add_row("", "")
        table.add_row("Outputs", "")
        for k, v in env["outputs"].items():
            table.add_row(f"  {k}", str(v))

    return table


def audit_table(items: list[dict[str, Any]]) -> Table:
    table = Table(show_header=True, header_style="bold")
    table.add_column("TIME")
    table.add_column("ACTION")
    table.add_column("ACTOR_TYPE")
    table.add_column("ENV")
    for row in items:
        table.add_row(
            row["created_at"],
            row["action"],
            row["actor_type"],
            short_id(row["environment_id"]) if row.get("environment_id") else "—",
        )
    return table