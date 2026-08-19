"""
Refresh Token Service

Issuance, verification/rotation, and revocation for the httpOnly-cookie
refresh flow, plus the cookie-attribute helpers shared by every endpoint
that sets or clears it. See routers/auth.py's module docstring for how
this fits into the overall login/refresh/logout flow, and PROJECT NOTE
below for why this exists at all.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Response
from sqlalchemy.orm import Session

from app.config import settings
from app.models.refresh_token import RefreshToken
from app.models.user import User

RAW_TOKEN_BYTES = 48  # 384 bits of entropy — see module docstring


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue(db: Session, user: User) -> str:
    """
    Creates and persists a new refresh token for `user`. Returns the RAW
    token — the only point in its entire lifecycle where the raw value
    exists outside this function's local scope; only its hash is ever
    stored, and the caller's only job is to hand this value to
    set_cookie() and then let it go out of scope.
    """
    raw_token = secrets.token_urlsafe(RAW_TOKEN_BYTES)
    now = datetime.now(timezone.utc)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash(raw_token),
            created_at=now,
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    db.commit()
    return raw_token


class RefreshResult:
    """
    Outcome of verify_and_rotate(). Callers check `.ok` rather than
    catching an exception, because "the presented cookie was garbage,
    expired, or already used" is an expected, routine outcome (e.g. every
    first-ever visit with no cookie at all) — not an application error
    worth a stack trace.
    """

    __slots__ = ("user", "raw_token", "reused")

    def __init__(self, user: Optional[User] = None, raw_token: Optional[str] = None, reused: bool = False):
        self.user = user
        self.raw_token = raw_token
        self.reused = reused

    @property
    def ok(self) -> bool:
        return self.user is not None and self.raw_token is not None


def verify_and_rotate(db: Session, raw_token: str) -> RefreshResult:
    """
    The core of the flow: given the raw token from the incoming cookie,
    either (a) confirm it's valid and currently active, revoke it, and
    issue+return a replacement — the normal case, running on essentially
    every silent refresh — or (b) reject it, for one of several reasons
    distinguished only for logging/docstring clarity; callers besides
    routers/auth.py don't need to branch on which.
    """
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash(raw_token)).first()
    if row is None:
        return RefreshResult()  # unknown token — garbage cookie, or already purged

    now = datetime.now(timezone.utc)

    if row.revoked_at is not None:
        # Reuse of an already-rotated-away (or already-logged-out) token.
        # See module docstring — contain the possible compromise rather
        # than just rejecting this one request.
        revoke_all_for_user(db, row.user_id)
        return RefreshResult(reused=True)

    if row.expires_at < now:
        row.revoked_at = now
        db.commit()
        return RefreshResult()

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        # No user-deletion feature exists today, so this shouldn't be
        # reachable — but a dangling token must never authenticate
        # anything on the strength of "well, it used to point at someone."
        row.revoked_at = now
        db.commit()
        return RefreshResult()

    new_raw_token = secrets.token_urlsafe(RAW_TOKEN_BYTES)
    new_row = RefreshToken(
        user_id=user.id,
        token_hash=_hash(new_raw_token),
        created_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(new_row)
    db.flush()  # populate new_row.id so row.replaced_by_id can point at it

    row.revoked_at = now
    row.replaced_by_id = new_row.id
    db.commit()

    return RefreshResult(user=user, raw_token=new_raw_token)


def revoke(db: Session, raw_token: str) -> None:
    """
    Used by logout. Silently no-ops for an unknown or already-revoked
    token — logout must always succeed from the caller's point of view,
    including "I already logged out in another tab" and "this cookie was
    stale/garbage to begin with."
    """
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash(raw_token)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()


def revoke_all_for_user(db: Session, user_id: UUID) -> None:
    """Defensive containment for reuse detection. A bulk UPDATE, not a
    loop over ORM objects — there's no per-row logic needed and this
    keeps it to one statement regardless of how many tokens the user has
    active."""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()


# --- Cookie helpers ----------------------------------------------------
# Centralized here rather than duplicated across the three router
# functions that need them (login, refresh, logout) — a mismatch between
# the attributes used to SET a cookie vs. the ones used to CLEAR it is a
# classic way to end up with a cookie that silently never actually clears
# in some browsers.


def set_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain or None,
        # Scoped to /auth only — the browser will never attach this
        # cookie to /environments, /teams, etc. It has exactly one job:
        # ride along on POST /auth/refresh and POST /auth/logout.
        path="/auth",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain or None,
        path="/auth",
    )