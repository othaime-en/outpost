"""
Tests for app.services.cost

These are pure unit tests against the service functions directly — no
TestClient, no DB, no HTTP. `TestCostPreview` in test_environments.py
already covers the `/cost-preview` route (auth, validation, response
shape).
"""

from __future__ import annotations

from app.services import cost


class TestEstimateMonthlyCost:
    def test_cost_estimate_is_reasonable(self):
        """Plan's Phase 5 checklist: dev ~$22-25/mo."""
        dev_estimate = cost.estimate_monthly_cost("dev")
        assert 20.0 <= dev_estimate <= 30.0

    def test_staging_is_roughly_20_percent_more_than_dev(self):
        dev_estimate = cost.estimate_monthly_cost("dev")
        staging_estimate = cost.estimate_monthly_cost("staging")
        assert staging_estimate == round(dev_estimate * 1.2, 2)

    def test_estimate_is_deterministic(self):
        """Static pricing table — same input always gives the same output,
        no hidden randomness or time-of-day dependence."""
        assert cost.estimate_monthly_cost("dev") == cost.estimate_monthly_cost("dev")

    def test_estimate_is_positive(self):
        assert cost.estimate_monthly_cost("dev") > 0
        assert cost.estimate_monthly_cost("staging") > 0

    def test_unrecognized_env_type_falls_back_to_dev_multiplier(self):
        """
        `estimate_monthly_cost` itself doesn't validate `env_type` — that's
        enforced upstream (Pydantic's `pattern=r'^(dev|staging)$'` on
        CreateEnvironmentRequest, and an explicit check in the
        `/cost-preview` route). Documenting that here rather than adding
        validation this function was never meant to own: only 'staging'
        gets the 1.2x multiplier, everything else behaves like 'dev'.
        """
        assert cost.estimate_monthly_cost("anything-else") == cost.estimate_monthly_cost("dev")


class TestGetCostBreakdown:
    def test_all_four_line_items_present(self):
        breakdown = cost.get_cost_breakdown("dev")
        assert set(breakdown.keys()) == {
            "ecs_fargate",
            "rds_postgres",
            "cloudwatch_logs",
            "secrets_manager",
            "total_monthly",
            "env_type",
            "note",
        }

    def test_line_items_are_all_positive(self):
        breakdown = cost.get_cost_breakdown("dev")
        for key in ("ecs_fargate", "rds_postgres", "cloudwatch_logs", "secrets_manager", "total_monthly"):
            assert breakdown[key] > 0, f"{key} should be a positive number"

    def test_env_type_is_echoed_back(self):
        assert cost.get_cost_breakdown("staging")["env_type"] == "staging"

    def test_total_matches_estimate_monthly_cost(self):
        """The itemized breakdown's total must always agree with the
        single-number estimate stored on Environment.cost_estimate_usd —
        showing the user a preview that doesn't match what gets billed to
        their environment would be a real (if small) trust problem."""
        for env_type in ("dev", "staging"):
            breakdown = cost.get_cost_breakdown(env_type)
            assert breakdown["total_monthly"] == cost.estimate_monthly_cost(env_type)