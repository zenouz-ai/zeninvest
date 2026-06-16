"""Stable error codes for ZenInvest failure modes (US-9.6).

A lightweight, in-repo taxonomy: each enum value is a stable, greppable code
(e.g. ``D001``) prefixed onto the ``logger.error`` message at real raise sites.
This is intentionally NOT a new exception hierarchy or a registry module — git
is the source of truth and ``docs/FAILURE_MODES.md`` is the human reference.
Promote to a richer module only once codes are numerous and the dashboard
consumes them (see docs/AGENTIC_TRANSFORMATION_PLAN.md).

Categories:
    D - Data / market-data providers
    L - LLM / committee output
    B - Broker / execution
    C - Concurrency / runtime locks
    S - Security / auth
    M - Model / learning pipeline
    P - Cost / budget (P for "purse")
"""

from enum import Enum


class ErrorCode(str, Enum):
    """Stable failure-mode codes. The value is the code used in logs."""

    # Data / market-data providers
    DATA_PROVIDER_ERROR = "D001"          # external market-data API call failed

    # LLM / committee output
    LLM_OUTPUT_UNPARSABLE = "L001"        # model returned non-JSON / wrong shape

    # Broker / execution
    BROKER_POSITION_MISSING = "B001"      # expected position not held at broker
    BROKER_PAYLOAD_INVALID = "B002"       # execution payload missing / malformed

    # Concurrency / runtime locks
    CONCURRENCY_LOCK_HELD = "C001"        # another process holds the runtime lock

    # Security / auth
    SECURITY_AUTH_MISCONFIGURED = "S001"  # required auth secret/config absent

    # Model / learning pipeline
    LEARNING_NO_MODEL = "M001"            # no trained model artifact available
    LEARNING_EMPTY_DATASET = "M002"       # cannot train/score on empty data

    # Cost / budget
    COST_DAILY_CAP_EXCEEDED = "P001"      # category/provider daily cap hit
    COST_MONTHLY_HALT = "P002"            # global monthly cap hit; degradation HALTED

    def __str__(self) -> str:  # so f"{ErrorCode.X}" renders the bare code
        return self.value
