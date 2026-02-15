from unittest.mock import MagicMock, patch

import pytest

from infra.guardrails import (
    COST_PER_HOUR,
    MAX_DROPLETS,
    MAX_SESSION_MINUTES,
    SessionGuard,
    check_droplet_limit,
    check_stale_droplets,
    count_tagged_droplets,
    estimate_cost,
)


TOKEN = "test-token-abc123"


def _make_mock_droplet(id, name, created_at, ip_address="10.0.0.1"):
    d = MagicMock()
    d.id = id
    d.name = name
    d.created_at = created_at
    d.ip_address = ip_address
    return d


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_default_max_droplets(self):
        assert MAX_DROPLETS == 7

    def test_default_max_session_minutes(self):
        assert MAX_SESSION_MINUTES == 60

    def test_cost_per_hour(self):
        assert COST_PER_HOUR == 0.00893

    def test_env_override_max_droplets(self):
        with patch.dict("os.environ", {"MAX_TEST_DROPLETS": "10"}):
            # Re-import to pick up the env override
            import importlib
            import infra.guardrails as mod
            importlib.reload(mod)
            assert mod.MAX_DROPLETS == 10
            # Restore
            importlib.reload(mod)

    def test_env_override_max_session_minutes(self):
        with patch.dict("os.environ", {"MAX_SESSION_MINUTES": "120"}):
            import importlib
            import infra.guardrails as mod
            importlib.reload(mod)
            assert mod.MAX_SESSION_MINUTES == 120
            importlib.reload(mod)


# ---------------------------------------------------------------------------
# TestCountTaggedDroplets
# ---------------------------------------------------------------------------


class TestCountTaggedDroplets:
    @patch("infra.guardrails.digitalocean")
    def test_returns_count(self, mock_do):
        mock_do.Manager.return_value.get_all_droplets.return_value = [
            MagicMock(), MagicMock(), MagicMock()
        ]
        assert count_tagged_droplets(TOKEN) == 3
        mock_do.Manager.return_value.get_all_droplets.assert_called_with(
            tag_name="sysadmin-ai-test"
        )

    @patch("infra.guardrails.digitalocean")
    def test_returns_zero_when_none(self, mock_do):
        mock_do.Manager.return_value.get_all_droplets.return_value = []
        assert count_tagged_droplets(TOKEN) == 0

    @patch("infra.guardrails.digitalocean")
    def test_uses_custom_tag(self, mock_do):
        mock_do.Manager.return_value.get_all_droplets.return_value = []
        count_tagged_droplets(TOKEN, tag="custom-tag")
        mock_do.Manager.return_value.get_all_droplets.assert_called_with(
            tag_name="custom-tag"
        )


# ---------------------------------------------------------------------------
# TestCheckDropletLimit
# ---------------------------------------------------------------------------


class TestCheckDropletLimit:
    @patch("infra.guardrails.count_tagged_droplets", return_value=3)
    def test_passes_when_under_limit(self, mock_count):
        check_droplet_limit(TOKEN, limit=7)  # should not raise

    @patch("infra.guardrails.count_tagged_droplets", return_value=7)
    def test_raises_when_at_limit(self, mock_count):
        with pytest.raises(RuntimeError, match="Droplet limit reached"):
            check_droplet_limit(TOKEN, limit=7)

    @patch("infra.guardrails.count_tagged_droplets", return_value=10)
    def test_raises_when_above_limit(self, mock_count):
        with pytest.raises(RuntimeError, match="Droplet limit reached"):
            check_droplet_limit(TOKEN, limit=7)


# ---------------------------------------------------------------------------
# TestCheckStaleDroplets
# ---------------------------------------------------------------------------


class TestCheckStaleDroplets:
    @patch("infra.guardrails.digitalocean")
    def test_returns_empty_when_none(self, mock_do):
        mock_do.Manager.return_value.get_all_droplets.return_value = []
        assert check_stale_droplets(TOKEN) == []

    @patch("infra.guardrails.digitalocean")
    def test_returns_dicts_with_correct_keys(self, mock_do):
        d1 = _make_mock_droplet(1, "test-ubuntu-ab12", "2025-01-15T10:00:00Z")
        d2 = _make_mock_droplet(2, "test-debian-cd34", "2025-01-15T10:05:00Z")
        mock_do.Manager.return_value.get_all_droplets.return_value = [d1, d2]

        result = check_stale_droplets(TOKEN)

        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "test-ubuntu-ab12", "created_at": "2025-01-15T10:00:00Z"}
        assert result[1] == {"id": 2, "name": "test-debian-cd34", "created_at": "2025-01-15T10:05:00Z"}


# ---------------------------------------------------------------------------
# TestEstimateCost
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_seven_droplets_60_minutes(self):
        cost = estimate_cost(7, 60)
        assert round(cost, 4) == round(7 * COST_PER_HOUR, 4)

    def test_zero_droplets(self):
        assert estimate_cost(0, 60) == 0.0

    def test_zero_duration(self):
        assert estimate_cost(7, 0) == 0.0

    def test_30_minutes(self):
        cost = estimate_cost(1, 30)
        assert round(cost, 6) == round(COST_PER_HOUR / 2, 6)


# ---------------------------------------------------------------------------
# TestSessionGuard
# ---------------------------------------------------------------------------


class TestSessionGuard:
    @patch("infra.guardrails.check_droplet_limit")
    @patch("infra.guardrails.time")
    def test_check_before_create_passes(self, mock_time, mock_limit):
        mock_time.monotonic.return_value = 0
        guard = SessionGuard(TOKEN)
        mock_time.monotonic.return_value = 60  # 1 minute elapsed
        guard.check_before_create()  # should not raise
        mock_limit.assert_called_once()

    @patch("infra.guardrails.check_droplet_limit")
    @patch("infra.guardrails.time")
    def test_check_before_create_fails_on_limit(self, mock_time, mock_limit):
        mock_time.monotonic.return_value = 0
        guard = SessionGuard(TOKEN)
        mock_time.monotonic.return_value = 60
        mock_limit.side_effect = RuntimeError("Droplet limit reached")
        with pytest.raises(RuntimeError, match="Droplet limit reached"):
            guard.check_before_create()

    @patch("infra.guardrails.time")
    def test_check_timeout_passes(self, mock_time):
        mock_time.monotonic.return_value = 0
        guard = SessionGuard(TOKEN, max_minutes=60)
        mock_time.monotonic.return_value = 30 * 60  # 30 minutes
        guard.check_timeout()  # should not raise

    @patch("infra.guardrails.time")
    def test_check_timeout_raises(self, mock_time):
        mock_time.monotonic.return_value = 0
        guard = SessionGuard(TOKEN, max_minutes=60)
        mock_time.monotonic.return_value = 61 * 60  # 61 minutes
        with pytest.raises(RuntimeError, match="Session timeout"):
            guard.check_timeout()

    @patch("infra.guardrails.time")
    def test_elapsed_minutes(self, mock_time):
        mock_time.monotonic.return_value = 0
        guard = SessionGuard(TOKEN)
        mock_time.monotonic.return_value = 300  # 5 minutes in seconds
        assert guard.elapsed_minutes() == 5.0

    @patch("infra.guardrails.count_tagged_droplets", return_value=3)
    @patch("infra.guardrails.time")
    def test_summary_returns_expected_keys(self, mock_time, mock_count):
        mock_time.monotonic.return_value = 0
        guard = SessionGuard(TOKEN)
        mock_time.monotonic.return_value = 600  # 10 minutes
        result = guard.summary()
        assert "elapsed_minutes" in result
        assert "estimated_cost" in result
        assert "droplet_count" in result
        assert result["droplet_count"] == 3
        assert result["elapsed_minutes"] == 10.0

    def test_cleanup_calls_destroy_all(self):
        guard = SessionGuard(TOKEN)
        mock_controller = MagicMock()
        guard.cleanup(mock_controller)
        mock_controller.destroy_all.assert_called_once_with(tag="sysadmin-ai-test")

    def test_cleanup_swallows_exceptions(self):
        guard = SessionGuard(TOKEN)
        mock_controller = MagicMock()
        mock_controller.destroy_all.side_effect = Exception("API error")
        guard.cleanup(mock_controller)  # should not raise
