"""
Environment Lifecycle Integration Tests
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.environment import Environment
from app.models.runbook import Runbook
from app.models.team_membership import TeamMembership
from app.models.user import User
from app.services import terraform


@pytest.fixture
def mock_terraform(monkeypatch):
    """
    Replaces services.terraform.trigger_provision/trigger_destroy/
    trigger_pause/trigger_resume with recording stand-ins. The router calls
    these via the `terraform` module object (not a direct function import),
    so patching the module's attributes here is visible to the router
    without touching its code.
    """
    calls = {"provision": [], "destroy": [], "pause": [], "resume": []}

    def fake_provision(**kwargs):
        calls["provision"].append(kwargs)

    def fake_destroy(*args, **kwargs):
        calls["destroy"].append({"args": args, "kwargs": kwargs})

    def fake_pause(*args, **kwargs):
        calls["pause"].append({"args": args, "kwargs": kwargs})

    def fake_resume(*args, **kwargs):
        calls["resume"].append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(terraform, "trigger_provision", fake_provision)
    monkeypatch.setattr(terraform, "trigger_destroy", fake_destroy)
    monkeypatch.setattr(terraform, "trigger_pause", fake_pause)
    monkeypatch.setattr(terraform, "trigger_resume", fake_resume)
    return calls


def _track(db_session, env_id: str) -> None:
    """Registers an API-created (rather than factory-created) environment
    for teardown cleanup — see db_session's created_environment_ids list."""
    db_session.track_environment(SimpleNamespace(id=uuid.UUID(env_id)))


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _callback_auth() -> dict:
    """
    Header for GitHub-Actions-only endpoints, built from the actual
    configured secret rather than a literal — CI sets CALLBACK_SECRET to
    `ci-callback-secret` while conftest.py's local default is
    `test-callback-secret`; hardcoding either value here would pass in one
    environment and silently 403 in the other.
    """
    return {"X-Callback-Secret": settings.callback_secret}


def _make_other_team_owner(db_session, team_id: uuid.UUID) -> User:
    """
    A minimal, one-off user belonging to a different team than the
    conftest.py `test_team` fixture — used only to own environments that
    cross-team-access tests then try (and should fail) to reach.
    """
    owner = User(
        github_id=uuid.uuid4().int % (2**62),
        username=f"other-team-owner-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        platform_role="user",
    )
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    db_session.track_user(owner)

    db_session.add(TeamMembership(user_id=owner.id, team_id=team_id, role="member"))
    db_session.commit()
    return owner


def _make_other_team(client: TestClient, super_admin_token: str, db_session) -> str:
    """Creates a second team via the real API and registers it for teardown."""
    suffix = uuid.uuid4().hex[:6]
    response = client.post(
        "/teams/",
        json={"name": f"Other Team {suffix}", "slug": f"other-team-{suffix}"},
        headers=_auth(super_admin_token),
    )
    team_id = response.json()["id"]
    db_session.track_team(SimpleNamespace(id=uuid.UUID(team_id)))
    return team_id


class TestCostPreview:
    """No auth required — pure calculator, nothing private involved."""

    def test_dev_preview_returns_itemized_breakdown(self, client: TestClient):
        response = client.get("/environments/cost-preview?env_type=dev")
        assert response.status_code == 200
        body = response.json()
        assert body["env_type"] == "dev"
        assert set(body.keys()) >= {
            "ecs_fargate", "rds_postgres", "cloudwatch_logs",
            "secrets_manager", "total_monthly", "note",
        }
        assert body["total_monthly"] > 0

    def test_staging_costs_more_than_dev(self, client: TestClient):
        dev = client.get("/environments/cost-preview?env_type=dev").json()
        staging = client.get("/environments/cost-preview?env_type=staging").json()
        assert staging["total_monthly"] > dev["total_monthly"]

    def test_invalid_env_type_is_rejected(self, client: TestClient):
        response = client.get("/environments/cost-preview?env_type=prod")
        assert response.status_code == 422

    def test_requires_no_auth(self, client: TestClient):
        response = client.get("/environments/cost-preview?env_type=dev")
        assert response.status_code != 401


class TestCreateEnvironment:
    def test_requires_auth(self, client: TestClient):
        # A syntactically valid team_id so the ONLY failure reason is
        # missing auth, not incidental body validation.
        response = client.post(
            "/environments/",
            json={"name": "x", "team_id": str(uuid.uuid4()), "env_type": "dev", "ttl_hours": 24},
        )
        assert response.status_code == 401

    def test_missing_team_id_is_rejected(self, client: TestClient, member_token: str):
        response = client.post(
            "/environments/",
            json={"name": "no-team-env", "env_type": "dev", "ttl_hours": 24},
            headers=_auth(member_token),
        )
        assert response.status_code == 422

    def test_team_you_are_not_a_member_of_is_rejected(
        self, client: TestClient, member_without_team_token: str, test_team
    ):
        """A syntactically valid team_id the caller has no membership on —
        different failure mode than the missing-field case above: this is
        has_team_role() rejecting it at the handler level (403), not
        Pydantic rejecting the shape of the request (422)."""
        response = client.post(
            "/environments/",
            json={"name": "wrong-team-env", "team_id": str(test_team.id), "env_type": "dev", "ttl_hours": 24},
            headers=_auth(member_without_team_token),
        )
        assert response.status_code == 403

    def test_invalid_name_pattern_is_rejected(self, client: TestClient, member_token: str, test_team):
        response = client.post(
            "/environments/",
            json={"name": "Not_Valid", "team_id": str(test_team.id), "env_type": "dev", "ttl_hours": 24},
            headers=_auth(member_token),
        )
        assert response.status_code == 422

    def test_invalid_env_type_is_rejected(self, client: TestClient, member_token: str, test_team):
        response = client.post(
            "/environments/",
            json={"name": "valid-name", "team_id": str(test_team.id), "env_type": "prod", "ttl_hours": 24},
            headers=_auth(member_token),
        )
        assert response.status_code == 422

    def test_ttl_out_of_range_is_rejected(self, client: TestClient, member_token: str, test_team):
        response = client.post(
            "/environments/",
            json={"name": "valid-name", "team_id": str(test_team.id), "env_type": "dev", "ttl_hours": 999},
            headers=_auth(member_token),
        )
        assert response.status_code == 422

    def test_success_returns_202_pending(
        self, client: TestClient, member_token: str, test_team, db_session, mock_terraform
    ):
        response = client.post(
            "/environments/",
            json={
                "name": f"env-{uuid.uuid4().hex[:8]}",
                "team_id": str(test_team.id),
                "env_type": "dev",
                "ttl_hours": 24,
            },
            headers=_auth(member_token),
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "PENDING"
        assert uuid.UUID(body["env_id"])
        _track(db_session, body["env_id"])

    def test_creates_row_with_cost_estimate_and_writes_audit_log(
        self, client: TestClient, member_user, test_team, member_token: str, db_session, mock_terraform
    ):
        response = client.post(
            "/environments/",
            json={
                "name": f"env-{uuid.uuid4().hex[:8]}",
                "team_id": str(test_team.id),
                "env_type": "staging",
                "ttl_hours": 48,
            },
            headers=_auth(member_token),
        )
        env_id = response.json()["env_id"]
        _track(db_session, env_id)

        env = db_session.query(Environment).filter(Environment.id == env_id).first()
        assert env is not None
        assert env.status == "PENDING"
        assert env.created_by == member_user.id
        assert env.team_id == test_team.id
        assert env.cost_estimate_usd is not None
        assert float(env.cost_estimate_usd) > 0

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env_id, AuditLog.action == "ENV_CREATED")
            .first()
        )
        assert audit is not None
        assert audit.actor_id == member_user.id
        assert audit.event_metadata["env_type"] == "staging"

    def test_dispatches_provision_workflow_with_correct_inputs(
        self, client: TestClient, member_user, test_team, member_token: str,
        db_session, mock_terraform,
    ):
        response = client.post(
            "/environments/",
            json={
                "name": "dispatch-check",
                "team_id": str(test_team.id),
                "env_type": "dev",
                "ttl_hours": 12,
            },
            headers=_auth(member_token),
        )
        env_id = response.json()["env_id"]
        _track(db_session, env_id)

        assert len(mock_terraform["provision"]) == 1
        call = mock_terraform["provision"][0]
        assert call["env_id"] == env_id
        assert call["env_name"] == "dispatch-check"
        assert call["team"] == test_team.slug
        assert call["env_type"] == "dev"
        assert call["ttl_hours"] == 12


class TestListEnvironments:
    def test_requires_auth(self, client: TestClient):
        assert client.get("/environments/").status_code == 401

    def test_member_sees_only_own_team(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        own = make_environment(team_id=test_team.id, created_by=member_user.id)

        response = client.get("/environments/", headers=_auth(member_token))
        assert response.status_code == 200
        ids = {e["id"] for e in response.json()}
        assert str(own.id) in ids

    def test_super_admin_sees_all_teams(
        self, client: TestClient, super_admin_token, member_user, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id)
        response = client.get("/environments/", headers=_auth(super_admin_token))
        assert response.status_code == 200
        ids = {e["id"] for e in response.json()}
        assert str(env.id) in ids

    def test_user_on_two_teams_sees_environments_from_both(
        self, client: TestClient, user_on_two_teams, user_on_two_teams_token,
        test_team, second_team, make_environment,
    ):
        env_a = make_environment(team_id=test_team.id, created_by=user_on_two_teams.id)
        env_b = make_environment(team_id=second_team.id, created_by=user_on_two_teams.id)

        response = client.get("/environments/", headers=_auth(user_on_two_teams_token))
        assert response.status_code == 200
        ids = {e["id"] for e in response.json()}
        assert str(env_a.id) in ids
        assert str(env_b.id) in ids

    def test_team_id_filter_narrows_to_one_of_callers_own_teams(
        self, client: TestClient, user_on_two_teams, user_on_two_teams_token,
        test_team, second_team, make_environment,
    ):
        env_a = make_environment(team_id=test_team.id, created_by=user_on_two_teams.id)
        make_environment(team_id=second_team.id, created_by=user_on_two_teams.id)

        response = client.get(
            f"/environments/?team_id={test_team.id}", headers=_auth(user_on_two_teams_token)
        )
        assert response.status_code == 200
        ids = {e["id"] for e in response.json()}
        assert ids == {str(env_a.id)}

    def test_team_id_filter_rejects_a_team_the_caller_is_not_on(
        self, client: TestClient, member_token, db_session, super_admin_token
    ):
        other_team_id = _make_other_team(client, super_admin_token, db_session)
        response = client.get(f"/environments/?team_id={other_team_id}", headers=_auth(member_token))
        assert response.status_code == 403


class TestGetEnvironment:
    def test_requires_auth(self, client: TestClient):
        assert client.get(f"/environments/{uuid.uuid4()}").status_code == 401

    def test_unknown_id_returns_404(self, client: TestClient, member_token):
        response = client.get(f"/environments/{uuid.uuid4()}", headers=_auth(member_token))
        assert response.status_code == 404

    def test_own_team_environment_returns_full_detail(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING", env_type="dev",
        )
        response = client.get(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(env.id)
        assert body["status"] == "RUNNING"
        assert body["env_type"] == "dev"
        assert body["health_status"] == "UNKNOWN"

    def test_cross_team_access_is_forbidden(
        self, client: TestClient, member_token, super_admin_token, db_session, make_environment,
    ):
        other_team_id = _make_other_team(client, super_admin_token, db_session)
        owner = _make_other_team_owner(db_session, uuid.UUID(other_team_id))
        env = make_environment(team_id=uuid.UUID(other_team_id), created_by=owner.id)

        response = client.get(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 403

    def test_super_admin_can_view_any_team(
        self, client: TestClient, super_admin_token, member_user, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id)
        response = client.get(f"/environments/{env.id}", headers=_auth(super_admin_token))
        assert response.status_code == 200

    def test_user_on_two_teams_can_view_environments_on_either(
        self, client: TestClient, user_on_two_teams, user_on_two_teams_token,
        test_team, second_team, make_environment,
    ):
        env_a = make_environment(team_id=test_team.id, created_by=user_on_two_teams.id)
        env_b = make_environment(team_id=second_team.id, created_by=user_on_two_teams.id)

        assert client.get(f"/environments/{env_a.id}", headers=_auth(user_on_two_teams_token)).status_code == 200
        assert client.get(f"/environments/{env_b.id}", headers=_auth(user_on_two_teams_token)).status_code == 200


class TestDestroyEnvironment:
    def test_requires_auth(self, client: TestClient):
        assert client.delete(f"/environments/{uuid.uuid4()}").status_code == 401

    def test_cancelling_pending_environment_succeeds_immediately(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        """Regression test for the original bug this feature fixes: a
        PENDING environment (never confirmed provisioned OR destroyed —
        see routers/environments.py's 'CANCELLING A PENDING ENVIRONMENT')
        used to have no exit at all. It must now go straight to DESTROYED,
        not DESTROYING — waiting on a callback here would just trade one
        stuck status for another in exactly the unconfigured-GitHub-Actions
        setups where this is most likely to happen."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PENDING")
        response = client.delete(f"/environments/{env.id}", headers=_auth(member_token))

        assert response.status_code == 200  # not 202 — nothing async is pending
        assert response.json()["status"] == "DESTROYED"

        db_session.refresh(env)
        assert env.status == "DESTROYED"
        assert env.destroyed_at is not None

    def test_cancelling_pending_environment_fires_best_effort_destroy_dispatch(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform,
    ):
        """The best-effort terraform.trigger_destroy() insurance call
        described in the module docstring — must still fire even though
        the DB doesn't wait on it."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PENDING")
        client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        assert len(mock_terraform["destroy"]) == 1

    def test_cancelling_pending_environment_logs_env_cancelled_not_env_destroyed(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PENDING")
        client.delete(f"/environments/{env.id}", headers=_auth(member_token))

        cancelled_audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_CANCELLED")
            .first()
        )
        assert cancelled_audit is not None
        assert cancelled_audit.event_metadata["confirmed_teardown"] is False

        destroyed_audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_DESTROYED")
            .first()
        )
        assert destroyed_audit is None  # never confirmed — must not claim otherwise

    def test_member_can_cancel_own_pending_environment_but_not_teammates(
        self, client: TestClient, member_user, member_token, team_admin_user, test_team,
        make_environment, mock_terraform,
    ):
        own_env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PENDING")
        teammates_env = make_environment(team_id=test_team.id, created_by=team_admin_user.id, status="PENDING")

        assert client.delete(f"/environments/{own_env.id}", headers=_auth(member_token)).status_code == 200
        assert client.delete(f"/environments/{teammates_env.id}", headers=_auth(member_token)).status_code == 403

    def test_cancelling_pending_environment_unblocks_team_deletion(
        self, client: TestClient, team_admin_token, team_admin_user, test_team,
        make_environment, mock_terraform, db_session,
    ):
        """End-to-end regression test for the actual reported problem: a
        team with a stuck PENDING environment could never be deleted."""
        env = make_environment(team_id=test_team.id, created_by=team_admin_user.id, status="PENDING")

        blocked = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
        assert blocked.status_code == 400

        cancel = client.delete(f"/environments/{env.id}", headers=_auth(team_admin_token))
        assert cancel.status_code == 200

        unblocked = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
        assert unblocked.status_code == 200

    def test_late_callback_after_pending_cancellation_is_ignored(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        """A provision workflow dispatched before cancellation reports
        back (e.g. RUNNING) long after the row was already closed. Must
        NOT resurrect the environment — see 'CANCELLING A PENDING
        ENVIRONMENT' in the module docstring."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PENDING")
        client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        db_session.refresh(env)
        assert env.status == "DESTROYED"

        late_callback = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "RUNNING", "outputs": {"ecs_service_arn": "arn:aws:ecs:fake"}},
            headers={"X-Callback-Secret": settings.callback_secret},
        )
        assert late_callback.status_code == 200
        assert late_callback.json()["ignored"] is True

        db_session.refresh(env)
        assert env.status == "DESTROYED"  # unchanged — not resurrected

        ignored_audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_CALLBACK_IGNORED")
            .first()
        )
        assert ignored_audit is not None
        assert ignored_audit.event_metadata["attempted_status"] == "RUNNING"

    def test_late_callback_after_normal_destroy_is_also_ignored(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        """The DESTROYED guard in the callback handler isn't specific to
        cancelled-from-PENDING environments — any already-DESTROYED
        environment must reject a late callback the same way, including
        the normal RUNNING -> DESTROYING -> DESTROYED path."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYING")

        first_callback = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "DESTROYED", "actor": member_user.username},
            headers={"X-Callback-Secret": settings.callback_secret},
        )
        assert first_callback.status_code == 200
        assert "ignored" not in first_callback.json()

        second_callback = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "FAILED", "error": "duplicate delivery"},
            headers={"X-Callback-Secret": settings.callback_secret},
        )
        assert second_callback.status_code == 200
        assert second_callback.json()["ignored"] is True

        db_session.refresh(env)
        assert env.status == "DESTROYED"

    def test_member_can_destroy_own_environment(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
        response = client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 202
        assert response.json()["status"] == "DESTROYING"

        db_session.refresh(env)
        assert env.status == "DESTROYING"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_DESTROY_REQUESTED")
            .first()
        )
        assert audit is not None
        assert len(mock_terraform["destroy"]) == 1

    def test_member_cannot_destroy_teammates_environment(
        self, client: TestClient, member_token, team_admin_user, test_team,
        make_environment, mock_terraform,
    ):
        env = make_environment(team_id=test_team.id, created_by=team_admin_user.id, status="RUNNING")
        response = client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 403

    def test_team_admin_can_destroy_any_team_environment(
        self, client: TestClient, team_admin_token, member_user, test_team,
        make_environment, mock_terraform,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
        response = client.delete(f"/environments/{env.id}", headers=_auth(team_admin_token))
        assert response.status_code == 202

    def test_failed_environment_can_be_destroyed(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="FAILED")
        response = client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 202

    def test_no_membership_on_this_environments_team_is_forbidden(
        self, client: TestClient, member_token, super_admin_token, db_session, make_environment, mock_terraform,
    ):
        """A user with no membership on the environment's team at all —
        distinct from the ownership-based 403 above, which is for a
        teammate who just isn't the creator. This is "not on this team,
        full stop"."""
        other_team_id = _make_other_team(client, super_admin_token, db_session)
        owner = _make_other_team_owner(db_session, uuid.UUID(other_team_id))
        env = make_environment(team_id=uuid.UUID(other_team_id), created_by=owner.id, status="RUNNING")

        response = client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 403

    def test_team_admin_on_other_team_cannot_destroy_this_team_environment(
        self, client: TestClient, user_on_two_teams, user_on_two_teams_token,
        test_team, second_team, member_user, make_environment, mock_terraform,
    ):
        """
        The scoping test the old single-team suite couldn't even express:
        user_on_two_teams IS a team_admin — but only on second_team.
        On test_team, they hold no membership at all. Their admin status on
        the OTHER team must grant them nothing here.
        """
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
        response = client.delete(f"/environments/{env.id}", headers=_auth(user_on_two_teams_token))
        assert response.status_code == 403

    def test_team_admin_can_destroy_on_the_team_they_actually_admin(
        self, client: TestClient, user_on_two_teams, user_on_two_teams_token,
        second_team, make_environment, mock_terraform,
    ):
        """Same user as above, but acting on second_team — where they
        genuinely are team_admin — succeeds."""
        env = make_environment(team_id=second_team.id, created_by=user_on_two_teams.id, status="RUNNING")
        response = client.delete(f"/environments/{env.id}", headers=_auth(user_on_two_teams_token))
        assert response.status_code == 202

    def test_expiring_environment_can_be_destroyed_directly(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        """DESTROYABLE_STATUSES was widened to include EXPIRING — see
        routers/environments.py's module docstring, 'GRACE PERIOD & PAUSE
        SAFETY NET'. A user shouldn't be forced through the pause flow if
        they'd rather just destroy directly."""
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="EXPIRING",
            expiring_since=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        response = client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 202
        assert response.json()["status"] == "DESTROYING"

    def test_paused_environment_can_be_destroyed_directly(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="PAUSED",
            paused_at=datetime.now(timezone.utc) - timedelta(days=1),
            pause_expires_at=datetime.now(timezone.utc) + timedelta(days=6),
        )
        response = client.delete(f"/environments/{env.id}", headers=_auth(member_token))
        assert response.status_code == 202

        db_session.refresh(env)
        assert env.status == "DESTROYING"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_DESTROY_REQUESTED")
            .first()
        )
        assert audit is not None
        assert audit.event_metadata["destroyed_from_status"] == "PAUSED"


class TestPauseEnvironment:
    """POST /environments/{id}/pause — manual pause, available from RUNNING
    or EXPIRING. See routers/environments.py's module docstring, 'GRACE
    PERIOD & PAUSE SAFETY NET'."""

    def test_requires_auth(self, client: TestClient):
        assert client.post(f"/environments/{uuid.uuid4()}/pause").status_code == 401

    def test_pause_from_running_succeeds(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
        response = client.post(f"/environments/{env.id}/pause", headers=_auth(member_token))
        assert response.status_code == 202
        assert response.json()["status"] == "PAUSING"

        db_session.refresh(env)
        assert env.status == "PAUSING"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_PAUSE_REQUESTED")
            .first()
        )
        assert audit is not None
        assert audit.event_metadata["reason"] == "manual"
        assert len(mock_terraform["pause"]) == 1

    def test_pause_from_expiring_succeeds(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        """Manual pause works from EXPIRING too, not just RUNNING — there's
        no reason to force someone through the automatic-pause path just
        because their grace period already started."""
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="EXPIRING",
            expiring_since=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        response = client.post(f"/environments/{env.id}/pause", headers=_auth(member_token))
        assert response.status_code == 202

        db_session.refresh(env)
        assert env.status == "PAUSING"

    def test_pause_from_pending_is_rejected(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PENDING")
        response = client.post(f"/environments/{env.id}/pause", headers=_auth(member_token))
        assert response.status_code == 400

    def test_pause_from_already_paused_is_rejected(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PAUSED")
        response = client.post(f"/environments/{env.id}/pause", headers=_auth(member_token))
        assert response.status_code == 400

    def test_member_cannot_pause_teammates_environment(
        self, client: TestClient, member_token, team_admin_user, test_team,
        make_environment, mock_terraform,
    ):
        env = make_environment(team_id=test_team.id, created_by=team_admin_user.id, status="RUNNING")
        response = client.post(f"/environments/{env.id}/pause", headers=_auth(member_token))
        assert response.status_code == 403

    def test_team_admin_can_pause_any_team_environment(
        self, client: TestClient, team_admin_token, member_user, test_team,
        make_environment, mock_terraform,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
        response = client.post(f"/environments/{env.id}/pause", headers=_auth(team_admin_token))
        assert response.status_code == 202

    def test_no_membership_on_this_team_is_forbidden(
        self, client: TestClient, member_token, super_admin_token, db_session, make_environment,
    ):
        other_team_id = _make_other_team(client, super_admin_token, db_session)
        owner = _make_other_team_owner(db_session, uuid.UUID(other_team_id))
        env = make_environment(team_id=uuid.UUID(other_team_id), created_by=owner.id, status="RUNNING")
        response = client.post(f"/environments/{env.id}/pause", headers=_auth(member_token))
        assert response.status_code == 403


class TestResumeEnvironment:
    """POST /environments/{id}/resume — from PAUSED only. See
    routers/environments.py's module docstring, 'GRACE PERIOD & PAUSE
    SAFETY NET'."""

    def test_requires_auth(self, client: TestClient):
        assert client.post(f"/environments/{uuid.uuid4()}/resume").status_code == 401

    def test_resume_from_paused_succeeds(
        self, client: TestClient, member_user, member_token, test_team,
        make_environment, mock_terraform, db_session,
    ):
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="PAUSED",
            paused_at=datetime.now(timezone.utc) - timedelta(days=1),
            pause_expires_at=datetime.now(timezone.utc) + timedelta(days=6),
        )
        response = client.post(f"/environments/{env.id}/resume", headers=_auth(member_token))
        assert response.status_code == 202
        assert response.json()["status"] == "RESUMING"

        db_session.refresh(env)
        assert env.status == "RESUMING"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_RESUME_REQUESTED")
            .first()
        )
        assert audit is not None
        assert len(mock_terraform["resume"]) == 1

    def test_resume_from_running_is_rejected(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
        response = client.post(f"/environments/{env.id}/resume", headers=_auth(member_token))
        assert response.status_code == 400

    def test_member_cannot_resume_teammates_environment(
        self, client: TestClient, member_token, team_admin_user, test_team,
        make_environment, mock_terraform,
    ):
        env = make_environment(team_id=test_team.id, created_by=team_admin_user.id, status="PAUSED")
        response = client.post(f"/environments/{env.id}/resume", headers=_auth(member_token))
        assert response.status_code == 403

    def test_team_admin_can_resume_any_team_environment(
        self, client: TestClient, team_admin_token, member_user, test_team,
        make_environment, mock_terraform,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PAUSED")
        response = client.post(f"/environments/{env.id}/resume", headers=_auth(team_admin_token))
        assert response.status_code == 202


class TestExtendTTL:
    def test_requires_auth(self, client: TestClient):
        response = client.patch(f"/environments/{uuid.uuid4()}/ttl", json={"extend_hours": 24})
        assert response.status_code == 401

    def test_only_running_can_be_extended(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PENDING")
        response = client.patch(
            f"/environments/{env.id}/ttl", json={"extend_hours": 24}, headers=_auth(member_token)
        )
        assert response.status_code == 400

    def test_extends_expiry_and_writes_audit_log(
        self, client: TestClient, member_user, member_token, test_team, make_environment, db_session,
    ):
        original_expiry = datetime.now(timezone.utc) + timedelta(hours=2)
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING",
            expires_at=original_expiry,
        )
        response = client.patch(
            f"/environments/{env.id}/ttl", json={"extend_hours": 24}, headers=_auth(member_token)
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.expires_at > original_expiry
        assert env.ttl_hours == 24 + 24  # factory default ttl_hours=24 + extension

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "TTL_EXTENDED")
            .first()
        )
        assert audit is not None
        assert audit.event_metadata["extended_by_hours"] == 24

    def test_extend_hours_out_of_range_is_rejected(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
        response = client.patch(
            f"/environments/{env.id}/ttl", json={"extend_hours": 0}, headers=_auth(member_token)
        )
        assert response.status_code == 422

    def test_cross_team_extend_is_forbidden(
        self, client: TestClient, member_token, super_admin_token, db_session, make_environment,
    ):
        other_team_id = _make_other_team(client, super_admin_token, db_session)
        owner = _make_other_team_owner(db_session, uuid.UUID(other_team_id))
        env = make_environment(team_id=uuid.UUID(other_team_id), created_by=owner.id, status="RUNNING")

        response = client.patch(
            f"/environments/{env.id}/ttl", json={"extend_hours": 24}, headers=_auth(member_token)
        )
        assert response.status_code == 403

    def test_extend_from_expiring_cancels_grace_period(
        self, client: TestClient, member_user, member_token, test_team, make_environment, db_session,
    ):
        """Extending from EXPIRING cancels the grace period outright and
        returns to RUNNING — see routers/environments.py's module
        docstring, 'GRACE PERIOD & PAUSE SAFETY NET'."""
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="EXPIRING",
            expiring_since=datetime.now(timezone.utc) - timedelta(hours=1),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        response = client.patch(
            f"/environments/{env.id}/ttl", json={"extend_hours": 24}, headers=_auth(member_token)
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.status == "RUNNING"
        assert env.expiring_since is None

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_EXTENDED_FROM_EXPIRING")
            .first()
        )
        assert audit is not None
        assert audit.event_metadata["cancelled_grace_period"] is True

        # And a plain TTL_EXTENDED must NOT also have been logged for this
        # same request — the two actions are mutually exclusive per call.
        plain_extend = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "TTL_EXTENDED")
            .first()
        )
        assert plain_extend is None

    def test_cannot_extend_a_paused_environment(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        """PAUSED isn't in the extendable set — resuming (which grants a
        fresh TTL window) is the correct action there, not extending a TTL
        that isn't currently counting down."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PAUSED")
        response = client.patch(
            f"/environments/{env.id}/ttl", json={"extend_hours": 24}, headers=_auth(member_token)
        )
        assert response.status_code == 400


class TestCallback:
    def test_missing_secret_is_rejected(self, client: TestClient):
        response = client.post(
            f"/environments/{uuid.uuid4()}/callback", json={"status": "RUNNING"}
        )
        assert response.status_code == 403

    def test_wrong_secret_is_rejected(self, client: TestClient):
        response = client.post(
            f"/environments/{uuid.uuid4()}/callback",
            json={"status": "RUNNING"},
            headers={"X-Callback-Secret": "wrong-secret"},
        )
        assert response.status_code == 403

    def test_unknown_environment_returns_404(self, client: TestClient):
        response = client.post(
            f"/environments/{uuid.uuid4()}/callback",
            json={"status": "RUNNING"},
            headers=_callback_auth(),
        )
        assert response.status_code == 404

    def test_rejects_status_outside_callback_enum(
        self, client: TestClient, member_user, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PROVISIONING")
        # PENDING/PROVISIONING/DESTROYING are states the API sets itself —
        # a callback is never allowed to claim them.
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "PENDING"},
            headers=_callback_auth(),
        )
        assert response.status_code == 422

    def test_running_status_stores_outputs_and_generates_runbook(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PROVISIONING")
        outputs = {
            "ecs_service_arn": "arn:aws:ecs:us-east-1:123:service/foo",
            "ecs_cluster_arn": "arn:aws:ecs:us-east-1:123:cluster/outpost-shared",
            "rds_endpoint": "outpost-abc.rds.amazonaws.com",
            "rds_secret_arn": "arn:aws:secretsmanager:us-east-1:123:secret/outpost/abc/rds",
            "log_group_name": "/outpost/abc",
            "subnet_id": "subnet-123",
        }
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "RUNNING", "outputs": outputs},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.status == "RUNNING"
        assert env.outputs == outputs

        rb = db_session.query(Runbook).filter(Runbook.environment_id == env.id).first()
        assert rb is not None
        assert outputs["ecs_service_arn"] in rb.content_md
        assert outputs["rds_endpoint"] in rb.content_md

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_RUNNING")
            .first()
        )
        assert audit is not None
        assert audit.actor_type == "system"

    def test_running_callback_is_idempotent_for_runbook(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        """A retried callback (network blip on GitHub Actions' side) must
        update the existing runbook, not create a second row — content_md
        has a UNIQUE constraint on environment_id at the DB level."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PROVISIONING")
        outputs = {"rds_endpoint": "first.rds.amazonaws.com"}

        client.post(
            f"/environments/{env.id}/callback",
            json={"status": "RUNNING", "outputs": outputs},
            headers=_callback_auth(),
        )
        second_outputs = {"rds_endpoint": "second.rds.amazonaws.com"}
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "RUNNING", "outputs": second_outputs},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        runbooks = db_session.query(Runbook).filter(Runbook.environment_id == env.id).all()
        assert len(runbooks) == 1
        assert "second.rds.amazonaws.com" in runbooks[0].content_md

    def test_destroyed_status_sets_destroyed_at_and_actor_type(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYING")
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "DESTROYED", "actor": "cron"},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.status == "DESTROYED"
        assert env.destroyed_at is not None

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_DESTROYED")
            .first()
        )
        assert audit is not None
        assert audit.actor_type == "cron"
        assert audit.event_metadata["actor"] == "cron"

    def test_failed_status_stores_error_in_metadata(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PROVISIONING")
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "FAILED", "error": "terraform apply exited 1"},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.status == "FAILED"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_FAILED")
            .first()
        )
        assert audit is not None
        assert audit.event_metadata["error"] == "terraform apply exited 1"

    def test_paused_status_sets_pause_fields_and_writes_audit(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        """PAUSING -> PAUSED, confirmed by pause.yml. See routers/
        environments.py's module docstring, 'GRACE PERIOD & PAUSE SAFETY
        NET'."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PAUSING")
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "PAUSED", "actor": "cron"},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.status == "PAUSED"
        assert env.paused_at is not None
        assert env.pause_expires_at is not None
        actual_delta = env.pause_expires_at - env.paused_at
        assert abs(actual_delta - timedelta(days=settings.paused_max_days)) < timedelta(seconds=5)

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_PAUSED")
            .first()
        )
        assert audit is not None

    def test_resuming_to_running_does_not_overwrite_outputs(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        """The single most important regression guard added in this batch.
        resume.yml never re-runs `terraform apply`, so it reports back with
        no new outputs — this must NOT wipe out the real endpoints/ARNs
        recorded at original provision time. See environment_callback()'s
        RESUMING branch in routers/environments.py."""
        original_outputs = {"ecs_service_arn": "arn:aws:ecs:fake", "rds_endpoint": "db.example.com"}
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RESUMING",
            paused_at=datetime.now(timezone.utc) - timedelta(days=1),
            pause_expires_at=datetime.now(timezone.utc) + timedelta(days=6),
        )
        env.outputs = original_outputs
        db_session.commit()
        old_expires_at = env.expires_at

        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "RUNNING", "actor": member_user.username},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.status == "RUNNING"
        assert env.outputs == original_outputs  # untouched — the whole point of this test
        assert env.paused_at is None
        assert env.pause_expires_at is None
        assert env.expiring_since is None
        assert env.expires_at > old_expires_at  # fresh TTL window granted on resume

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_RESUMED")
            .first()
        )
        assert audit is not None

    def test_provisioning_to_running_still_overwrites_outputs(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        """Companion to the RESUMING test above — proves the two branches
        of the RUNNING callback are genuinely distinguished by the
        environment's prior status, not accidentally merged into one."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PROVISIONING")
        new_outputs = {"ecs_service_arn": "arn:aws:ecs:brand-new"}
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "RUNNING", "outputs": new_outputs},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.outputs == new_outputs

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_RUNNING")
            .first()
        )
        assert audit is not None

    def test_destroy_via_pause_expiry_logs_distinct_audit_action(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        """actor='cron_pause_expired' (set by ttl-cron.yml's Sweep-3
        dispatch) must log ENV_PAUSE_EXPIRED_DESTROYED, not an ordinary
        ENV_DESTROYED — this destroy was never requested by a human and
        was preceded by two separate advance warnings."""
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYING")
        response = client.post(
            f"/environments/{env.id}/callback",
            json={"status": "DESTROYED", "actor": "cron_pause_expired"},
            headers=_callback_auth(),
        )
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.status == "DESTROYED"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_PAUSE_EXPIRED_DESTROYED")
            .first()
        )
        assert audit is not None
        assert audit.actor_type == "cron"

        ordinary = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_DESTROYED")
            .first()
        )
        assert ordinary is None  # must not ALSO log the ordinary action


class TestProcessTTL:
    """POST /environments/process-ttl — the three-sweep (+ one warning
    pass) grace-period/pause state machine driver that replaced GET
    /environments/expired. See process_ttl()'s docstring in
    routers/environments.py for what each sweep does."""

    def test_missing_secret_is_rejected(self, client: TestClient):
        assert client.post("/environments/process-ttl").status_code == 403

    # --- Sweep 1: RUNNING -> EXPIRING ---

    def test_expired_running_environment_becomes_expiring(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING", expires_at=past,
        )

        response = client.post("/environments/process-ttl", headers=_callback_auth())
        assert response.status_code == 200
        assert str(env.id) in response.json()["transitioned_to_expiring"]

        db_session.refresh(env)
        assert env.status == "EXPIRING"
        assert env.expiring_since is not None

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_EXPIRING")
            .first()
        )
        assert audit is not None
        assert audit.actor_type == "cron"

    def test_running_environment_not_yet_expired_is_untouched(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING", expires_at=future,
        )
        response = client.post("/environments/process-ttl", headers=_callback_auth())
        assert response.status_code == 200
        assert str(env.id) not in response.json()["transitioned_to_expiring"]

        db_session.refresh(env)
        assert env.status == "RUNNING"

    # --- Sweep 2: EXPIRING -> PAUSING ---

    def test_expiring_past_grace_period_moves_to_pausing(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        grace_elapsed = datetime.now(timezone.utc) - timedelta(
            hours=settings.expiring_grace_period_hours + 1
        )
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="EXPIRING",
            expiring_since=grace_elapsed,
        )

        response = client.post("/environments/process-ttl", headers=_callback_auth())
        assert response.status_code == 200
        to_pause_ids = {t["env_id"] for t in response.json()["to_pause"]}
        assert str(env.id) in to_pause_ids

        db_session.refresh(env)
        assert env.status == "PAUSING"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_PAUSE_REQUESTED")
            .first()
        )
        assert audit is not None
        assert audit.actor_type == "cron"
        assert audit.event_metadata["reason"] == "grace_period_elapsed"

    def test_expiring_still_within_grace_period_is_untouched(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        just_started = datetime.now(timezone.utc) - timedelta(minutes=5)
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="EXPIRING",
            expiring_since=just_started,
        )
        response = client.post("/environments/process-ttl", headers=_callback_auth())
        assert response.status_code == 200
        to_pause_ids = {t["env_id"] for t in response.json()["to_pause"]}
        assert str(env.id) not in to_pause_ids

        db_session.refresh(env)
        assert env.status == "EXPIRING"

    # --- Sweep 3: PAUSED -> DESTROYING ---

    def test_paused_past_pause_window_moves_to_destroying(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="PAUSED",
            paused_at=datetime.now(timezone.utc) - timedelta(days=settings.paused_max_days, hours=1),
            pause_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        response = client.post("/environments/process-ttl", headers=_callback_auth())
        assert response.status_code == 200
        to_destroy_ids = {t["env_id"] for t in response.json()["to_destroy"]}
        assert str(env.id) in to_destroy_ids

        db_session.refresh(env)
        assert env.status == "DESTROYING"

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.environment_id == env.id, AuditLog.action == "ENV_DESTROY_REQUESTED")
            .first()
        )
        assert audit is not None
        assert audit.event_metadata["reason"] == "pause_window_elapsed"

    def test_paused_still_within_pause_window_is_untouched(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="PAUSED",
            paused_at=datetime.now(timezone.utc) - timedelta(days=1),
            pause_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        response = client.post("/environments/process-ttl", headers=_callback_auth())
        assert response.status_code == 200
        to_destroy_ids = {t["env_id"] for t in response.json()["to_destroy"]}
        assert str(env.id) not in to_destroy_ids

        db_session.refresh(env)
        assert env.status == "PAUSED"

    # --- Sweep 4: pause-expiring-soon warning (one-time) ---

    def test_paused_nearing_destroy_sets_warning_timestamp(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        soon = datetime.now(timezone.utc) + timedelta(hours=10)  # within the 48h window
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="PAUSED",
            paused_at=datetime.now(timezone.utc) - timedelta(days=6),
            pause_expires_at=soon,
        )
        assert env.pause_expiry_warning_sent_at is None

        response = client.post("/environments/process-ttl", headers=_callback_auth())
        assert response.status_code == 200

        db_session.refresh(env)
        assert env.pause_expiry_warning_sent_at is not None
        assert env.status == "PAUSED"  # the warning alone doesn't change status

    def test_warning_only_fires_once_across_multiple_cron_passes(
        self, client: TestClient, member_user, test_team, make_environment, db_session,
    ):
        """Without pause_expiry_warning_sent_at gating this, a 48h window
        at a 15-minute cron interval would send ~192 duplicate warnings."""
        soon = datetime.now(timezone.utc) + timedelta(hours=10)
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="PAUSED",
            paused_at=datetime.now(timezone.utc) - timedelta(days=6),
            pause_expires_at=soon,
        )

        client.post("/environments/process-ttl", headers=_callback_auth())
        db_session.refresh(env)
        first_sent_at = env.pause_expiry_warning_sent_at
        assert first_sent_at is not None

        client.post("/environments/process-ttl", headers=_callback_auth())
        db_session.refresh(env)
        assert env.pause_expiry_warning_sent_at == first_sent_at  # unchanged — not resent


class TestRunbook:
    def test_requires_auth(self, client: TestClient):
        assert client.get(f"/environments/{uuid.uuid4()}/runbook").status_code == 401

    def test_404_before_runbook_is_generated(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PROVISIONING")
        response = client.get(f"/environments/{env.id}/runbook", headers=_auth(member_token))
        assert response.status_code == 404

    def test_returns_markdown_after_running_callback(
        self, client: TestClient, member_user, member_token, test_team, make_environment,
    ):
        env = make_environment(team_id=test_team.id, created_by=member_user.id, status="PROVISIONING")
        client.post(
            f"/environments/{env.id}/callback",
            json={"status": "RUNNING", "outputs": {"rds_endpoint": "db.example.com"}},
            headers=_callback_auth(),
        )
        response = client.get(f"/environments/{env.id}/runbook", headers=_auth(member_token))
        assert response.status_code == 200
        assert "db.example.com" in response.json()["content_md"]

    def test_cross_team_runbook_access_is_forbidden(
        self, client: TestClient, member_token, super_admin_token, db_session, make_environment,
    ):
        other_team_id = _make_other_team(client, super_admin_token, db_session)
        owner = _make_other_team_owner(db_session, uuid.UUID(other_team_id))
        env = make_environment(
            team_id=uuid.UUID(other_team_id), created_by=owner.id, status="RUNNING"
        )

        response = client.get(f"/environments/{env.id}/runbook", headers=_auth(member_token))
        assert response.status_code == 403