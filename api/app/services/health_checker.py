"""
Health Checking Service

Polls the ECS service behind each RUNNING environment and derives a
coarse HEALTHY / DEGRADED / UNKNOWN status from `runningCount` vs
`desiredCount`.
"""

from __future__ import annotations

import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.orm import Session

logger = logging.getLogger("idplite.health_checker")

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNKNOWN = "UNKNOWN"

DEFAULT_POLL_INTERVAL_SECONDS = 300  # 5 minutes, per the implementation plan


def check_ecs_health(ecs_service_arn: str, cluster_arn: str, region: str) -> str:
    """
    Returns HEALTHY, DEGRADED, or UNKNOWN for a single ECS service.

    - UNKNOWN: the service doesn't exist / isn't describable yet (e.g. the
      moment after PROVISIONING completes but before ECS has settled), the
      AWS call itself fails, or desired_count is 0 (intentionally scaled
      down — "unhealthy" would be the wrong read on that).
    - DEGRADED: the service exists but isn't ACTIVE, or running < desired.
    - HEALTHY: ACTIVE and running >= desired.

    Never raises — a health check that can crash the poller for one bad
    environment and take the rest down with it is worse than a single
    UNKNOWN reading.
    """
    try:
        client = boto3.client("ecs", region_name=region)
        resp = client.describe_services(cluster=cluster_arn, services=[ecs_service_arn])
    except (BotoCoreError, ClientError) as exc:
        logger.warning("ECS describe_services failed for %s: %s", ecs_service_arn, exc)
        return UNKNOWN
    except Exception:  # noqa: BLE001 — health checks must never raise
        logger.exception("Unexpected error checking ECS health for %s", ecs_service_arn)
        return UNKNOWN

    services = resp.get("services", [])
    if not services or services[0].get("status") != "ACTIVE":
        return DEGRADED

    svc = services[0]
    running = svc.get("runningCount", 0)
    desired = svc.get("desiredCount", 1)

    if desired == 0:
        return UNKNOWN

    return HEALTHY if running >= desired else DEGRADED


def poll_once(db: Session) -> int:
    """
    One full health-poll pass: every RUNNING environment with recorded
    Terraform outputs gets its `health_status` / `health_checked_at`
    updated. Commits once at the end of the pass.

    Returns the number of environments updated, so callers (the startup
    background task, or a test) can log/assert on progress without needing
    the DB layer to instrument itself.

    Environments missing `ecs_service_arn` / `ecs_cluster_arn` in their
    outputs are skipped rather than marked UNKNOWN — that shape of output
    means Terraform hasn't reported ECS details at all (e.g. an unexpected
    module change), which is a data problem worth investigating separately
    from "AWS says this service isn't healthy."
    """
    # Imported here (not at module load) to avoid a circular import: models
    # import Base from database.py, and this module is imported by main.py
    # before the app — importing at module scope is fine today but keeping
    # it deferred matches the pattern already used for Runbook in
    # routers/environments.py's callback handler.
    from app.models.environment import Environment

    running = (
        db.query(Environment)
        .filter(Environment.status == "RUNNING", Environment.outputs.isnot(None))
        .all()
    )

    updated = 0
    for env in running:
        outputs = env.outputs or {}
        service_arn = outputs.get("ecs_service_arn")
        cluster_arn = outputs.get("ecs_cluster_arn")
        if not service_arn or not cluster_arn:
            continue

        env.health_status = check_ecs_health(service_arn, cluster_arn, env.aws_region)
        env.health_checked_at = _utcnow()
        updated += 1

    if updated:
        db.commit()

    return updated


async def poll_health_forever(interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
    """
    Background task started on API startup (see main.py). Runs until the
    process exits — asyncio.CancelledError on shutdown is expected and
    allowed to propagate so the task actually stops.
    """
    import asyncio

    from app.database import SessionLocal

    while True:
        await asyncio.sleep(interval_seconds)
        db = SessionLocal()
        try:
            updated = poll_once(db)
            logger.info("Health poll complete: %d environment(s) updated", updated)
        except Exception:  # noqa: BLE001 — one bad pass must not kill the poller
            db.rollback()
            logger.exception("Health poll pass failed")
        finally:
            db.close()


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)