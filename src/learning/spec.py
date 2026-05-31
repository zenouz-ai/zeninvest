"""Frozen dataset specification for the trade-outcome learning pipeline.

The spec is the single source of truth for:

- which decisions count as a row (``action IN row_actions``)
- the leakage rule (``as_of_ts <= strategy_decisions.timestamp``)
- the forward horizons used to attach mark-to-market labels
- the thresholds that turn returns into the three-class target
- the feature groups the builder is allowed to emit

Bumping ``DATASET_VERSION`` invalidates cached parquet outputs and triggers a
fresh build on the next ``python -m src.learning.cli build`` run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


# Version of the on-disk parquet schema. Bump when adding/removing/renaming a
# label column or a structural feature group. Feature additions inside an
# existing group do not require a bump as long as builder.py stays
# backwards-compatible.
DATASET_VERSION = "v2"


@dataclass(frozen=True)
class LabelConfig:
    """Thresholds for the 3-class supervised target.

    Defaults match the operational definitions ZenInvest already uses
    (US-3.7 stagnation exit, profit-lock tiers, US-2.1 conviction calibration).
    """

    # Forward MTM horizons (calendar days) attached as ret_<H>d columns.
    horizons_days: tuple[int, ...] = (3, 10, 30)

    # Big-winner / big-loser thresholds applied to the longest horizon (or
    # realized P&L when the trade closed).
    big_winner_min_return_pct: float = 10.0
    big_loser_max_return_pct: float = -10.0

    # Drawdown veto: a big winner must never have drawn down by more than this
    # over the labelling horizon (in pct). Negative number.
    big_winner_max_drawdown_pct: float = -8.0

    # Stall band on the longest horizon and the minimum holding-days qualifier.
    stall_abs_return_pct: float = 3.0
    stall_min_holding_days: float = 14.0

    # Embargo (calendar days) between the end of the training window and the
    # start of the test window in walk-forward CV. Should be at least
    # ``max(horizons_days)`` to avoid label leakage across folds (Lopez de
    # Prado, AFML ch. 7).
    embargo_days: int = 30


@dataclass(frozen=True)
class DatasetSpec:
    """Top-level dataset specification."""

    version: str = DATASET_VERSION

    # Which Strategy actions become rows. BUY and QUEUED are both included
    # because QUEUED is just a UOV-deferred BUY in this pipeline and gives us
    # additional samples without leaking labels.
    row_actions: tuple[str, ...] = ("BUY", "QUEUED")

    # Feature groups the builder is allowed to emit, mirroring section 3 of
    # the plan. The names are surfaced in the data card and reports.
    feature_groups: tuple[str, ...] = (
        "committee",        # Group A — strategy + moderation + risk signals
        "opportunity_macro",  # Group B — UOV, regime, guidance, vix/spy
        "market_fundamentals",  # Group C — technicals + fundamentals
        "portfolio_context",   # Group D — cash, concentration, positions
        "research_intensity",  # Group E — research_logs aggregates
        "attribution_context",  # Group F — cycle context + macro headlines (v2)
    )

    labels: LabelConfig = field(default_factory=LabelConfig)

    # Output directory (relative to project root).
    output_dir: str = "data/learning"

    def parquet_paths(self) -> dict[str, str]:
        base = f"{self.output_dir}/parquet/{self.version}"
        return {
            "decisions": f"{base}/decisions.parquet",
            "outcomes": f"{base}/outcomes.parquet",
            "features": f"{base}/features.parquet",
            "text_corpus": f"{base}/text_corpus.parquet",
            "splits": f"{base}/splits.json",
            "schema": f"{base}/schema.json",
        }

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "row_actions": list(self.row_actions),
            "feature_groups": list(self.feature_groups),
            "labels": {
                "horizons_days": list(self.labels.horizons_days),
                "big_winner_min_return_pct": self.labels.big_winner_min_return_pct,
                "big_loser_max_return_pct": self.labels.big_loser_max_return_pct,
                "big_winner_max_drawdown_pct": self.labels.big_winner_max_drawdown_pct,
                "stall_abs_return_pct": self.labels.stall_abs_return_pct,
                "stall_min_holding_days": self.labels.stall_min_holding_days,
                "embargo_days": self.labels.embargo_days,
            },
            "output_dir": self.output_dir,
        }


@dataclass(frozen=True)
class TextCorpusSpec:
    """Sidecar text export for memory / graph / embedding tracks (Track B)."""

    version: str = DATASET_VERSION
    output_dir: str = "data/learning"

    def text_corpus_path(self) -> str:
        return f"{self.output_dir}/parquet/{self.version}/text_corpus.parquet"

    def memory_bundle_path(self) -> str:
        return f"{self.output_dir}/exports/{self.version}/memory_bundle.jsonl"

    def vector_index_path(self) -> str:
        return f"{self.output_dir}/vectors/{self.version}/index.jsonl"


def get_default_spec() -> DatasetSpec:
    """Return the canonical v2 spec."""
    return DatasetSpec()


def get_text_corpus_spec() -> TextCorpusSpec:
    """Return the canonical text sidecar spec (aligned to dataset version)."""
    return TextCorpusSpec(version=DATASET_VERSION)


def label_columns(spec: DatasetSpec | None = None) -> Sequence[str]:
    """Names of forward-looking columns that must not leak into features."""
    spec = spec or get_default_spec()
    cols: list[str] = []
    for h in spec.labels.horizons_days:
        cols.extend([f"ret_{h}d", f"mtm_max_drawdown_{h}d", f"mtm_max_runup_{h}d"])
    cols.extend(
        [
            "realized_pnl_pct",
            "realized_holding_days",
            "exit_reason",
            "actually_traded",
            "label_3class",
            "trade_buy_timestamp",
            "trade_sell_timestamp",
            "trade_pnl_gbp",
            "trade_buy_value_gbp",
            "trade_sell_value_gbp",
            "trade_moderation_result",
            "trade_risk_result",
            "trade_strategy",
        ]
    )
    return tuple(cols)
