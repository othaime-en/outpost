"""
Platform Settings Integration Tests

Covers routers/settings.py: GET /settings (any authenticated user) and
PATCH /settings/ttl-enforcement (super_admin only). The process_ttl()
early-return when enforcement is disabled is tested alongside the rest of
TestProcessTTL in test_environments.py, not here — that behavior belongs
to environments.py's test class, not this one.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.platform_settings import PlatformSettings


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestGetSettings:
    def test_requires_auth(self, client: TestClient):
        assert client.get("/settings/").status_code == 401

    def test_seeded_default_is_enabled(self, client: TestClient, member_token: str):
        """The migration seeds ttl_enforcement_enabled=true — any
        authenticated user (not just super_admin) can read it."""
        response = client.get("/settings/", headers=_auth(member_token))
        assert response.status_code == 200
        body = response.json()
        assert body["ttl_enforcement_enabled"] is True

    def test_readable_by_plain_member_not_just_super_admin(self, client: TestClient, member_token: str):
        """Read access is platform-wide, not team-scoped and not
        super_admin-gated — see routers/settings.py's module docstring."""
        response = client.get("/settings/", headers=_auth(member_token))
        assert response.status_code == 200


class TestToggleTTLEnforcement:
    def test_requires_auth(self, client: TestClient):
        assert client.patch("/settings/ttl-enforcement", json={"enabled": False}).status_code == 401

    def test_non_super_admin_is_rejected(self, client: TestClient, member_token: str):
        response = client.patch(
            "/settings/ttl-enforcement", json={"enabled": False}, headers=_auth(member_token)
        )
        assert response.status_code == 403

    def test_team_admin_is_rejected(self, client: TestClient, team_admin_token: str):
        """team_admin is a TEAM-scoped role — it grants nothing here. Only
        User.platform_role == 'super_admin' passes require_super_admin."""
        response = client.patch(
            "/settings/ttl-enforcement", json={"enabled": False}, headers=_auth(team_admin_token)
        )
        assert response.status_code == 403

    def test_super_admin_can_disable(
        self, client: TestClient, super_admin_token: str, super_admin_user, db_session
    ):
        response = client.patch(
            "/settings/ttl-enforcement", json={"enabled": False}, headers=_auth(super_admin_token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ttl_enforcement_enabled"] is False
        assert body["updated_by_username"] == super_admin_user.username
        assert body["updated_at"] is not None

        row = db_session.query(PlatformSettings).filter(PlatformSettings.key == "ttl_enforcement_enabled").first()
        assert row.value is False
        assert row.updated_by_id == super_admin_user.id

    def test_toggle_writes_audit_log_in_same_transaction(
        self, client: TestClient, super_admin_token: str, super_admin_user, db_session
    ):
        response = client.patch(
            "/settings/ttl-enforcement", json={"enabled": False}, headers=_auth(super_admin_token)
        )
        assert response.status_code == 200

        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "TTL_ENFORCEMENT_TOGGLED", AuditLog.actor_id == super_admin_user.id)
            .first()
        )
        assert audit is not None
        assert audit.actor_type == "user"
        assert audit.environment_id is None
        assert audit.event_metadata["enabled"] is False
        assert audit.event_metadata["previous"] is True

    def test_toggle_persists_across_requests(
        self, client: TestClient, super_admin_token: str
    ):
        off = client.patch(
            "/settings/ttl-enforcement", json={"enabled": False}, headers=_auth(super_admin_token)
        )
        assert off.json()["ttl_enforcement_enabled"] is False

        read_back = client.get("/settings/", headers=_auth(super_admin_token))
        assert read_back.json()["ttl_enforcement_enabled"] is False

        on = client.patch(
            "/settings/ttl-enforcement", json={"enabled": True}, headers=_auth(super_admin_token)
        )
        assert on.json()["ttl_enforcement_enabled"] is True

    def test_toggle_off_then_on_records_previous_correctly(
        self, client: TestClient, super_admin_token: str, super_admin_user, db_session
    ):
        client.patch("/settings/ttl-enforcement", json={"enabled": False}, headers=_auth(super_admin_token))
        client.patch("/settings/ttl-enforcement", json={"enabled": True}, headers=_auth(super_admin_token))

        audits = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "TTL_ENFORCEMENT_TOGGLED", AuditLog.actor_id == super_admin_user.id)
            .order_by(AuditLog.created_at.asc())
            .all()
        )
        assert len(audits) == 2
        assert audits[0].event_metadata == {"enabled": False, "previous": True}
        assert audits[1].event_metadata == {"enabled": True, "previous": False}