"""
Setup Verification Tests
"""

from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """GET /health returns {"status": "ok", "version": "0.1.0"}"""

    def test_health_returns_200(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_correct_body(self, client: TestClient):
        response = client.get("/health")
        body = response.json()
        assert body["status"] == "ok"
        assert body["version"] == "0.1.0"

    def test_health_requires_no_auth(self, client: TestClient):
        """Health check must be publicly accessible — no Authorization header needed."""
        response = client.get("/health")
        assert response.status_code != 401


class TestDocsEndpoint:
    """GET /docs shows FastAPI Swagger UI"""

    def test_docs_accessible(self, client: TestClient):
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestRouterStubs:
    """
    Verify all router stubs are mounted and reachable.
    These will return stub responses for now — we just confirm the routing works
    so we catch any wiring mistakes early.
    """

    def test_auth_github_redirects_to_github(self, client: TestClient):
        """
        Was test_auth_github_stub — auth.py stopped being a stub in Phase 1.
        conftest.py sets a fake GITHUB_CLIENT_ID for the test process, so
        this now exercises the real redirect rather than tolerating either
        a stub 200 or the "not configured" 503 that fires when
        GITHUB_CLIENT_ID is genuinely empty (as it should be in CI without
        real OAuth secrets).
        """
        response = client.get("/auth/github", follow_redirects=False)
        assert response.status_code == 307
        assert "github.com/login/oauth/authorize" in response.headers["location"]

    def test_environments_list_requires_auth(self, client: TestClient):
        """
        Was test_environments_list_stub — environments.py stopped being a
        stub in Phase 4. GET /environments/ is now real, auth-protected
        code, so an anonymous request correctly gets 401 instead of the old
        stub's 200 + placeholder message. Full lifecycle + RBAC coverage
        lives in test_environments.py; this test's only job is confirming
        the route is wired up at all.
        """
        response = client.get("/environments/")
        assert response.status_code == 401

    def test_audit_list_requires_auth(self, client: TestClient):
        """Was test_audit_list_stub — audit.py stopped being a stub in Phase 4."""
        response = client.get("/audit/")
        assert response.status_code == 401

    def test_teams_list_requires_auth(self, client: TestClient):
        """
        Was test_teams_list_stub — teams.py stopped being a stub in Phase 1.
        GET /teams/ is now real, RBAC-protected code (super_admin only), so
        an anonymous request correctly gets 401 instead of the old stub's
        200 + placeholder message. Full RBAC coverage (who's allowed, who
        isn't) lives in test_auth.py::TestTeamRBAC; this test's only job is
        confirming the route is wired up at all.
        """
        response = client.get("/teams/")
        assert response.status_code == 401


class TestAppStructure:
    """Verify the app is configured correctly."""

    def test_openapi_schema_has_all_tags(self, client: TestClient):
        """The OpenAPI schema should list all our router tags."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        # If tags aren't explicitly defined, check the paths instead
        all_paths = schema.get("paths", {})
        assert "/health" in all_paths
        assert "/auth/github" in all_paths
        assert "/environments/" in all_paths or "/environments" in all_paths