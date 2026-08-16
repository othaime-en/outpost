"""
Authentication Middleware

Provides get_current_user as a FastAPI dependency. Supports two auth methods
that both resolve to the same User object, so downstream code never needs to
know which one was used:

  1. JWT Bearer token  — used by the web UI (Authorization: Bearer <jwt>)
  2. X-API-Key header  — used by the CLI (long-lived, bcrypt-hashed at rest)

MULTI-TEAM NOTE: the JWT payload was already decode-side minimal — this
file only ever read `user_id` out of it, never `team_id`/`role`, even
before multi-team support (routers/auth.py's _create_jwt is the one that
wrote those extra, now-removed, claims). Authorization is always resolved
fresh from the DB on every request, never trusted from the token — that
was true before this change and remains true now. The one addition here is
eager-loading `team_memberships` on the way out, so rbac.py's
team_role()/has_team_role() helpers can filter an already-loaded Python
list instead of issuing a second query per request.
"""

from __future__ import annotations

from typing import Optional

import jwt
import passlib.hash as ph
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.models.user import User

# auto_error=False so a missing Bearer token doesn't short-circuit before we
# get a chance to fall through to X-API-Key auth.
security = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolves the current user from either a JWT or an API key.
    JWT is tried first since it covers the more common case (every UI request).
    """
    if credentials is not None:
        user = _user_from_jwt(credentials.credentials, db)
        if user is not None:
            return user

    if x_api_key:
        user = _user_from_api_key(x_api_key, db)
        if user is not None:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_from_jwt(token: str, db: Session) -> Optional[User]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        # Catches every PyJWT failure mode we care about here: bad signature,
        # malformed token, expired exp claim, etc. — all subclass PyJWTError.
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    return (
        db.query(User)
        .options(joinedload(User.team_memberships))
        .filter(User.id == user_id)
        .first()
    )


def _user_from_api_key(raw_key: str, db: Session) -> Optional[User]:
    """
    NOTE: O(n) bcrypt-verify loop over every user with an API key set.
    Acceptable at portfolio-project scale. At real scale, store a
    non-sensitive key prefix (e.g. first 8 chars) alongside the hash to
    narrow the candidate set before running bcrypt, which is deliberately slow.
    """
    candidates = (
        db.query(User)
        .options(joinedload(User.team_memberships))
        .filter(User.api_key_hash.isnot(None))
        .all()
    )
    for user in candidates:
        try:
            if ph.bcrypt.verify(raw_key, user.api_key_hash):
                return user
        except ValueError:
            # Malformed/foreign hash format — skip rather than crash the loop.
            continue
    return None