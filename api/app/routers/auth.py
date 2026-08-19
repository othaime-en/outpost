"""
Authentication & API Key Management

GitHub OAuth flow:
  1. Browser hits GET /auth/github -> redirected to GitHub's authorize page.
  2. GitHub redirects back to GET /auth/github/callback?code=...
  3. We exchange the code for a GitHub access token, fetch the GitHub profile,
     find-or-create the local User row, mint our own JWT AND a refresh token,
     and redirect the browser to the frontend with the JWT in the URL
     *fragment* (FRONTEND_URL/callback#token=...) while the refresh token
     rides along as an httpOnly cookie on that same redirect response.

REFRESH-TOKEN FLOW (see services/refresh_tokens.py for the full design):
  - POST /auth/refresh reads the httpOnly cookie (never touched by JS —
    the browser attaches it automatically), verifies + rotates it, and
    returns a fresh short-lived JWT. Called by the frontend once on app
    mount (silent re-login after a hard refresh) and automatically,
    transparently, whenever an ordinary request 401s mid-session because
    the access token expired.
  - POST /auth/logout revokes the current refresh token server-side and
    clears the cookie. Idempotent — succeeds even with no/garbage cookie.
  - Neither endpoint requires get_current_user / a valid JWT — by design,
    since the whole point of /auth/refresh is re-establishing a session
    when the access token is ALREADY gone, and /auth/logout must still
    work when it is too.

MULTI-TEAM CHANGE — _create_jwt: the payload now carries ONLY {user_id, exp}.
It used to also embed team_id and role, but get_current_user's JWT decode
path never actually read those two claims (only user_id) — so removing them
changes nothing about how requests are authorized, only what's sitting
inside the token. Worth removing anyway, for two reasons:

  1. Under multi-team, "team_id" is no longer well-defined for a user with
     zero, or more than one, team — embedding a single value would just be
     wrong on its face for those users.
  2. Even where it happened to be accurate, embedding authorization data in
     a token means a role change or team removal wouldn't take effect until
     the token expired. Authorization is resolved fresh from the DB on
     every request instead (see middleware/auth.py, rbac.py) — a
     super_admin demoting someone takes effect on that user's very next
     request, not after a token refresh.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from passlib.hash import bcrypt
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.middleware.auth import JWT_ALGORITHM, get_current_user
from app.models.audit_log import AuditLog
from app.models.team_membership import TeamMembership
from app.models.user import User
from app.schemas.auth import ApiKeyResponse, TokenResponse, UserProfile
from app.schemas.user import TeamMembershipOut
from app.services import refresh_tokens

router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"
GITHUB_EMAILS_API = "https://api.github.com/user/emails"


def _create_jwt(user: User) -> str:
    payload = {
        "user_id": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_ttl_minutes),
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
    local user, issue our JWT + a refresh token, and hand the browser
    back to the frontend. The JWT travels in the redirect URL's fragment
    (read client-side, never sent to any server — see AuthCallback.tsx);
    the refresh token travels as an httpOnly cookie set directly on this
    RedirectResponse, which the browser stores and silently re-attaches
    to future POST /auth/refresh calls without any JS ever touching it.
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
    raw_refresh_token = refresh_tokens.issue(db, user)

    response = RedirectResponse(f"{settings.frontend_url}/callback#token={jwt_token}")
    refresh_tokens.set_cookie(response, raw_refresh_token)
    return response


def _refresh_failure(detail: str) -> "JSONResponse":
    """
    Builds a 401 for a rejected refresh attempt AND clears the refresh
    cookie on that SAME response object.

    Deliberately NOT `response.delete_cookie(...)` on an injected
    `Response` param followed by `raise HTTPException(...)`: FastAPI does
    not carry over cookie/header mutations made to an injected `Response`
    when the handler raises rather than returns normally — verified
    directly against this FastAPI version with a throwaway TestClient
    script rather than assumed from memory, since it's a genuinely easy
    mistake to make silently. Returning a real Response object here
    sidesteps the gotcha entirely: the cookie mutation and the response
    that carries it are the same object, so there's no path where one
    ships without the other.
    """
    response = JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": detail})
    refresh_tokens.clear_cookie(response)
    return response


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(request: Request, db: Session = Depends(get_db)):
    """
    Silently re-establishes a session from the httpOnly refresh cookie —
    no Authorization header involved, and none required. Called by the
    frontend once on every app mount (recovering from a hard refresh) and
    automatically whenever an ordinary API call 401s mid-session because
    the short-lived access token expired (see ui/src/api/client.ts).

    Rotates the refresh token on every successful call — the cookie in
    the response is NOT the same value that came in. See
    services/refresh_tokens.py's module docstring for why, and for what
    happens if an already-rotated-away token is presented again (reuse
    detection: the entire session, everywhere, is revoked defensively).
    """
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        return _refresh_failure("No refresh token")

    result = refresh_tokens.verify_and_rotate(db, raw_token)
    if not result.ok:
        # Whatever the exact reason (garbage, expired, or
        # reused-and-now-revoked session-wide), the cookie the browser is
        # holding is dead either way — clear it so it isn't retried
        # forever on every future silent-refresh attempt.
        return _refresh_failure("Invalid or expired refresh token")

    response = JSONResponse(content=TokenResponse(access_token=_create_jwt(result.user)).model_dump())
    refresh_tokens.set_cookie(response, result.raw_token)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Revokes the current refresh token server-side and clears the cookie.
    Deliberately does NOT require get_current_user — a user must be able
    to log out even if their access token already expired, and this call
    must always succeed idempotently (already logged out elsewhere, no
    cookie present at all, etc. are all fine, not errors).
    """
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        refresh_tokens.revoke(db, raw_token)
    refresh_tokens.clear_cookie(response)


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