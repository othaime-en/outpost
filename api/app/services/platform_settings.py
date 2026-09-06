"""
Platform Settings — Read Helper

Thin wrapper over the platform_settings key/value table (see
models/platform_settings.py). Kept as a service function rather than
inlined into routers/environments.py because two independent routers need
the same "is TTL enforcement on?" answer — routers/settings.py (to report
current state) and routers/environments.py's process_ttl() (to decide
whether to run its sweeps at all) — and duplicating the fallback-default
logic in both places would be exactly the kind of thing that quietly
drifts out of sync.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.platform_settings import PlatformSettings

TTL_ENFORCEMENT_KEY = "ttl_enforcement_enabled"


def get_setting(db: Session, key: str) -> Optional[PlatformSettings]:
    return db.query(PlatformSettings).filter(PlatformSettings.key == key).first()


def is_ttl_enforcement_enabled(db: Session) -> bool:
    """
    Defaults to True (enforcement ON) if the row is somehow missing — the
    migration seeds it, so this should only matter against a hand-edited
    or partially-migrated DB. Failing this check closed (defaulting to
    disabled) would silently and permanently turn off cost-governance TTL
    enforcement with no operator visibility at all, which is a worse
    failure mode than just continuing to enforce.
    """
    row = get_setting(db, TTL_ENFORCEMENT_KEY)
    if row is None or row.value is None:
        return True
    return bool(row.value)