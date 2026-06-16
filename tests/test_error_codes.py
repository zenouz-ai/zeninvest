"""Tests for the failure-mode error-code taxonomy (US-9.6)."""

import logging

from src.utils.error_codes import ErrorCode


class TestErrorCodes:
    def test_values_unique(self):
        values = [c.value for c in ErrorCode]
        assert len(values) == len(set(values))

    def test_str_renders_bare_code(self):
        assert str(ErrorCode.DATA_PROVIDER_ERROR) == "D001"
        assert f"{ErrorCode.COST_MONTHLY_HALT}" == "P002"

    def test_codes_follow_category_prefixes(self):
        prefixes = {
            "DATA_": "D",
            "LLM_": "L",
            "BROKER_": "B",
            "CONCURRENCY_": "C",
            "SECURITY_": "S",
            "LEARNING_": "M",
            "COST_": "P",
        }
        for code in ErrorCode:
            for name_prefix, code_prefix in prefixes.items():
                if code.name.startswith(name_prefix):
                    assert code.value.startswith(code_prefix), code.name
                    break
            else:  # pragma: no cover - guards against an untagged new code
                raise AssertionError(f"{code.name} has no category prefix mapping")


class TestCostTrackerEmitsCodes:
    def test_category_budget_logs_cost_code(self, caplog):
        from unittest.mock import patch

        from src.utils import cost_tracker

        with patch.object(cost_tracker, "get_monthly_spend", return_value=0.0), patch.object(
            cost_tracker, "get_category_daily_spend", return_value=999.0
        ):
            with caplog.at_level(logging.WARNING):
                assert cost_tracker.check_category_budget("chat") is False
        assert "[P001]" in caplog.text
