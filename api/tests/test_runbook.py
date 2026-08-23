"""
Tests for app.services.runbook

Direct unit tests against `generate()` using a lightweight fake
environment (SimpleNamespace, same pattern test_environments.py already
uses for fakes) rather than a real DB-backed Environment — no session,
no lazy-loaded relationships to worry about, full control over exactly
which fields are populated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import runbook

FULL_OUTPUTS = {
    "ecs_service_arn": "arn:aws:ecs:us-east-1:123456789012:service/outpost-shared/svc-abc",
    "ecs_cluster_arn": "arn:aws:ecs:us-east-1:123456789012:cluster/outpost-shared",
    "rds_endpoint": "outpost-abc123.us-east-1.rds.amazonaws.com:5432",
    "rds_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:outpost/abc/rds",
    "log_group_name": "/outpost/abc123",
    "subnet_id": "subnet-0abc123",
}


def _fake_env(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=uuid.uuid4(),
        name="my-feature-branch",
        env_type="dev",
        aws_region="us-east-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        team=SimpleNamespace(name="Platform Engineering"),
        creator=SimpleNamespace(username="octocat"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestGenerate:
    def test_runbook_contains_all_fields(self):
        env = _fake_env()
        content = runbook.generate(env, FULL_OUTPUTS)

        # Environment identity
        assert env.name in content
        assert str(env.id) in content
        assert env.env_type in content
        assert env.aws_region in content
        assert env.team.name in content
        assert env.creator.username in content

        # Terraform outputs — every value from FULL_OUTPUTS should appear
        for value in FULL_OUTPUTS.values():
            assert value in content, f"expected output value {value!r} to appear in the runbook"

        # No unrendered Jinja placeholders left behind
        assert "{{" not in content and "}}" not in content

    def test_no_blank_or_none_fields_when_outputs_are_complete(self):
        env = _fake_env()
        content = runbook.generate(env, FULL_OUTPUTS)
        # A None slipping through Jinja renders as the literal string "None"
        assert "None" not in content
        assert "n/a" not in content  # only appears when an output key is missing

    def test_missing_outputs_render_as_na_not_a_crash(self):
        """The callback can theoretically arrive with a partial outputs
        dict (e.g. a Terraform module change that drops a field) — the
        template must degrade gracefully, not raise."""
        env = _fake_env()
        content = runbook.generate(env, {})  # nothing at all
        assert "n/a" in content
        assert "None" not in content

    def test_optional_service_url_omitted_when_absent(self):
        env = _fake_env()
        content = runbook.generate(env, FULL_OUTPUTS)  # no service_url key
        assert "Service URL" not in content

    def test_optional_service_url_included_when_present(self):
        env = _fake_env()
        outputs = {**FULL_OUTPUTS, "service_url": "https://my-feature-branch.dev.example.com"}
        content = runbook.generate(env, outputs)
        assert "Service URL" in content
        assert outputs["service_url"] in content

    def test_includes_ttl_extend_and_destroy_commands(self):
        env = _fake_env()
        content = runbook.generate(env, FULL_OUTPUTS)
        assert f"outpost env extend {env.id}" in content
        assert f"outpost env destroy {env.id}" in content

    def test_respects_custom_api_base_url(self):
        env = _fake_env()
        content = runbook.generate(env, FULL_OUTPUTS, api_base_url="https://api.outpost.example.com")
        assert "https://api.outpost.example.com" in content

    def test_output_is_valid_markdown_heading_structure(self):
        env = _fake_env()
        content = runbook.generate(env, FULL_OUTPUTS)
        assert content.startswith("# Environment Runbook")
        assert "## Resource Summary" in content
        assert "## Connect to the Database" in content
        assert "## Extend TTL" in content
        assert "## Destroy Early" in content