"""
Auth & RBAC Integration Tests

Covers:
  - protected routes reject missing/invalid credentials
  - JWT auth and API-key auth both resolve to the correct user
  - API key generation issues a working key
  - RBAC is enforced per-role on team + role-management endpoints
"""

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient


class TestAuthRequired:
    def test_protected_route_without_credentials_returns_401(self, client: TestClient):
        response = client.get("/teams/")
        assert response.status_code == 401

    def test_me_without_credentials_returns_401(self, client: TestClient):
        response = client.get("/auth/me")
        assert response.status_code == 401


class TestJWTAuth:
    def test_me_with_valid_jwt_returns_profile(self, client: TestClient, member_user, member_token):
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {member_token}"})
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(member_user.id)
        assert body["username"] == member_user.username
        # "role" no longer exists as a flat field — member_user's platform
        # role is the ordinary 'user' (not a super_admin), and their
        # team-scoped 'member' role shows up in team_memberships instead.
        assert body["platform_role"] == "user"
        assert len(body["team_memberships"]) == 1
        assert body["team_memberships"][0]["role"] == "member"

    def test_me_with_garbage_jwt_returns_401(self, client: TestClient):
        response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
        assert response.status_code == 401


class TestAPIKeyAuth:
    def test_me_with_valid_api_key_returns_profile(self, client: TestClient, user_with_api_key):
        response = client.get("/auth/me", headers={"X-API-Key": user_with_api_key.raw_key})
        assert response.status_code == 200
        assert response.json()["id"] == str(user_with_api_key.id)

    def test_me_with_wrong_api_key_returns_401(self, client: TestClient, user_with_api_key):
        response = client.get("/auth/me", headers={"X-API-Key": "idplite_wrong_key"})
        assert response.status_code == 401


class TestGenerateAPIKey:
    def test_generate_api_key_returns_plaintext_once(self, client: TestClient, member_token):
        response = client.post("/auth/api-key", headers={"Authorization": f"Bearer {member_token}"})
        assert response.status_code == 200
        body = response.json()
        assert body["api_key"].startswith("idplite_")

    def test_newly_generated_key_authenticates(self, client: TestClient, member_token):
        gen = client.post("/auth/api-key", headers={"Authorization": f"Bearer {member_token}"})
        new_key = gen.json()["api_key"]
        response = client.get("/auth/me", headers={"X-API-Key": new_key})
        assert response.status_code == 200

    def test_generate_api_key_requires_auth(self, client: TestClient):
        response = client.post("/auth/api-key")
        assert response.status_code == 401


class TestTeamRBAC:

    def test_super_admin_can_create_team(self, client: TestClient, super_admin_token, db_session):
        slug = f"new-team-{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/teams/",
            json={"name": f"New Team {slug}", "slug": slug},
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 201
        assert response.json()["slug"] == slug
        # This test creates a team through the live API rather than the
        # test_team fixture, so it has to register it for cleanup itself —
        # otherwise it leaks a row into the DB on every local test run.
        db_session.track_team(SimpleNamespace(id=uuid.UUID(response.json()["id"])))

    def test_duplicate_team_slug_is_rejected(self, client: TestClient, super_admin_token, test_team):
        response = client.post(
            "/teams/",
            json={"name": "Different Name", "slug": test_team.slug},
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 409

    def test_member_cannot_add_team_members(self, client: TestClient, member_token, test_team):
        response = client.post(
            f"/teams/{test_team.id}/members",
            json={"github_username": "someone", "role": "member"},
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert response.status_code == 403

    def test_team_admin_cannot_add_member_to_other_team(
        self, client: TestClient, team_admin_token, super_admin_token, db_session
    ):
        other_slug = f"other-team-{uuid.uuid4().hex[:8]}"
        other = client.post(
            "/teams/",
            json={"name": f"Other {other_slug}", "slug": other_slug},
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        other_team_id = other.json()["id"]
        db_session.track_team(SimpleNamespace(id=uuid.UUID(other_team_id)))

        response = client.post(
            f"/teams/{other_team_id}/members",
            json={"github_username": "someone", "role": "member"},
            headers={"Authorization": f"Bearer {team_admin_token}"},
        )
        assert response.status_code == 403

    
    def test_add_member_for_unknown_username_returns_404(
        self, client: TestClient, team_admin_token, test_team
    ):
        response = client.post(
            f"/teams/{test_team.id}/members",
            json={"github_username": "no-such-user-exists", "role": "member"},
            headers={"Authorization": f"Bearer {team_admin_token}"},
        )
        assert response.status_code == 404


class TestUserRoleRBAC:
    """
    PATCH /users/{id}/role is platform-scoped only — see routers/users.py's
    module docstring. ChangeRoleRequest is validated against PLATFORM_ROLES
    ({"user", "super_admin"}), NOT the team-scoped TEAM_ROLES — "team_admin"
    is not a meaningful value here anymore, since it's exclusively a
    TeamMembership concept now. These tests promote to "super_admin", the
    only non-trivial platform role change left.
    """

    def test_only_super_admin_can_change_role(self, client: TestClient, team_admin_token, member_user):
        response = client.patch(
            f"/users/{member_user.id}/role",
            json={"role": "super_admin"},
            headers={"Authorization": f"Bearer {team_admin_token}"},
        )
        assert response.status_code == 403

    def test_super_admin_can_change_role(self, client: TestClient, super_admin_token, member_user):
        response = client.patch(
            f"/users/{member_user.id}/role",
            json={"role": "super_admin"},
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["platform_role"] == "super_admin"

    def test_change_role_for_unknown_user_returns_404(self, client: TestClient, super_admin_token):
        response = client.patch(
            f"/users/{uuid.uuid4()}/role",
            json={"role": "super_admin"},
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 404

    def test_change_role_rejects_invalid_role_value(self, client: TestClient, super_admin_token, member_user):
        response = client.patch(
            f"/users/{member_user.id}/role",
            json={"role": "wizard"},
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 422

    def test_change_role_rejects_team_admin_as_a_platform_role(
        self, client: TestClient, super_admin_token, member_user
    ):
        """'team_admin' is a valid TEAM_ROLES value but NOT a valid
        PLATFORM_ROLES value — this endpoint must reject it, since it would
        otherwise be meaningless (platform_role has no concept of which team)."""
        response = client.patch(
            f"/users/{member_user.id}/role",
            json={"role": "team_admin"},
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 422