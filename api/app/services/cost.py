"""
Cost Estimation Service

NOTE — pulled forward from Phase 5: the implementation plan's Phase 4
`create_environment` code calls `cost.estimate_monthly_cost()` directly, and
`GET /environments/cost-preview` is part of the Phase 4 router surface. So a
working version of this service has to exist now, not after Phase 5. This
is the same "minimal forward dependency" pattern already used for the
Phase 4 callback → services/cost.py + services/runbook.py.

What's genuinely still Phase 5 scope and NOT here: CloudWatch-based health
checking (services/health_checker.py) and the daily Cost Explorer snapshot
job that populates `cost_snapshots` with *actual* spend. This module only
produces the static, explainable estimate used at creation time and for the
pre-provisioning cost preview.
"""

from __future__ import annotations

# Static monthly estimates, us-east-1, illustrative pricing.
PRICING = {
    "fargate_vcpu_per_hour": 0.04048,
    "fargate_gb_per_hour": 0.004445,
    "rds_t3_micro_monthly": 15.33,
    "cloudwatch_logs_per_gb": 0.50,
    "secrets_manager_monthly": 0.40,
}

_HOURS_PER_MONTH = 24 * 30


def _ecs_fargate_monthly() -> float:
    return round(
        PRICING["fargate_vcpu_per_hour"] * 0.25 * _HOURS_PER_MONTH
        + PRICING["fargate_gb_per_hour"] * 0.5 * _HOURS_PER_MONTH,
        2,
    )


def estimate_monthly_cost(env_type: str) -> float:
    """
    Single-number estimate stored on Environment.cost_estimate_usd at
    creation time. `staging` carries a 20% multiplier over `dev` — a
    stand-in for staging environments typically running closer to 24/7
    with less aggressive TTLs in practice.
    """
    fargate = _ecs_fargate_monthly()
    rds = PRICING["rds_t3_micro_monthly"]
    overhead = PRICING["cloudwatch_logs_per_gb"] + PRICING["secrets_manager_monthly"]
    multiplier = 1.2 if env_type == "staging" else 1.0
    return round((fargate + rds + overhead) * multiplier, 2)


def get_cost_breakdown(env_type: str) -> dict:
    """Itemized version used by GET /environments/cost-preview."""
    return {
        "ecs_fargate": _ecs_fargate_monthly(),
        "rds_postgres": PRICING["rds_t3_micro_monthly"],
        "cloudwatch_logs": PRICING["cloudwatch_logs_per_gb"],
        "secrets_manager": PRICING["secrets_manager_monthly"],
        "total_monthly": estimate_monthly_cost(env_type),
        "env_type": env_type,
        "note": "Estimate based on 24/7 runtime. Actual cost depends on usage.",
    }