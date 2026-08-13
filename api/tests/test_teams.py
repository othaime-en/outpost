"""
Teams Integration Tests

Covers the RBAC rewrite documented in routers/teams.py's module docstring:
role-scoped GET /teams and GET /teams/{id}, self-serve POST /teams (with the
"already on a team" 400 edge case), and read-only member visibility on
GET /teams/{id}/members.
"""

from __future__ import annotations

import uuid


from app.models.team import Team
from app.models.user import User


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- POST /teams — self-serve creation -------------------------------------


def test_teamless_member_can_self_serve_create_team(client, member_without_team_token, db_session):
    resp = client.post(
        "/teams/",
        json={"name": f"Backend Guild {uuid.uuid4().hex[:6]}", "slug": f"backend-guild-{uuid.uuid4().hex[:6]}"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 201
    team_id = resp.json()["id"]
    db_session.track_team(Team(id=uuid.UUID(team_id)))  # register for teardown


def test_self_serve_creation_promotes_creator_to_team_admin(
    client, member_without_team_user, member_without_team_token, db_session
):
    resp = client.post(
        "/teams/",
        json={"name": f"Ops Guild {uuid.uuid4().hex[:6]}", "slug": f"ops-guild-{uuid.uuid4().hex[:6]}"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 201
    team_id = resp.json()["id"]
    db_session.track_team(Team(id=uuid.UUID(team_id)))

    db_session.refresh(member_without_team_user)
    assert member_without_team_user.role == "team_admin"
    assert str(member_without_team_user.team_id) == team_id


def test_user_already_on_a_team_cannot_self_serve_create(client, member_token):
    resp = client.post(
        "/teams/",
        json={"name": f"Another Team {uuid.uuid4().hex[:6]}", "slug": f"another-team-{uuid.uuid4().hex[:6]}"},
        headers=_auth(member_token),
    )
    assert resp.status_code == 400


def test_super_admin_creating_team_keeps_super_admin_role(
    client, super_admin_user, super_admin_token, db_session
):
    resp = client.post(
        "/teams/",
        json={"name": f"Admin Team {uuid.uuid4().hex[:6]}", "slug": f"admin-team-{uuid.uuid4().hex[:6]}"},
        headers=_auth(super_admin_token),
    )
    assert resp.status_code == 201
    team_id = resp.json()["id"]
    db_session.track_team(Team(id=uuid.UUID(team_id)))

    db_session.refresh(super_admin_user)
    assert super_admin_user.role == "super_admin"


def test_duplicate_team_name_or_slug_is_rejected(client, member_without_team_token, test_team):
    resp = client.post(
        "/teams/",
        json={"name": test_team.name, "slug": f"different-slug-{uuid.uuid4().hex[:6]}"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 409


# --- GET /teams — role-scoped listing --------------------------------------


def test_member_lists_only_own_team(client, member_token, test_team):
    resp = client.get("/teams/", headers=_auth(member_token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(test_team.id)


def test_teamless_member_lists_no_teams(client, member_without_team_token):
    resp = client.get("/teams/", headers=_auth(member_without_team_token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_super_admin_lists_all_teams(client, super_admin_token, test_team):
    resp = client.get("/teams/", headers=_auth(super_admin_token))
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()}
    assert str(test_team.id) in ids


# --- GET /teams/{id} — detail endpoint --------------------------------------


def test_member_can_view_own_team_detail(client, member_token, test_team, member_user):
    resp = client.get(f"/teams/{test_team.id}", headers=_auth(member_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(test_team.id)
    assert body["slug"] == test_team.slug
    assert any(m["id"] == str(member_user.id) for m in body["members"])
    assert "active_environment_count" in body
    assert "estimated_monthly_cost_usd" in body


def test_member_cannot_view_other_team_detail(client, member_token, db_session):
    other_team = Team(name=f"Other Team {uuid.uuid4().hex[:6]}", slug=f"other-team-{uuid.uuid4().hex[:6]}")
    db_session.add(other_team)
    db_session.commit()
    db_session.refresh(other_team)
    db_session.track_team(other_team)

    resp = client.get(f"/teams/{other_team.id}", headers=_auth(member_token))
    assert resp.status_code == 403


def test_super_admin_can_view_any_team_detail(client, super_admin_token, test_team):
    resp = client.get(f"/teams/{test_team.id}", headers=_auth(super_admin_token))
    assert resp.status_code == 200


def test_team_detail_includes_environments(client, member_token, test_team, member_user, make_environment):
    env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    resp = client.get(f"/teams/{test_team.id}", headers=_auth(member_token))
    assert resp.status_code == 200
    env_ids = {e["id"] for e in resp.json()["environments"]}
    assert str(env.id) in env_ids


def test_team_detail_404_for_unknown_team(client, member_token):
    resp = client.get(f"/teams/{uuid.uuid4()}", headers=_auth(member_token))
    assert resp.status_code == 404


# --- GET /teams/{id}/members — now read-only for plain members -------------


def test_plain_member_can_list_own_team_members(client, member_token, test_team, member_user):
    resp = client.get(f"/teams/{test_team.id}/members", headers=_auth(member_token))
    assert resp.status_code == 200
    usernames = {m["username"] for m in resp.json()}
    assert member_user.username in usernames


def test_member_cannot_list_other_teams_members(client, member_token, db_session):
    other_team = Team(name=f"Other Team {uuid.uuid4().hex[:6]}", slug=f"other-team-{uuid.uuid4().hex[:6]}")
    db_session.add(other_team)
    db_session.commit()
    db_session.refresh(other_team)
    db_session.track_team(other_team)

    resp = client.get(f"/teams/{other_team.id}/members", headers=_auth(member_token))
    assert resp.status_code == 403


# --- POST /teams/{id}/members — unchanged, still team_admin+ ---------------


def test_plain_member_cannot_add_team_member(client, member_token, test_team):
    resp = client.post(
        f"/teams/{test_team.id}/members",
        json={"github_username": "octocat", "role": "member"},
        headers=_auth(member_token),
    )
    assert resp.status_code == 403


def test_team_admin_can_add_member_to_own_team(client, team_admin_token, test_team, db_session):
    new_user = User(
        github_id=uuid.uuid4().int % (2**62),
        username=f"invitee-{uuid.uuid4().hex[:8]}",
        email=None,
        role="member",
        team_id=None,
    )
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)
    db_session.track_user(new_user)

    resp = client.post(
        f"/teams/{test_team.id}/members",
        json={"github_username": new_user.username, "role": "member"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["team_id"] == str(test_team.id)


# --- PATCH /teams/{id}/members/{user_id}/role — promote/demote existing member ---


def test_team_admin_can_promote_member_to_team_admin(
    client, team_admin_token, test_team, member_user
):
    resp = client.patch(
        f"/teams/{test_team.id}/members/{member_user.id}/role",
        json={"role": "team_admin"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "team_admin"


def test_team_admin_cannot_grant_super_admin(client, team_admin_token, test_team, member_user):
    resp = client.patch(
        f"/teams/{test_team.id}/members/{member_user.id}/role",
        json={"role": "super_admin"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 403


def test_cannot_demote_the_last_team_admin(client, team_admin_token, test_team, team_admin_user):
    resp = client.patch(
        f"/teams/{test_team.id}/members/{team_admin_user.id}/role",
        json={"role": "member"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 400


def test_demoting_non_last_team_admin_succeeds(
    client, team_admin_token, test_team, team_admin_user, member_user, db_session
):
    # Promote member_user to team_admin first, so team_admin_user is no
    # longer the *last* one and can safely be demoted.
    member_user.role = "team_admin"
    db_session.commit()

    resp = client.patch(
        f"/teams/{test_team.id}/members/{team_admin_user.id}/role",
        json={"role": "member"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "member"


def test_plain_member_cannot_change_roles(client, member_token, test_team, member_user):
    resp = client.patch(
        f"/teams/{test_team.id}/members/{member_user.id}/role",
        json={"role": "team_admin"},
        headers=_auth(member_token),
    )
    assert resp.status_code == 403


# --- DELETE /teams/{id}/members/{user_id} — self-serve or forced removal ---


def test_member_can_remove_self(client, member_token, member_user, test_team, db_session):
    resp = client.delete(f"/teams/{test_team.id}/members/{member_user.id}", headers=_auth(member_token))
    assert resp.status_code == 200
    db_session.refresh(member_user)
    assert member_user.team_id is None
    assert member_user.role == "member"


def test_team_admin_can_forcibly_remove_another_member(
    client, team_admin_token, member_user, test_team, db_session
):
    resp = client.delete(f"/teams/{test_team.id}/members/{member_user.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 200
    db_session.refresh(member_user)
    assert member_user.team_id is None


def test_member_cannot_remove_someone_else(client, member_token, team_admin_user, test_team):
    resp = client.delete(
        f"/teams/{test_team.id}/members/{team_admin_user.id}", headers=_auth(member_token)
    )
    assert resp.status_code == 403


def test_cannot_remove_the_last_team_admin(client, team_admin_token, team_admin_user, test_team):
    resp = client.delete(
        f"/teams/{test_team.id}/members/{team_admin_user.id}", headers=_auth(team_admin_token)
    )
    assert resp.status_code == 400


def test_last_team_admin_can_leave_after_promoting_a_peer(
    client, team_admin_token, team_admin_user, member_user, test_team, db_session
):
    member_user.role = "team_admin"
    db_session.commit()

    resp = client.delete(
        f"/teams/{test_team.id}/members/{team_admin_user.id}", headers=_auth(team_admin_token)
    )
    assert resp.status_code == 200
    db_session.refresh(team_admin_user)
    assert team_admin_user.team_id is None


# --- DELETE /teams/{id} — blocked on non-destroyed environments, auto-detaches members ---


def test_delete_team_blocked_by_non_destroyed_environment(
    client, team_admin_token, test_team, member_user, make_environment
):
    make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    resp = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 400


def test_delete_team_blocked_by_failed_environment(
    client, team_admin_token, test_team, member_user, make_environment
):
    """FAILED environments block deletion too — they can have
    partially-provisioned resources needing manual resolution first."""
    make_environment(team_id=test_team.id, created_by=member_user.id, status="FAILED")
    resp = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 400


def test_delete_team_succeeds_when_all_environments_destroyed(
    client, team_admin_token, team_admin_user, test_team, member_user, make_environment, db_session
):
    make_environment(team_id=test_team.id, created_by=member_user.id, status="DESTROYED")

    resp = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert member_user.username in body["detached_members"]
    assert team_admin_user.username in body["detached_members"]

    db_session.refresh(member_user)
    db_session.refresh(team_admin_user)
    assert member_user.team_id is None
    assert team_admin_user.team_id is None

    # Team row persists (soft delete — see the Team model's docstring for
    # why a hard delete isn't possible once a team has any environment
    # history), but is marked deleted and excluded from normal lookups.
    from app.models.team import Team as TeamModel

    deleted_team = db_session.query(TeamModel).filter(TeamModel.id == test_team.id).first()
    assert deleted_team is not None
    assert deleted_team.deleted_at is not None

    get_resp = client.get(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert get_resp.status_code == 404


def test_delete_team_succeeds_with_no_environments_at_all(
    client, team_admin_token, test_team
):
    resp = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 200


def test_team_admin_cannot_delete_other_teams(client, team_admin_token, db_session):
    other_team = Team(name=f"Other Delete Team {uuid.uuid4().hex[:6]}", slug=f"other-delete-{uuid.uuid4().hex[:6]}")
    db_session.add(other_team)
    db_session.commit()
    db_session.refresh(other_team)
    db_session.track_team(other_team)

    resp = client.delete(f"/teams/{other_team.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 403


def test_super_admin_can_delete_any_team(client, super_admin_token, test_team):
    resp = client.delete(f"/teams/{test_team.id}", headers=_auth(super_admin_token))
    assert resp.status_code == 200


def test_plain_member_cannot_delete_team(client, member_token, test_team):
    resp = client.delete(f"/teams/{test_team.id}", headers=_auth(member_token))
    assert resp.status_code == 403


# --- Hotfix: team-scoped role writes must never touch a super_admin -------
# Regression coverage for a real bug: adding an existing super_admin to a
# team (or editing their team role afterward) silently overwrote their
# platform-wide role, permanently downgrading them. Both endpoints must
# refuse outright rather than merely "protect" the value.


def test_add_member_cannot_downgrade_a_super_admin(
    client, team_admin_token, test_team, super_admin_user, db_session
):
    resp = client.post(
        f"/teams/{test_team.id}/members",
        json={"github_username": super_admin_user.username, "role": "member"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 403

    db_session.refresh(super_admin_user)
    assert super_admin_user.role == "super_admin"
    assert super_admin_user.team_id is None


def test_update_member_role_cannot_downgrade_a_super_admin(
    client, team_admin_token, test_team, super_admin_user, db_session
):
    # Simulate a super_admin who already has a team_id set (e.g. from
    # before this hotfix, or added directly in the DB) to confirm the
    # endpoint itself still refuses to touch their role.
    super_admin_user.team_id = test_team.id
    db_session.commit()

    resp = client.patch(
        f"/teams/{test_team.id}/members/{super_admin_user.id}/role",
        json={"role": "member"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 403

    db_session.refresh(super_admin_user)
    assert super_admin_user.role == "super_admin"