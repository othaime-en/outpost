"""
Authentication & API Key Management

GitHub OAuth flow:
  1. Browser hits GET /auth/github -> redirected to GitHub's authorize page.
  2. GitHub redirects back to GET /auth/github/callback?code=...
  3. We exchange the code for a GitHub access token, fetch the GitHub profile,
     find-or-create the local User row, mint our own JWT, and redirect the
     browser to the frontend with the JWT in the URL *fragment*
     (FRONTEND_URL/callback#token=...).

MULTI-TEAM CHANGE — _create_jwt: the payload now carries ONLY {user_id, exp}.
It used to also embed team_id and role, but get_current_user's JWT decode
path never actually read those two claims (only user_id) — so removing them
changes nothing about how requests are authorized, only what's sitting
inside the token. Worth removing anyway, for two reasons:

  1. Under multi-team, "team_id" is no longer well-defined for a user with
     zero, or more than one, team — embedding a single value would just be
     wrong on its face for those users.
  2. Even where it happened to be accurate, embedding authorization data in
     a 24h-lived token means a role change or team removal wouldn't take
     effect until the token expired. Authorization is resolved fresh from
     the DB on every request instead (see middleware/auth.py, rbac.py) —
     a super_admin demoting someone takes effect on that user's very next
     request, not after a token refresh.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from passlib.hash import bcrypt
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.middleware.auth import JWT_ALGORITHM, get_current_user
from app.models.audit_log import AuditLog
from app.models.team_membership import TeamMembership
from app.models.user import User
from app.schemas.auth import ApiKeyResponse, UserProfile
from app.schemas.user import TeamMembershipOut

router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"
GITHUB_EMAILS_API = "https://api.github.com/user/emails"


def _create_jwt(user: User) -> str:
    payload = {
        "user_id": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def _fetch_primary_email(gh_access_token: str) -> Optional[str]:
    """GitHub omits `email` from /user when it's private — fall back to /user/emails."""
    resp = httpx.get(
        GITHUB_EMAILS_API,
        headers={"Authorization": f"Bearer {gh_access_token}"},
        timeout=10.0,
    )
    if resp.status_code != 200:
        return None
    primary = next((e for e in resp.json() if e.get("primary")), None)
    return primary["email"] if primary else None


def _profile_response(user: User, db: Session) -> UserProfile:
    """
    Builds the /auth/me response. Queries team_memberships joined to Team
    for team_name/team_slug — user.team_memberships (eager-loaded by
    get_current_user) has the membership rows but not each team's name/slug,
    which UserProfile needs for display.
    """
    memberships = (
        db.query(TeamMembership)
        .options(joinedload(TeamMembership.team))
        .filter(TeamMembership.user_id == user.id)
        .all()
    )
    return UserProfile(
        id=str(user.id),
        username=user.username,
        email=user.email,
        platform_role=user.platform_role,
        team_memberships=[
            TeamMembershipOut(
                team_id=str(m.team_id),
                team_name=m.team.name,
                team_slug=m.team.slug,
                role=m.role,
            )
            for m in memberships
        ],
    )


@router.get("/github")
def github_login():
    """Redirect the browser to GitHub's OAuth authorize page."""
    if not settings.github_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured on this server (GITHUB_CLIENT_ID missing).",
        )
    params = (
        f"client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_redirect_uri}"
        f"&scope=user:email"
    )
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/github/callback")
def github_callback(code: str, db: Session = Depends(get_db)):
    """
    Handle the GitHub OAuth redirect: exchange `code`, resolve/create the
    local user, issue our JWT, and hand the browser back to the frontend.
    """
    token_resp = httpx.post(
        GITHUB_TOKEN_URL,
        json={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": settings.github_redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=10.0,
    )
    token_resp.raise_for_status()
    gh_access_token = token_resp.json().get("access_token")
    if not gh_access_token:
        raise HTTPException(status_code=400, detail="GitHub OAuth exchange failed")

    profile_resp = httpx.get(
        GITHUB_USER_API,
        headers={"Authorization": f"Bearer {gh_access_token}"},
        timeout=10.0,
    )
    profile_resp.raise_for_status()
    gh_user = profile_resp.json()

    email = gh_user.get("email") or _fetch_primary_email(gh_access_token)

    user = db.query(User).filter(User.github_id == gh_user["id"]).first()
    if user is None:
        user = User(
            github_id=gh_user["id"],
            username=gh_user["login"],
            email=email,
            platform_role="user",
        )
        db.add(user)
    else:
        # GitHub usernames can change — keep ours in sync on every login.
        user.username = gh_user["login"]
        if email:
            user.email = email
    db.commit()
    db.refresh(user)

    jwt_token = _create_jwt(user)
    return RedirectResponse(f"{settings.frontend_url}/callback#token={jwt_token}")


@router.post("/api-key", response_model=ApiKeyResponse)
def generate_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Issues a new CLI API key for the current user. Only the bcrypt hash is
    ever persisted — the raw key is returned exactly once. Calling this again
    silently invalidates any previously issued key (only one hash is stored).
    """
    raw_key = f"idplite_{secrets.token_urlsafe(32)}"
    current_user.api_key_hash = bcrypt.hash(raw_key)
    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="API_KEY_GENERATED",
            actor_type="user",
            event_metadata={"username": current_user.username},
        )
    )
    db.commit()
    return ApiKeyResponse(api_key=raw_key)


@router.get("/me", response_model=UserProfile)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _profile_response(current_user, db)