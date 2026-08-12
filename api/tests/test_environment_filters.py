"""
Environment List Filtering Integration Tests

Covers the query params added to GET /environments (see routers/environments.py's
module docstring): status, team_id, env_type, health_status,
expiring_within_hours, include_destroyed, created_by_me, sort_by/sort_dir —
plus the "DESTROYED excluded by default" behavior change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_destroyed_excluded_by_default(client, member_token, test_team, member_user, make_environment):
    running = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    destroyed = make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYED")

    resp = client.get("/environments/", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(running.id) in ids
    assert str(destroyed.id) not in ids


def test_include_destroyed_true_returns_destroyed_too(
    client, member_token, test_team, member_user, make_environment
):
    destroyed = make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYED")

    resp = client.get("/environments/?include_destroyed=true", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(destroyed.id) in ids


def test_explicit_status_filter_overrides_default_exclusion(
    client, member_token, test_team, member_user, make_environment
):
    destroyed = make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYED")
    running = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")

    resp = client.get("/environments/?status=DESTROYED", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(destroyed.id) in ids
    assert str(running.id) not in ids


def test_multiple_status_values(client, member_token, test_team, member_user, make_environment):
    running = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    failed = make_environment(team_id=test_team.id, created_by=member_user.id, status="FAILED")
    make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYED")

    resp = client.get("/environments/?status=RUNNING&status=FAILED", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert ids == {str(running.id), str(failed.id)}


def test_invalid_status_value_is_422(client, member_token):
    resp = client.get("/environments/?status=NOT_A_REAL_STATUS", headers=_auth(member_token))
    assert resp.status_code == 422


def test_env_type_filter(client, member_token, test_team, member_user, make_environment):
    dev_env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING", env_type="dev")
    staging_env = make_environment(
        team_id=test_team.id, created_by=member_user.id, status="RUNNING", env_type="staging"
    )

    resp = client.get("/environments/?env_type=staging", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(staging_env.id) in ids
    assert str(dev_env.id) not in ids


def test_expiring_within_hours_filter(client, member_token, test_team, member_user, make_environment):
    soon = make_environment(
        team_id=test_team.id,
        created_by=member_user.id,
        status="RUNNING",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    later = make_environment(
        team_id=test_team.id,
        created_by=member_user.id,
        status="RUNNING",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=100),
    )

    resp = client.get("/environments/?expiring_within_hours=4", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(soon.id) in ids
    assert str(later.id) not in ids


def test_created_by_me_filter(client, member_token, member_user, team_admin_user, test_team, make_environment):
    mine = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    theirs = make_environment(team_id=test_team.id, created_by=team_admin_user.id, status="RUNNING")

    resp = client.get("/environments/?created_by_me=true", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(mine.id) in ids
    assert str(theirs.id) not in ids


def test_non_super_admin_team_id_param_is_ignored(
    client, member_token, test_team, member_user, make_environment, db_session
):
    """A member passing team_id should still only see their own team's envs —
    the param only has an effect for super_admin."""
    mine = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")

    resp = client.get(f"/environments/?team_id={test_team.id}", headers=_auth(member_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(mine.id) in ids


def test_super_admin_team_id_filter_scopes_results(
    client, super_admin_token, test_team, member_user, make_environment, db_session
):
    from app.models.team import Team

    other_team = Team(name="Other Filter Team", slug="other-filter-team")
    db_session.add(other_team)
    db_session.commit()
    db_session.refresh(other_team)
    db_session.track_team(other_team)

    in_team = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    other_env = make_environment(team_id=other_team.id, created_by=member_user.id, status="RUNNING")

    resp = client.get(f"/environments/?team_id={test_team.id}", headers=_auth(super_admin_token))
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert str(in_team.id) in ids
    assert str(other_env.id) not in ids


def test_sort_by_cost_ascending(client, member_token, test_team, member_user, make_environment, db_session):
    cheap = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    cheap.cost_estimate_usd = 10
    pricey = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    pricey.cost_estimate_usd = 90
    db_session.commit()

    resp = client.get(
        "/environments/?sort_by=cost_estimate_usd&sort_dir=asc", headers=_auth(member_token)
    )
    assert resp.status_code == 200
    ids_in_order = [e["id"] for e in resp.json()]
    assert ids_in_order.index(str(cheap.id)) < ids_in_order.index(str(pricey.id))


def test_invalid_sort_by_is_422(client, member_token):
    resp = client.get("/environments/?sort_by=not_a_column", headers=_auth(member_token))
    assert resp.status_code == 422