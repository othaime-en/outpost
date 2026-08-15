"""
Pytest Configuration & Shared Fixtures
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt

os.environ.setdefault("DATABASE_URL", "postgresql://idplite:idplite@localhost:5432/idplite_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("CALLBACK_SECRET", "test-callback-secret")
# GitHub OAuth isn't exercised end-to-end in tests (that would need a live
# GitHub App), but GET /auth/github still needs a non-empty client_id to
# build its redirect — otherwise it correctly returns 503 "not configured"
# rather than a broken redirect URL. Setting fake values here lets tests
# verify the real redirect path instead of just tolerating that 503 branch.
os.environ.setdefault("GITHUB_CLIENT_ID", "test-github-client-id")
os.environ.setdefault("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")

from app.main import app                        # noqa: E402
from app.config import settings                  # noqa: E402
from app.database import SessionLocal            # noqa: E402
from app.middleware.auth import JWT_ALGORITHM    # noqa: E402
from app.models.audit_log import AuditLog        # noqa: E402
from app.models.environment import Environment   # noqa: E402
from app.models.runbook import Runbook           # noqa: E402
from app.models.team import Team                 # noqa: E402
from app.models.team_membership import TeamMembership  # noqa: E402
from app.models.user import User                 # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """
    A test HTTP client that calls the FastAPI app in-process.
    No network, no running server required.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session():
    """
    A raw SQLAlchemy session for setting up/tearing down fixture data
    directly, bypassing the API. Tracks everything it creates and deletes it
    on teardown so tests don't leak rows into each other (or into a
    persistent local `docker compose` Postgres across repeated runs).
    """
    session = SessionLocal()
    created_user_ids: list = []
    created_team_ids: list = []
    created_environment_ids: list = []

    session.track_user = lambda u: created_user_ids.append(u.id) or u               # type: ignore[attr-defined]
    session.track_team = lambda t: created_team_ids.append(t.id) or t               # type: ignore[attr-defined]
    session.track_environment = lambda e: created_environment_ids.append(e.id) or e  # type: ignore[attr-defined]

    yield session

    session.rollback()
    if created_environment_ids:
        # runbooks.environment_id and audit_logs.environment_id both FK to
        # environments.id with no ON DELETE CASCADE, so both must clear
        # before the environment rows themselves — same reasoning as the
        # actor_id ordering below, applied one table over.
        session.query(Runbook).filter(
            Runbook.environment_id.in_(created_environment_ids)
        ).delete(synchronize_session=False)
        session.query(AuditLog).filter(
            AuditLog.environment_id.in_(created_environment_ids)
        ).delete(synchronize_session=False)
    if created_user_ids:
        # audit_logs.actor_id has no ON DELETE CASCADE — intentionally, so a
        # real user's audit trail survives them (there's no user-deletion
        # endpoint anyway). But it means test rows created by these fixture
        # users (API key generation, team creation, membership changes,
        # role changes all write an audit log) must be cleared before the
        # users themselves, or Postgres raises ForeignKeyViolation here.
        session.query(AuditLog).filter(AuditLog.actor_id.in_(created_user_ids)).delete(synchronize_session=False)
    if created_environment_ids:
        # environments.team_id / created_by both FK to teams/users — clear
        # environments before the teams and users that own them.
        session.query(Environment).filter(
            Environment.id.in_(created_environment_ids)
        ).delete(synchronize_session=False)
    if created_user_ids or created_team_ids:
        # NEW: team_memberships.user_id / team_id both FK to users/teams
        # with no cascade — must clear before either side is deleted below.
        # A membership row involves a tracked user OR a tracked team (every
        # membership in these tests was created via a tracked fixture on at
        # least one side), so this single filter catches everything.
        session.query(TeamMembership).filter(
            TeamMembership.user_id.in_(created_user_ids) | TeamMembership.team_id.in_(created_team_ids)
        ).delete(synchronize_session=False)
    if created_user_ids:
        session.query(User).filter(User.id.in_(created_user_ids)).delete(synchronize_session=False)
    if created_team_ids:
        session.query(Team).filter(Team.id.in_(created_team_ids)).delete(synchronize_session=False)
    session.commit()
    session.close()


def _make_user(db_session, *, platform_role: str = "user", username: Optional[str] = None) -> User:
    user = User(
        github_id=uuid.uuid4().int % (2**62),  # arbitrary unique bigint-sized id
        username=username or f"test-user-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        platform_role=platform_role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    db_session.track_user(user)
    return user


def _make_membership(db_session, *, user_id, team_id, role: str = "member") -> TeamMembership:
    membership = TeamMembership(user_id=user_id, team_id=team_id, role=role)
    db_session.add(membership)
    db_session.commit()
    db_session.refresh(membership)
    return membership


def _make_token(user: User) -> str:
    """JWT payload is {user_id, exp} only — see middleware/auth.py's module
    docstring for why authorization data was removed from the token."""
    payload = {
        "user_id": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


@pytest.fixture
def make_membership(db_session):
    """
    Factory fixture for creating a TeamMembership row directly, e.g.:

        make_membership(user_id=some_user.id, team_id=some_team.id, role="team_admin")

    Use this whenever a test needs a user already sitting in a particular
    team role, without going through POST /teams/{id}/members.
    """

    def _factory(**kwargs) -> TeamMembership:
        return _make_membership(db_session, **kwargs)

    return _factory


@pytest.fixture
def test_team(db_session) -> Team:
    suffix = uuid.uuid4().hex[:8]
    team = Team(name=f"Test Team {suffix}", slug=f"test-team-{suffix}")
    db_session.add(team)
    db_session.commit()
    db_session.refresh(team)
    db_session.track_team(team)
    return team


@pytest.fixture
def second_team(db_session) -> Team:
    """A second, independent team — for multi-team scenarios where a single
    `test_team` isn't enough to prove cross-team isolation."""
    suffix = uuid.uuid4().hex[:8]
    team = Team(name=f"Second Team {suffix}", slug=f"second-team-{suffix}")
    db_session.add(team)
    db_session.commit()
    db_session.refresh(team)
    db_session.track_team(team)
    return team


@pytest.fixture
def member_user(db_session, test_team) -> User:
    user = _make_user(db_session)
    _make_membership(db_session, user_id=user.id, team_id=test_team.id, role="member")
    return user


@pytest.fixture
def member_token(member_user) -> str:
    return _make_token(member_user)


@pytest.fixture
def team_admin_user(db_session, test_team) -> User:
    user = _make_user(db_session)
    _make_membership(db_session, user_id=user.id, team_id=test_team.id, role="team_admin")
    return user


@pytest.fixture
def team_admin_token(team_admin_user) -> str:
    return _make_token(team_admin_user)


@pytest.fixture
def super_admin_user(db_session) -> User:
    return _make_user(db_session, platform_role="super_admin")


@pytest.fixture
def super_admin_token(super_admin_user) -> str:
    return _make_token(super_admin_user)


@pytest.fixture
def member_without_team_user(db_session) -> User:
    """
    A user with platform_role='user' and ZERO team memberships. Under the
    old single-team model this represented "team_id is None" specifically;
    under multi-team it's the more general (and more common) case of a
    user who hasn't joined any team yet — the case create_environment must
    reject with 403 (not a member of the requested team), and the case
    self-serve team creation exists to resolve.
    """
    return _make_user(db_session)


@pytest.fixture
def member_without_team_token(member_without_team_user) -> str:
    return _make_token(member_without_team_user)


@pytest.fixture
def user_on_two_teams(db_session, test_team, second_team) -> User:
    """
    member on test_team, team_admin on second_team — the "embedded engineer
    across two teams" scenario multi-team membership was built to support.
    Used to prove role checks are scoped per-team, not read off a single
    global value.
    """
    user = _make_user(db_session)
    _make_membership(db_session, user_id=user.id, team_id=test_team.id, role="member")
    _make_membership(db_session, user_id=user.id, team_id=second_team.id, role="team_admin")
    return user


@pytest.fixture
def user_on_two_teams_token(user_on_two_teams) -> str:
    return _make_token(user_on_two_teams)


def _make_environment(
    db_session,
    *,
    team_id,
    created_by,
    status: str = "RUNNING",
    env_type: str = "dev",
    ttl_hours: int = 24,
    expires_at: Optional[datetime] = None,
    name: Optional[str] = None,
) -> Environment:
    env = Environment(
        name=name or f"test-env-{uuid.uuid4().hex[:8]}",
        team_id=team_id,
        created_by=created_by,
        env_type=env_type,
        status=status,
        ttl_hours=ttl_hours,
        expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)),
        aws_region="us-east-1",
    )
    db_session.add(env)
    db_session.commit()
    db_session.refresh(env)
    db_session.track_environment(env)
    return env


@pytest.fixture
def make_environment(db_session):
    """
    Factory fixture — bypasses the API to create an Environment row
    directly, e.g.:

        env = make_environment(team_id=test_team.id, created_by=member_user.id,
                                status="RUNNING")

    Use this (rather than POST /environments) whenever a test needs an
    environment already sitting in a particular status, since POST always
    starts a real one at PENDING and dispatches a workflow.
    """

    def _factory(**kwargs) -> Environment:
        return _make_environment(db_session, **kwargs)

    return _factory


@pytest.fixture
def user_with_api_key(db_session) -> User:
    """
    A user with a real API key set. `.raw_key` carries the plaintext key
    for test use only — in production this is never stored or retrievable
    after generation.
    """
    user = _make_user(db_session)
    raw_key = f"idplite_test_{uuid.uuid4().hex}"
    user.api_key_hash = bcrypt.hash(raw_key)
    db_session.commit()
    db_session.refresh(user)
    user.raw_key = raw_key  # type: ignore[attr-defined]
    return user