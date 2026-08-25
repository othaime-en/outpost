"""
Notification Service (stub)

Fires at three points in the grace-period/pause lifecycle — see
routers/environments.py's module docstring, "GRACE PERIOD & PAUSE SAFETY
NET": entering EXPIRING, entering PAUSED, and ~48h before a paused
environment's final, unrecoverable destroy.

This is deliberately just an interface plus a logging-only implementation
right now. No Slack webhook or SMTP config exists in this project yet, and
standing one up (secrets, delivery failures/retries, rate limiting) is its
own separate piece of work that hasn't been scoped. Swapping in a real
channel later means adding one new NotificationService subclass and
changing what get_notification_service() returns — nothing that calls
notify() needs to change.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("outpost.notifications")


class NotificationEvent(str, Enum):
    ENV_EXPIRING = "ENV_EXPIRING"                        # grace period started
    ENV_PAUSED = "ENV_PAUSED"                             # auto- or manually paused
    ENV_PAUSE_EXPIRING_SOON = "ENV_PAUSE_EXPIRING_SOON"   # final destroy is ~48h out


@dataclass
class NotificationContext:
    env_id: str
    env_name: str
    team_slug: str
    created_by_username: str
    detail: str  # human-readable, event-specific — e.g. "auto-pauses in 24h unless extended"


class NotificationService(ABC):
    @abstractmethod
    def notify(self, event: NotificationEvent, ctx: NotificationContext) -> None:
        ...


class LoggingNotificationService(NotificationService):
    """
    Default implementation. Writes a structured log line instead of
    delivering anything — enough to prove the trigger points fire at the
    right moments (and to eyeball in local dev / test output) without
    committing to a delivery channel this project doesn't have configured.
    """

    def notify(self, event: NotificationEvent, ctx: NotificationContext) -> None:
        logger.info(
            "[notify] %s — env=%s (%s) team=%s owner=%s — %s",
            event.value,
            ctx.env_name,
            ctx.env_id,
            ctx.team_slug,
            ctx.created_by_username,
            ctx.detail,
        )


def get_notification_service() -> NotificationService:
    """Single seam for swapping in a real implementation later (Slack
    webhook, SMTP, etc.) — see this module's docstring."""
    return LoggingNotificationService()