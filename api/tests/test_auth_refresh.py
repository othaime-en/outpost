"""
Refresh Token Flow Tests

Covers:
  - POST /auth/refresh: missing/garbage/expired/revoked cookie -> 401 +
    cookie cleared; valid cookie -> new access token + rotated cookie
  - Rotation: the old token stops working after one use
  - Reuse detection: presenting an already-rotated-away token revokes
    every active refresh token that user has
  - POST /auth/logout: revokes + clears the cookie, idempotent
  - GET /auth/github/callback sets the refresh cookie on login (OAuth
    exchange itself is mocked — this project has no live GitHub App to
    test against, same reasoning as test_environments.py mocking
    terraform.trigger_provision rather than hitting real GitHub Actions)

These seed RefreshToken rows directly via services.refresh_tokens.issue()
rather than going through the OAuth flow for most cases — faster, and
keeps "does rotation/reuse-detection work" independent from "does the
OAuth exchange work," which is covered separately by the callback tests
below.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.refresh_token import RefreshToken
from app.services import refresh_tokens


@pytest.fixture
def issued_refresh_token(db_session, member_user):
    """A real, active refresh token for member_user, via the actual
    issuance path — returns the RAW token, exactly what a cookie would
    hold. Cleanup is automatic: refresh_tokens.user_id cascades on
    member_user's deletion in db_session's teardown (see
    models/refresh_token.py's module docstring for why that cascade is
    the deliberate, correct choice here, unlike audit_logs)."""
    return refresh_tokens.issue(db_session, member_user)


def _cookie_jar(raw_token: str) -> dict:
    from app.config import settings

    return {settings.refresh_cookie_name: raw_token}


class TestRefreshEndpoint:
    def test_refresh_without_cookie_returns_401(self, client):
        resp = client.post("/auth/refresh")
        assert resp.status_code == 401

    def test_refresh_with_garbage_cookie_returns_401_and_clears_it(self, client):
        from app.config import settings

        resp = client.post("/auth/refresh", cookies={settings.refresh_cookie_name: "not-a-real-token"})
        assert resp.status_code == 401
        # A 401 response clearing a cookie that was never validly set is a
        # no-op from the browser's point of view, but the response must
        # still carry the clearing Set-Cookie header — that's what proves
        # _refresh_failure() (not a bare `raise HTTPException`) is what
        # actually ran. See routers/auth.py's docstring on that function
        # for why the distinction matters.
        assert "set-cookie" in resp.headers
        assert settings.refresh_cookie_name in resp.headers["set-cookie"]

    def test_refresh_with_valid_cookie_returns_new_access_token(self, client, issued_refresh_token, member_user):
        resp = client.post("/auth/refresh", cookies=_cookie_jar(issued_refresh_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20

        # The new access token actually authenticates as member_user.
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["id"] == str(member_user.id)

    def test_refresh_rotates_the_cookie(self, client, issued_refresh_token):
        from app.config import settings

        resp = client.post("/auth/refresh", cookies=_cookie_jar(issued_refresh_token))
        assert resp.status_code == 200
        set_cookie_header = resp.headers.get("set-cookie", "")
        assert settings.refresh_cookie_name in set_cookie_header
        # The rotated value must not be the same raw token that came in —
        # that's the entire point of rotation-on-use.
        assert f"={issued_refresh_token}" not in set_cookie_header

    def test_old_token_is_rejected_after_rotation(self, client, issued_refresh_token):
        first = client.post("/auth/refresh", cookies=_cookie_jar(issued_refresh_token))
        assert first.status_code == 200

        # Reusing the SAME (now-rotated-away) raw token must fail — it's
        # been consumed, one-time-use.
        second = client.post("/auth/refresh", cookies=_cookie_jar(issued_refresh_token))
        assert second.status_code == 401

    def test_reuse_of_rotated_token_revokes_all_active_tokens_for_user(
        self, client, db_session, member_user, issued_refresh_token
    ):
        """The security-relevant case: issue a second, independent refresh
        token for the same user (simulating "logged in on two devices"),
        rotate the first one normally, then present the now-dead first
        token again — reuse. Both the reused token's session AND the
        completely unrelated second token must be dead afterward, since
        reuse is treated as a possible compromise signal for the whole
        account, not just a rejection of the one bad request."""
        second_raw_token = refresh_tokens.issue(db_session, member_user)

        first_rotation = client.post("/auth/refresh", cookies=_cookie_jar(issued_refresh_token))
        assert first_rotation.status_code == 200

        # Reuse the original (already-rotated-away) token.
        reuse_attempt = client.post("/auth/refresh", cookies=_cookie_jar(issued_refresh_token))
        assert reuse_attempt.status_code == 401

        # The unrelated second token must now be revoked too — it was
        # never itself reused, but reuse detection nukes the whole
        # account's active sessions defensively.
        second_token_attempt = client.post("/auth/refresh", cookies=_cookie_jar(second_raw_token))
        assert second_token_attempt.status_code == 401

        active_count = (
            db_session.query(RefreshToken)
            .filter(RefreshToken.user_id == member_user.id, RefreshToken.revoked_at.is_(None))
            .count()
        )
        assert active_count == 0

    def test_refresh_with_expired_token_returns_401(self, client, db_session, member_user):
        raw_token = "expired-test-token-" + uuid.uuid4().hex
        db_session.add(
            RefreshToken(
                user_id=member_user.id,
                token_hash=refresh_tokens._hash(raw_token),  # noqa: SLF001 — test-only direct construction
                created_at=datetime.now(timezone.utc) - timedelta(days=40),
                expires_at=datetime.now(timezone.utc) - timedelta(days=10),
            )
        )
        db_session.commit()

        resp = client.post("/auth/refresh", cookies=_cookie_jar(raw_token))
        assert resp.status_code == 401


class TestLogoutEndpoint:
    def test_logout_without_cookie_succeeds_idempotently(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code == 204

    def test_logout_revokes_the_token(self, client, db_session, member_user, issued_refresh_token):
        resp = client.post("/auth/logout", cookies=_cookie_jar(issued_refresh_token))
        assert resp.status_code == 204

        row = (
            db_session.query(RefreshToken)
            .filter(RefreshToken.token_hash == refresh_tokens._hash(issued_refresh_token))  # noqa: SLF001
            .first()
        )
        assert row.revoked_at is not None

        # And the now-revoked token can no longer be used to refresh.
        refresh_attempt = client.post("/auth/refresh", cookies=_cookie_jar(issued_refresh_token))
        assert refresh_attempt.status_code == 401

    def test_logout_clears_the_cookie(self, client, issued_refresh_token):
        from app.config import settings

        resp = client.post("/auth/logout", cookies=_cookie_jar(issued_refresh_token))
        assert resp.status_code == 204
        assert settings.refresh_cookie_name in resp.headers.get("set-cookie", "")

    def test_logout_twice_is_safe(self, client, issued_refresh_token):
        first = client.post("/auth/logout", cookies=_cookie_jar(issued_refresh_token))
        assert first.status_code == 204
        second = client.post("/auth/logout", cookies=_cookie_jar(issued_refresh_token))
        assert second.status_code == 204


class TestGithubCallbackSetsRefreshCookie:
    """The OAuth token exchange + profile fetch are mocked — see module
    docstring. This isolates "does the callback set a working refresh
    cookie on login" from "does the GitHub OAuth handshake work," which
    isn't something a test suite without live GitHub credentials can
    exercise anyway."""

    @pytest.fixture
    def mock_github_oauth(self, monkeypatch):
        import httpx as httpx_module

        gh_user_id = 900000 + (uuid.uuid4().int % 90000)

        class FakeResponse:
            def __init__(self, json_data, status_code=200):
                self._json = json_data
                self.status_code = status_code

            def raise_for_status(self):
                pass

            def json(self):
                return self._json

        def fake_post(url, **kwargs):
            assert "access_token" in url
            return FakeResponse({"access_token": "fake-gh-access-token"})

        def fake_get(url, **kwargs):
            assert "api.github.com/user" in url
            return FakeResponse(
                {
                    "id": gh_user_id,
                    "login": f"octocat-{gh_user_id}",
                    "email": f"octocat-{gh_user_id}@example.com",
                }
            )

        monkeypatch.setattr(httpx_module, "post", fake_post)
        monkeypatch.setattr(httpx_module, "get", fake_get)
        return gh_user_id

    def test_login_sets_refresh_cookie_and_redirects_with_jwt_fragment(
        self, client, db_session, mock_github_oauth
    ):
        from app.config import settings
        from app.models.user import User

        resp = client.get("/auth/github/callback", params={"code": "fake-code"}, follow_redirects=False)

        assert resp.status_code in (302, 307)
        assert resp.headers["location"].startswith(f"{settings.frontend_url}/callback#token=")

        assert settings.refresh_cookie_name in resp.headers.get("set-cookie", "")
        assert "HttpOnly" in resp.headers["set-cookie"]

        # Clean up the user this test just created via the live endpoint.
        created = db_session.query(User).filter(User.github_id == mock_github_oauth).first()
        assert created is not None
        db_session.track_user(created)