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
"""

from __future__ import annotations

import html
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

# --- CLI login handoff -----------------------------------------------------
#
# `state` is opaque to GitHub — it round-trips whatever we send unchanged
# from GET /auth/github to GET /auth/github/callback — so it's the only
# channel available to tell the callback "this login came from the CLI,
# not the browser SPA" across the external hop through GitHub.
#
# Two CLI-originated values are recognized, everything else (including no
# state at all) falls through to the original SPA fragment-redirect
# unchanged — this is purely additive, the web UI's login path is
# untouched:
#
#   cli:<port>   — the default `outpost auth login` flow. The CLI starts a
#                  short-lived HTTP server on 127.0.0.1:<port> before
#                  opening the browser, and expects the token delivered
#                  there directly (RFC 8252's "loopback interface
#                  redirection" pattern — the same one used by `gh auth
#                  login`, `gcloud auth login`, VS Code, etc). Restricting
#                  the redirect host to a hardcoded 127.0.0.1 (only the
#                  port is attacker-influenceable) is what makes this safe
#                  without needing to sign or otherwise validate `state`:
#                  the worst a forged port does is hand a token to some
#                  other *local* process on the same machine the browser
#                  is running on, which is already a fully-compromised-
#                  device scenario outside this flow's threat model.
#
#   cli-manual   — for `outpost auth login --manual`, i.e. a CLI running
#                  on a different machine than the browser (SSH sessions,
#                  headless boxes) where a loopback redirect can't reach
#                  it. Renders a small standalone page with the token
#                  visible and copyable. This does NOT reuse the SPA's
#                  /callback route: AuthCallback.tsx reads the token from
#                  the fragment, calls history.replaceState to scrub it,
#                  and redirects into the dashboard within the same
#                  render pass specifically so it never lingers in browser
#                  history — there is no way to also have it sit still
#                  long enough to read, by design. A separate,
#                  purpose-built page is the fix, not a flag bolted onto
#                  that one.
CLI_LOOPBACK_STATE = re.compile(r"^cli:(\d{4,5})$")
CLI_MANUAL_STATE = "cli-manual"
_MIN_LOOPBACK_PORT = 1024
_MAX_LOOPBACK_PORT = 65535


def _cli_manual_token_page(token: str) -> str:
    """Self-contained HTML for the `cli-manual` login path — no dependency
    on the frontend build, so this keeps working even if the SPA is down
    or not deployed at all."""
    safe_token = html.escape(token)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Outpost CLI login</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 640px; margin: 64px auto; padding: 0 20px; color: #1a1a1a; }}
  code {{ display: block; background: #f4f4f5; border: 1px solid #ddd; border-radius: 6px; padding: 14px 16px;
          font-size: 13px; word-break: break-all; margin: 16px 0; }}
  button {{ background: #111; color: #fff; border: none; border-radius: 6px; padding: 8px 16px; cursor: pointer; font-size: 13px; }}
  button:hover {{ background: #333; }}
  .hint {{ color: #666; font-size: 13px; }}
</style>
</head>
<body>
  <h2>Login successful</h2>
  <p>Copy this token and paste it into your terminal:</p>
  <code id="token">{safe_token}</code>
  <button onclick="navigator.clipboard.writeText(document.getElementById('token').textContent)">Copy to clipboard</button>
  <p class="hint">This token expires in a few minutes — paste it back into <code style="display:inline;padding:2px 6px">outpost auth login --manual</code> right away.</p>
</body>
</html>"""


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
def github_login(state: Optional[str] = None):
    """
    Redirect the browser to GitHub's OAuth authorize page.

    `state` is passed straight through to GitHub, which hands it back
    unchanged on `/github/callback` — see that constants block above for
    the two CLI-specific values this can carry. Anything else (or
    nothing) is also passed through harmlessly; the callback only acts on
    the two values it recognizes.
    """
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
    if state:
        params += f"&state={quote(state)}"
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/github/callback")
def github_callback(code: str, state: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Handle the GitHub OAuth redirect: exchange `code`, resolve/create the
    local user, issue our JWT + a refresh token, and hand the browser
    back to the frontend. The JWT travels in the redirect URL's fragment
    (read client-side, never sent to any server — see AuthCallback.tsx);
    the refresh token travels as an httpOnly cookie set directly on this
    RedirectResponse, which the browser stores and silently re-attaches
    to future POST /auth/refresh calls without any JS ever touching it.

    CLI LOGIN HANDOFF: if `state` matches `cli:<port>` or `cli-manual`
    (see the constants block above), the browser is redirected somewhere
    other than the frontend instead — a local loopback server, or a
    standalone token-display page, respectively. This is what makes
    `outpost auth login` work at all: the SPA's own /callback route
    deliberately never displays the token (it's consumed and scrubbed
    from the URL within one render, by design, for the browser session's
    own security), so a CLI login can't ride on that route.
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

    loopback_match = CLI_LOOPBACK_STATE.match(state) if state else None
    if loopback_match:
        port = int(loopback_match.group(1))
        if _MIN_LOOPBACK_PORT <= port <= _MAX_LOOPBACK_PORT:
            response = RedirectResponse(f"http://127.0.0.1:{port}/callback?token={jwt_token}")
            refresh_tokens.set_cookie(response, raw_refresh_token)
            return response
        # Out-of-range port on an otherwise-well-formed `cli:` state: fall
        # through to the normal SPA redirect below rather than erroring —
        # worst case is the browser lands on the dashboard instead of the
        # CLI, not a broken login.

    if state == CLI_MANUAL_STATE:
        response = HTMLResponse(_cli_manual_token_page(jwt_token))
        refresh_tokens.set_cookie(response, raw_refresh_token)
        return response

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
    raw_key = f"outpost_{secrets.token_urlsafe(32)}"
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