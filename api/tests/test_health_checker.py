"""
Tests for app.services.health_checker
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.services import health_checker


# --- check_ecs_health ------------------------------------------------------


class TestCheckEcsHealth:
    def _client_returning(self, services: list[dict]) -> MagicMock:
        mock_client = MagicMock()
        mock_client.describe_services.return_value = {"services": services}
        return mock_client

    def test_healthy_when_running_meets_desired(self):
        client = self._client_returning(
            [{"status": "ACTIVE", "runningCount": 2, "desiredCount": 2}]
        )
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.HEALTHY

    def test_healthy_when_running_exceeds_desired(self):
        """A mid-deploy scale-up (running temporarily > desired) still reads healthy."""
        client = self._client_returning(
            [{"status": "ACTIVE", "runningCount": 3, "desiredCount": 2}]
        )
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.HEALTHY

    def test_degraded_when_running_below_desired(self):
        client = self._client_returning(
            [{"status": "ACTIVE", "runningCount": 0, "desiredCount": 1}]
        )
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.DEGRADED

    def test_degraded_when_service_not_active(self):
        client = self._client_returning(
            [{"status": "DRAINING", "runningCount": 1, "desiredCount": 1}]
        )
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.DEGRADED

    def test_degraded_when_service_list_is_empty(self):
        """describe_services returns an empty list when the service has been deleted."""
        client = self._client_returning([])
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.DEGRADED

    def test_unknown_when_desired_count_is_zero(self):
        """Intentionally scaled to zero is not the same thing as unhealthy."""
        client = self._client_returning(
            [{"status": "ACTIVE", "runningCount": 0, "desiredCount": 0}]
        )
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.UNKNOWN

    def test_health_returns_unknown_on_client_error(self):
        client = MagicMock()
        client.describe_services.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "boom"}},
            "DescribeServices",
        )
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.UNKNOWN

    def test_health_returns_unknown_on_unexpected_exception(self):
        """Any non-AWS exception (network blip, bad response shape, etc.) also degrades to UNKNOWN — never raises."""
        client = MagicMock()
        client.describe_services.side_effect = RuntimeError("unexpected")
        with patch.object(health_checker.boto3, "client", return_value=client):
            result = health_checker.check_ecs_health("svc-arn", "cluster-arn", "us-east-1")
        assert result == health_checker.UNKNOWN

    def test_uses_environments_own_region(self):
        """Regression guard for the plan deviation: region must be passed through, not read from global settings."""
        client = self._client_returning(
            [{"status": "ACTIVE", "runningCount": 1, "desiredCount": 1}]
        )
        with patch.object(health_checker.boto3, "client", return_value=client) as client_factory:
            health_checker.check_ecs_health("svc-arn", "cluster-arn", "eu-west-1")
        client_factory.assert_called_once_with("ecs", region_name="eu-west-1")


# --- poll_once --------------------------------------------------------------


class TestPollOnce:
    def test_updates_running_environments_with_outputs(
        self, db_session, test_team, member_user, make_environment
    ):
        env = make_environment(
            team_id=test_team.id,
            created_by=member_user.id,
            status="RUNNING",
        )
        env.outputs = {
            "ecs_service_arn": "arn:aws:ecs:us-east-1:123:service/svc",
            "ecs_cluster_arn": "arn:aws:ecs:us-east-1:123:cluster/outpost-shared",
        }
        db_session.commit()

        with patch.object(health_checker, "check_ecs_health", return_value=health_checker.HEALTHY) as mock_check:
            updated = health_checker.poll_once(db_session)

        assert updated == 1
        mock_check.assert_called_once_with(
            "arn:aws:ecs:us-east-1:123:service/svc",
            "arn:aws:ecs:us-east-1:123:cluster/outpost-shared",
            env.aws_region,
        )

        db_session.refresh(env)
        assert env.health_status == health_checker.HEALTHY
        assert env.health_checked_at is not None
        assert env.health_checked_at.tzinfo is not None

    def test_skips_environments_without_outputs(
        self, db_session, test_team, member_user, make_environment
    ):
        # PENDING/PROVISIONING environments have outputs=None until the
        # callback lands — poll_once's own filter should exclude them, but
        # this also guards the case of a RUNNING row with no outputs yet.
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING"
        )
        assert env.outputs is None

        with patch.object(health_checker, "check_ecs_health") as mock_check:
            updated = health_checker.poll_once(db_session)

        mock_check.assert_not_called()
        assert updated == 0

    def test_skips_environments_missing_ecs_arns_in_outputs(
        self, db_session, test_team, member_user, make_environment
    ):
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING"
        )
        env.outputs = {"rds_endpoint": "db.example.com"}  # no ECS keys at all
        db_session.commit()

        with patch.object(health_checker, "check_ecs_health") as mock_check:
            updated = health_checker.poll_once(db_session)

        mock_check.assert_not_called()
        assert updated == 0

    def test_ignores_non_running_environments(
        self, db_session, test_team, member_user, make_environment
    ):
        env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="DESTROYED"
        )
        env.outputs = {
            "ecs_service_arn": "arn:svc",
            "ecs_cluster_arn": "arn:cluster",
        }
        db_session.commit()

        with patch.object(health_checker, "check_ecs_health") as mock_check:
            updated = health_checker.poll_once(db_session)

        mock_check.assert_not_called()
        assert updated == 0

    def test_one_bad_environment_does_not_block_others(
        self, db_session, test_team, member_user, make_environment
    ):
        """check_ecs_health itself never raises (see TestCheckEcsHealth), but
        poll_once should still process every eligible row even if one of
        them has a surprising shape."""
        healthy_env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING"
        )
        healthy_env.outputs = {"ecs_service_arn": "a", "ecs_cluster_arn": "b"}

        skipped_env = make_environment(
            team_id=test_team.id, created_by=member_user.id, status="RUNNING"
        )
        skipped_env.outputs = {}  # missing arns — should be skipped, not crash the pass
        db_session.commit()

        with patch.object(health_checker, "check_ecs_health", return_value=health_checker.DEGRADED):
            updated = health_checker.poll_once(db_session)

        assert updated == 1
        db_session.refresh(healthy_env)
        db_session.refresh(skipped_env)
        assert healthy_env.health_status == health_checker.DEGRADED
        assert skipped_env.health_status == "UNKNOWN"  # untouched default