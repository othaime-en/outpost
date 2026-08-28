"""
Terraform Trigger Service

Dispatches the GitHub Actions workflows built in Phase 3 (provision.yml /
destroy.yml) via GitHub's workflow_dispatch REST endpoint. This is the only
module in the API that knows how to talk to GitHub Actions — routers call
`trigger_provision` / `trigger_destroy` / `trigger_pause` / `trigger_resume`
and know nothing about the HTTP details underneath.

Terraform itself never runs inside the API process. The API's job ends the
moment the workflow_dispatch request succeeds; GitHub Actions takes it from
there and reports back via POST /environments/{id}/callback.

trigger_pause() / trigger_resume() dispatch pause.yml / resume.yml, added
alongside the grace-period/pause safety net — see routers/environments.py's
module docstring, "GRACE PERIOD & PAUSE SAFETY NET". Those two workflow
files don't exist in .github/workflows/ yet as of this change (they're the
next batch, alongside the ttl-cron.yml rewrite and the Terraform module
changes for ECS scale-to-zero / RDS stop-start). Shipping these dispatch
functions ahead of that is safe: `_dispatch()` already no-ops whenever
GITHUB_TOKEN/GITHUB_REPO aren't configured, which is the case for this repo
today (AWS bootstrap not yet done — see the implementation plan), and even
once they are configured, GitHub simply 404s a dispatch to a workflow file
that doesn't exist yet rather than doing anything destructive.
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


def trigger_pause(env_id: str, region: str = "us-east-1", actor: str = "system") -> None:
    """
    Dispatch pause.yml for an environment moving into PAUSING — scales the
    ECS service to 0 and stops the RDS instance, reversibly, instead of
    tearing anything down. See this module's docstring for the workflow
    file's current status.
    """
    _dispatch("pause.yml", {"env_id": env_id, "region": region, "actor": actor})


def trigger_resume(env_id: str, region: str = "us-east-1", actor: str = "system") -> None:
    """
    Dispatch resume.yml for an environment moving into RESUMING — scales
    the ECS service back up and starts the RDS instance. Same
    not-yet-created-workflow caveat as trigger_pause() above.
    """
    _dispatch("resume.yml", {"env_id": env_id, "region": region, "actor": actor})


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