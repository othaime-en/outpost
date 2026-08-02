"""
Terraform Trigger Service

Dispatches the GitHub Actions workflows built in Phase 3 (provision.yml /
destroy.yml) via GitHub's workflow_dispatch REST endpoint. This is the only
module in the API that knows how to talk to GitHub Actions — routers call
`trigger_provision` / `trigger_destroy` and know nothing about the HTTP
details underneath.

Terraform itself never runs inside the API process. The API's job ends the
moment the workflow_dispatch request succeeds; GitHub Actions takes it from
there and reports back via POST /environments/{id}/callback.
"""

from __future__ import annotations

import httpx

from app.config import settings

_DISPATCH_TIMEOUT_SECONDS = 10.0


def trigger_provision(
    env_id: str,
    env_name: str,
    team: str,
    env_type: str,
    ttl_hours: int,
    region: str,
) -> None:
    """Dispatch provision.yml for a newly created (PENDING) environment."""
    _dispatch(
        "provision.yml",
        {
            "env_id": env_id,
            "env_name": env_name,
            "team": team,
            "env_type": env_type,
            "ttl_hours": str(ttl_hours),
            "region": region,
        },
    )


def trigger_destroy(env_id: str, region: str = "us-east-1", actor: str = "system") -> None:
    """Dispatch destroy.yml for an environment moving into DESTROYING."""
    _dispatch("destroy.yml", {"env_id": env_id, "region": region, "actor": actor})


def _dispatch(workflow_file: str, inputs: dict) -> None:
    """
    POST to GitHub's workflow_dispatch endpoint.

    Silently no-ops when GITHUB_TOKEN / GITHUB_REPO aren't configured —
    local dev and the test suite both run without them, and callers (the
    environments router) already commit the DB state change before calling
    this, so a missing GitHub config degrades to "the row exists but nothing
    dispatches" rather than a 500. Tests patch these functions directly
    rather than relying on this fallback.
    """
    if not settings.github_token or not settings.github_repo:
        return

    resp = httpx.post(
        f"https://api.github.com/repos/{settings.github_repo}/actions/workflows/{workflow_file}/dispatches",
        json={"ref": "main", "inputs": inputs},
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=_DISPATCH_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()