"""
Teams Integration Tests
"""

from __future__ import annotations

import uuid
from typing import Optional

from app.models.team import Team
from app.models.team_membership import TeamMembership
from app.models.user import User


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _membership_role(db_session, user_id, team_id) -> Optional[str]:
    """Reads a user's team-scoped role directly from team_memberships —
    the replacement for the old `user.role` attribute check."""
    m = (
        db_session.query(TeamMembership)
        .filter(TeamMembership.user_id == user_id, TeamMembership.team_id == team_id)
        .first()
    )
    return m.role if m else None


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


def test_self_serve_creation_enrolls_creator_as_team_admin(
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

    assert _membership_role(db_session, member_without_team_user.id, team_id) == "team_admin"


def test_user_already_on_a_team_can_self_serve_create_second_team(
    client, member_token, member_user, test_team, db_session
):
    resp = client.post(
        "/teams/",
        json={"name": f"Another Team {uuid.uuid4().hex[:6]}", "slug": f"another-team-{uuid.uuid4().hex[:6]}"},
        headers=_auth(member_token),
    )
    assert resp.status_code == 201
    new_team_id = resp.json()["id"]
    db_session.track_team(Team(id=uuid.UUID(new_team_id)))

    assert _membership_role(db_session, member_user.id, new_team_id) == "team_admin"
    # Original membership on test_team is untouched.
    assert _membership_role(db_session, member_user.id, test_team.id) == "member"


def test_super_admin_creating_team_keeps_super_admin_platform_role(
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
    assert super_admin_user.platform_role == "super_admin"
    # A super_admin creating a team is ALSO
    # auto-enrolled as team_admin of it, same as any other creator — the
    # membership is purely team-scoped and doesn't touch platform_role.
    assert _membership_role(db_session, super_admin_user.id, team_id) == "team_admin"


def test_duplicate_team_name_or_slug_is_rejected(client, member_without_team_token, test_team):
    resp = client.post(
        "/teams/",
        json={"name": test_team.name, "slug": f"different-slug-{uuid.uuid4().hex[:6]}"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 409


def test_name_and_slug_are_reusable_after_soft_delete(client, team_admin_token, test_team, db_session):
    """Regression test for e9c869c63ffd: a deleted team's name/slug must
    not stay reserved forever. Delete `test_team` (no environments, so
    delete_team()'s precondition is satisfied for free), then create a
    brand-new team reusing its exact name and slug — this must succeed,
    not 409."""
    name, slug = test_team.name, test_team.slug

    delete_resp = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert delete_resp.status_code == 200

    create_resp = client.post(
        "/teams/",
        json={"name": name, "slug": slug},
        headers=_auth(team_admin_token),
    )
    assert create_resp.status_code == 201
    new_team_id = create_resp.json()["id"]
    assert new_team_id != str(test_team.id)
    db_session.track_team(Team(id=uuid.UUID(new_team_id)))


def test_duplicate_check_ignores_soft_deleted_teams_even_with_different_creator(
    client, team_admin_token, member_without_team_token, test_team, db_session
):
    """Same as above, but the re-creation is done by a totally different
    user than the one who deleted the original team — makes sure the
    active-only scoping isn't accidentally keyed off the actor."""
    name, slug = test_team.name, test_team.slug

    delete_resp = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert delete_resp.status_code == 200

    create_resp = client.post(
        "/teams/",
        json={"name": name, "slug": slug},
        headers=_auth(member_without_team_token),
    )
    assert create_resp.status_code == 201
    new_team_id = create_resp.json()["id"]
    db_session.track_team(Team(id=uuid.UUID(new_team_id)))


def test_two_soft_deleted_teams_can_share_a_name(client, team_admin_token, test_team, second_team, db_session):
    """Two different teams, both later soft-deleted, ending up with the
    same name isn't just tolerated when creating one at a time (covered
    above) — it must also not violate the partial unique index directly,
    since both rows persist afterward with deleted_at set."""
    shared_name = test_team.name

    # Soft-delete test_team FIRST — renaming second_team to match while
    # test_team is still active would itself violate the (correct,
    # unrelated) active-uniqueness constraint before this test even gets
    # to the behavior it's checking.
    resp1 = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert resp1.status_code == 200

    second_team.name = shared_name
    db_session.commit()

    # second_team's team_admin is a different user than test_team's in the
    # general case, but team_admin_token belongs to test_team specifically
    # per the fixture — deleting second_team needs its own admin.
    from tests.conftest import _make_user, _make_membership, _make_token  # local import: test-only helpers

    admin2 = _make_user(db_session)
    _make_membership(db_session, user_id=admin2.id, team_id=second_team.id, role="team_admin")
    admin2_token = _make_token(admin2)

    resp2 = client.delete(f"/teams/{second_team.id}", headers=_auth(admin2_token))
    assert resp2.status_code == 200

    # Both rows now share `shared_name` and both have deleted_at set — the
    # partial index (WHERE deleted_at IS NULL) must allow this.
    active_team = db_session.query(Team).filter(Team.name == shared_name, Team.deleted_at.is_(None)).first()
    assert active_team is None


# --- POST /teams — slug auto-derivation & case-insensitive uniqueness ------


def test_slug_is_auto_generated_when_omitted(client, member_without_team_token, db_session):
    suffix = uuid.uuid4().hex[:8]
    resp = client.post(
        "/teams/",
        json={"name": f"Platform Engineering {suffix}"},  # no slug key at all
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    db_session.track_team(Team(id=uuid.UUID(body["id"])))
    assert body["slug"] == f"platform-engineering-{suffix}"
    # name is stored exactly as typed — no title-casing/normalization applied
    assert body["name"] == f"Platform Engineering {suffix}"


def test_name_is_stored_exactly_as_typed(client, member_without_team_token, db_session):
    """Explicit regression guard: Claude was asked NOT to normalize `name`
    (no forced title-casing, no lowercasing) — only `slug` gets that
    treatment. Odd but valid casing must round-trip unchanged."""
    suffix = uuid.uuid4().hex[:8]
    resp = client.post(
        "/teams/",
        json={"name": f"K8s Platform (EU) {suffix}"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    db_session.track_team(Team(id=uuid.UUID(body["id"])))
    assert body["name"] == f"K8s Platform (EU) {suffix}"
    assert body["slug"] == f"k8s-platform-eu-{suffix}"


def test_explicit_slug_overrides_derivation(client, member_without_team_token, db_session):
    suffix = uuid.uuid4().hex[:8]
    resp = client.post(
        "/teams/",
        json={"name": f"Platform Engineering {suffix}", "slug": f"plat-eng-custom-{suffix}"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    db_session.track_team(Team(id=uuid.UUID(body["id"])))
    assert body["slug"] == f"plat-eng-custom-{suffix}"


def test_explicit_slug_still_validated_for_format(client, member_without_team_token):
    resp = client.post(
        "/teams/",
        json={"name": f"Bad Slug Team {uuid.uuid4().hex[:6]}", "slug": "Not_A-Valid-Slug!"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 422


def test_slug_derivation_failure_returns_422(client, member_without_team_token):
    """A name with nothing but characters outside [a-z0-9-] can't produce
    a slug — must be a clear 422, not a 500 from a NOT NULL violation."""
    resp = client.post(
        "/teams/",
        json={"name": "🚀🚀🚀"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 422


def test_duplicate_check_is_case_insensitive_on_name(client, member_without_team_token, test_team):
    resp = client.post(
        "/teams/",
        json={"name": test_team.name.upper(), "slug": f"different-{uuid.uuid4().hex[:6]}"},
        headers=_auth(member_without_team_token),
    )
    assert resp.status_code == 409


def test_duplicate_check_is_case_insensitive_on_slug(client, member_without_team_token, test_team):
    resp = client.post(
        "/teams/",
        json={"name": f"Totally Different Name {uuid.uuid4().hex[:6]}", "slug": test_team.slug.upper()},
        headers=_auth(member_without_team_token),
    )
    # An uppercase slug fails format validation before it ever reaches the
    # duplicate check (SLUG_PATTERN requires lowercase) — so this is 422,
    # not 409. The genuinely-interesting case-insensitive-slug-collision
    # path is covered by the derived-slug variant below, since derivation
    # always produces lowercase.
    assert resp.status_code == 422


def test_duplicate_check_is_case_insensitive_on_derived_slug(client, member_without_team_token, test_team):
    """test_team's slug is whatever the fixture set it to (lowercase,
    since it went through the same validated path). A different name that
    *derives* to that same slug must still collide, even though no one
    typed the slug directly."""
    resp = client.post(
        "/teams/",
        # Punctuation-only differences collapse to the same derived slug
        # as test_team's, e.g. "Test Team" -> "test-team". We reuse
        # test_team's actual slug value here to keep this fixture-agnostic.
        json={"name": test_team.slug.replace("-", "   ")},
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


def test_user_on_two_teams_lists_both(client, user_on_two_teams_token, test_team, second_team):
    """The core new scenario multi-team membership exists for: one user,
    two teams, both visible in a single call — not just one."""
    resp = client.get("/teams/", headers=_auth(user_on_two_teams_token))
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()}
    assert {str(test_team.id), str(second_team.id)} <= ids


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


def test_user_on_two_teams_can_view_both_details(
    client, user_on_two_teams_token, test_team, second_team
):
    resp_a = client.get(f"/teams/{test_team.id}", headers=_auth(user_on_two_teams_token))
    resp_b = client.get(f"/teams/{second_team.id}", headers=_auth(user_on_two_teams_token))
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200


def test_team_detail_includes_environments(client, member_token, test_team, member_user, make_environment):
    env = make_environment(team_id=test_team.id, created_by=member_user.id, status="RUNNING")
    resp = client.get(f"/teams/{test_team.id}", headers=_auth(member_token))
    assert resp.status_code == 200
    env_ids = {e["id"] for e in resp.json()["environments"]}
    assert str(env.id) in env_ids


def test_team_detail_404_for_unknown_team(client, member_token):
    resp = client.get(f"/teams/{uuid.uuid4()}", headers=_auth(member_token))
    assert resp.status_code == 404


# --- GET /teams/{id}/members — read-only for plain members -----------------


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


def test_member_roster_reports_this_teams_role_not_platform_role(
    client, user_on_two_teams, user_on_two_teams_token, test_team, second_team
):
    """user_on_two_teams is 'member' on test_team and 'team_admin' on
    second_team — the roster for EACH team must show the role scoped to
    THAT team, not a single value copy-pasted across both."""
    resp_a = client.get(f"/teams/{test_team.id}/members", headers=_auth(user_on_two_teams_token))
    resp_b = client.get(f"/teams/{second_team.id}/members", headers=_auth(user_on_two_teams_token))

    role_on_a = next(m["team_role"] for m in resp_a.json() if m["id"] == str(user_on_two_teams.id))
    role_on_b = next(m["team_role"] for m in resp_b.json() if m["id"] == str(user_on_two_teams.id))
    assert role_on_a == "member"
    assert role_on_b == "team_admin"


# --- POST /teams/{id}/members -----------------------------------------------


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
        platform_role="user",
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
    assert resp.json()["team_role"] == "member"
    assert _membership_role(db_session, new_user.id, test_team.id) == "member"


def test_adding_the_same_member_twice_is_rejected(client, team_admin_token, test_team, member_user):
    """member_user is already on test_team (via the fixture) — re-adding
    them must 409, not silently overwrite the existing membership row."""
    resp = client.post(
        f"/teams/{test_team.id}/members",
        json={"github_username": member_user.username, "role": "team_admin"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 409


def test_team_admin_can_add_an_existing_super_admin_as_plain_member(
    client, team_admin_token, test_team, super_admin_user, db_session
):
    """
    This is the actual bug-fix regression test, positive direction: this
    operation used to be blocked with 403 to avoid corrupting the
    super_admin's (formerly shared) role column. Now that TeamMembership.role
    is structurally separate from User.platform_role, there's nothing to
    corrupt, and this is just an ordinary add.
    """
    resp = client.post(
        f"/teams/{test_team.id}/members",
        json={"github_username": super_admin_user.username, "role": "member"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["team_role"] == "member"

    db_session.refresh(super_admin_user)
    assert super_admin_user.platform_role == "super_admin"  # untouched
    assert _membership_role(db_session, super_admin_user.id, test_team.id) == "member"


def test_add_member_with_role_super_admin_is_rejected_at_schema_layer(
    client, team_admin_token, test_team
):
    """
    TEAM_ROLES = {"member", "team_admin"} — "super_admin" isn't a valid
    team-scoped role at all anymore, so this is a 422 from Pydantic
    validation, not a 403 application-level permission check. The handler
    body never even runs.
    """
    resp = client.post(
        f"/teams/{test_team.id}/members",
        json={"github_username": "octocat", "role": "super_admin"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 422


# --- PATCH /teams/{id}/members/{user_id}/role — promote/demote existing member ---


def test_team_admin_can_promote_member_to_team_admin(client, team_admin_token, test_team, member_user, db_session):
    resp = client.patch(
        f"/teams/{test_team.id}/members/{member_user.id}/role",
        json={"role": "team_admin"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["team_role"] == "team_admin"
    assert _membership_role(db_session, member_user.id, test_team.id) == "team_admin"


def test_update_member_role_with_super_admin_is_rejected_at_schema_layer(
    client, team_admin_token, test_team, member_user
):
    """Same reasoning as add_member above: 422, not 403 — "super_admin" is
    not a member of TEAM_ROLES, so Pydantic rejects it before the handler runs."""
    resp = client.patch(
        f"/teams/{test_team.id}/members/{member_user.id}/role",
        json={"role": "super_admin"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 422


def test_update_member_role_on_an_existing_super_admin_succeeds_and_leaves_platform_role_alone(
    client, team_admin_token, test_team, super_admin_user, make_membership, db_session
):
    """
    The other half of the bug-fix regression test: a super_admin who
    already holds a team membership can have THAT membership's role
    changed freely — platform_role is a separate column and is never
    touched by this endpoint.
    """
    make_membership(user_id=super_admin_user.id, team_id=test_team.id, role="member")

    resp = client.patch(
        f"/teams/{test_team.id}/members/{super_admin_user.id}/role",
        json={"role": "team_admin"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["team_role"] == "team_admin"

    db_session.refresh(super_admin_user)
    assert super_admin_user.platform_role == "super_admin"  # untouched
    assert _membership_role(db_session, super_admin_user.id, test_team.id) == "team_admin"


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
    # Promote member_user to team_admin first (directly, at the DB layer,
    # for setup convenience), so team_admin_user is no longer the *last*
    # one and can safely be demoted.
    membership = (
        db_session.query(TeamMembership)
        .filter(TeamMembership.user_id == member_user.id, TeamMembership.team_id == test_team.id)
        .first()
    )
    membership.role = "team_admin"
    db_session.commit()

    resp = client.patch(
        f"/teams/{test_team.id}/members/{team_admin_user.id}/role",
        json={"role": "member"},
        headers=_auth(team_admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["team_role"] == "member"


def test_plain_member_cannot_change_roles(client, member_token, test_team, member_user):
    resp = client.patch(
        f"/teams/{test_team.id}/members/{member_user.id}/role",
        json={"role": "team_admin"},
        headers=_auth(member_token),
    )
    assert resp.status_code == 403


def test_team_admin_on_team_a_cannot_change_roles_on_team_b(
    client, user_on_two_teams, user_on_two_teams_token, test_team, second_team, member_user
):
    """
    user_on_two_teams is team_admin on second_team but only a plain member
    on test_team — their team_admin status on ONE team must not leak into
    authority over a DIFFERENT team. This is the exact scoping bug that
    would have been impossible to even express under the old single-team
    model (there was only ever one team to be admin of).
    """
    resp = client.patch(
        f"/teams/{test_team.id}/members/{member_user.id}/role",
        json={"role": "team_admin"},
        headers=_auth(user_on_two_teams_token),
    )
    assert resp.status_code == 403


# --- DELETE /teams/{id}/members/{user_id} — self-serve or forced removal ---


def test_member_can_remove_self(client, member_token, member_user, test_team, db_session):
    resp = client.delete(f"/teams/{test_team.id}/members/{member_user.id}", headers=_auth(member_token))
    assert resp.status_code == 200
    assert _membership_role(db_session, member_user.id, test_team.id) is None


def test_team_admin_can_forcibly_remove_another_member(
    client, team_admin_token, member_user, test_team, db_session
):
    resp = client.delete(f"/teams/{test_team.id}/members/{member_user.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 200
    assert _membership_role(db_session, member_user.id, test_team.id) is None


def test_removing_from_one_team_does_not_affect_other_memberships(
    client, user_on_two_teams, test_team, second_team, team_admin_token, db_session
):
    """Removing user_on_two_teams from test_team must leave their
    second_team membership completely untouched — the whole point of
    per-team rows instead of a single team_id."""
    resp = client.delete(f"/teams/{test_team.id}/members/{user_on_two_teams.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 200
    assert _membership_role(db_session, user_on_two_teams.id, test_team.id) is None
    assert _membership_role(db_session, user_on_two_teams.id, second_team.id) == "team_admin"


def test_member_cannot_remove_someone_else(client, member_token, team_admin_user, test_team):
    resp = client.delete(f"/teams/{test_team.id}/members/{team_admin_user.id}", headers=_auth(member_token))
    assert resp.status_code == 403


def test_cannot_remove_the_last_team_admin(client, team_admin_token, team_admin_user, test_team):
    resp = client.delete(f"/teams/{test_team.id}/members/{team_admin_user.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 400


def test_last_team_admin_can_leave_after_promoting_a_peer(
    client, team_admin_token, team_admin_user, member_user, test_team, db_session
):
    membership = (
        db_session.query(TeamMembership)
        .filter(TeamMembership.user_id == member_user.id, TeamMembership.team_id == test_team.id)
        .first()
    )
    membership.role = "team_admin"
    db_session.commit()

    resp = client.delete(f"/teams/{test_team.id}/members/{team_admin_user.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 200
    assert _membership_role(db_session, team_admin_user.id, test_team.id) is None


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

    assert _membership_role(db_session, member_user.id, test_team.id) is None
    assert _membership_role(db_session, team_admin_user.id, test_team.id) is None

    # Team row persists (soft delete — see the Team model's docstring for
    # why a hard delete isn't possible once a team has any environment
    # history), but is marked deleted and excluded from normal lookups.
    deleted_team = db_session.query(Team).filter(Team.id == test_team.id).first()
    db_session.refresh(deleted_team)
    assert deleted_team is not None
    assert deleted_team.deleted_at is not None

    get_resp = client.get(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert get_resp.status_code == 404


def test_delete_team_does_not_affect_a_detached_members_other_teams(
    client, user_on_two_teams, test_team, second_team, team_admin_token, db_session
):
    """Deleting test_team must detach user_on_two_teams from test_team
    ONLY — their second_team membership must survive the delete."""
    resp = client.delete(f"/teams/{test_team.id}", headers=_auth(team_admin_token))
    assert resp.status_code == 200
    assert _membership_role(db_session, user_on_two_teams.id, test_team.id) is None
    assert _membership_role(db_session, user_on_two_teams.id, second_team.id) == "team_admin"


def test_delete_team_succeeds_with_no_environments_at_all(client, team_admin_token, test_team):
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