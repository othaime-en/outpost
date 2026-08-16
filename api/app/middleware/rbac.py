"""
RBAC Enforcement

Two distinct kinds of check live here now, and they should never be
conflated:

  1. Platform-level  — "is this user a super_admin at all." No team
                        involved. See require_platform_role / require_super_admin.
  2. Team-scoped      — "does this user hold a qualifying role on THIS
                        SPECIFIC team." See team_role / has_team_role /
                        require_team_role.

WHAT HAPPENED TO require_member / require_team_admin:

Under the old single-team model, `require_member` gated on
`current_user.role in ("member", "team_admin", "super_admin")` — which is
every possible value that column could hold. It never actually rejected an
authenticated user; it was already functioning as "just require login,"
not a real role check. Team-scoping was enforced separately, per-handler,
via _assert_team_visibility()-style checks. So removing it here is a no-op
behavior-wise — call sites that used it now depend on get_current_user
directly, which is the honest name for what was already happening.

`require_team_admin` genuinely checked something under the single-team
model (current_user.role == "team_admin"), but that check was only ever
correct because a user had exactly one team, so "is team_admin" and "is
team_admin OF THE TEAM THIS ENDPOINT TARGETS" were the same question. Under
multi-team they're not — a user can be team_admin on Team A and a plain
member (or nothing at all) on Team B. Call sites that used
require_team_admin on a path with a `team_id` param now use
require_team_role("team_admin") instead, which checks the role scoped to
that specific team_id, not a global property of the user.

Team-scoped checks route through team_role()/has_team_role() exclusively —
never touch current_user.team_memberships or .platform_role directly
elsewhere in the app. That's what makes "authorized on team X" mean one
thing, checked one way, everywhere.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Path, status

from app.config import settings
from app.middleware.auth import get_current_user
from app.models.user import User


# ---------------------------------------------------------------------------
# Team-scoped authorization: single source of truth
#
# Both functions read off User.team_memberships, which get_current_user
# eager-loads on every request — neither issues a DB query. This only works
# for questions about the CURRENT user's own memberships. Questions about
# OTHER users' memberships on a team (e.g. "is this the last team_admin")
# still need a real query — see routers/teams.py's _is_last_team_admin,
# which deliberately stays local to that router since it's a business rule
# specific to team-membership management, not a generic auth gate.
# ---------------------------------------------------------------------------

def team_role(user: User, team_id) -> Optional[str]:
    """This user's role on this specific team, or None if not a member.
    No DB query — filters the eager-loaded team_memberships list.
    Accepts team_id as UUID or str; comparison is done as str to avoid
    UUID-vs-str mismatches depending on caller."""
    target = str(team_id)
    for m in user.team_memberships:
        if str(m.team_id) == target:
            return m.role
    return None


def has_team_role(user: User, team_id, *roles: str) -> bool:
    """
    True if the user qualifies for one of `roles` on this team.
    super_admin always qualifies, regardless of team membership — this is
    the one place platform_role and team-scoped role meet, and it's
    intentional: a super_admin's platform privilege is a strict superset
    of anything a team membership could grant.

    Called with no `roles` args, this checks for ANY membership at all
    (i.e. "can this user see this team's data").
    """
    if user.platform_role == "super_admin":
        return True
    role = team_role(user, team_id)
    if not roles:
        return role is not None
    return role in roles


# ---------------------------------------------------------------------------
# Platform-level authorization
# ---------------------------------------------------------------------------

def require_platform_role(*roles: str):
    """Factory: returns a dependency requiring current_user.platform_role in `roles`."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.platform_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these platform roles: {', '.join(roles)}",
            )
        return current_user

    return dependency


require_super_admin = require_platform_role("super_admin")


# ---------------------------------------------------------------------------
# Team-scoped authorization dependency — for endpoints where team_id is a
# PATH parameter (e.g. POST /teams/{team_id}/members). For endpoints where
# the relevant team_id can only be learned by fetching a resource first
# (e.g. DELETE /environments/{id}), don't force this dependency to fit —
# use team_role()/has_team_role() as explicit checks in the handler body
# instead. Ownership-plus-role logic (member: own only, team_admin: any on
# their team) reads far more clearly as an explicit if/raise chain than
# hidden inside dependency-injection machinery.
# ---------------------------------------------------------------------------

def require_team_role(*roles: str):
    """Factory: returns a dependency requiring the caller to hold one of
    `roles` on the team_id taken from the path. super_admin always passes."""

    def dependency(
        team_id: str = Path(...),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not has_team_role(current_user, team_id, *roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles on team {team_id}: {', '.join(roles)}",
            )
        return current_user

    return dependency


def require_callback_secret(x_callback_secret: Optional[str] = Header(default=None)) -> None:
    """
    Guards internal endpoints (/callback, /environments/expired) called by
    GitHub Actions rather than a logged-in user. Not user auth — a shared
    secret header, matching the architecture doc's "callback security" note.
    """
    if not settings.callback_secret or x_callback_secret != settings.callback_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing callback secret",
        )