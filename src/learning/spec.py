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

from dataclasses import dataclass, field, replace
from typing import Sequence


# Version of the on-disk parquet schema. Bump when adding/removing/renaming a
# label column or a structural feature group. Feature additions inside an
# existing group do not require a bump as long as builder.py stays
# backwards-compatible.
DATASET_VERSION = "v6"


@dataclass(frozen=True)
class LabelConfig:
    """Thresholds for the 3-class supervised target (v6 unified gain/day bands).

    Realized trades: ``big_winner`` when gain/day ≥ winner threshold;
    ``stall`` when gain/day is between stall floor and winner threshold;
    ``big_loser`` when gain/day < stall floor. No ``neutral`` on closed trades.
    """

    # Forward MTM horizons (calendar days) attached as ret_<H>d columns.
    horizons_days: tuple[int, ...] = (3, 10, 30)

    # Unified gain/day bands (realized rows and MTM fallbacks).
    success_min_profit_per_day_pct: float = 0.25
    stall_min_gain_per_day_pct: float = -0.05

    # Drawdown veto: path-resolved big_winner must not draw down beyond this (pct).
    big_winner_max_drawdown_pct: float = -8.0

    # MTM vertical-barrier / Phase-A stall helpers (open rows only).
    stall_abs_return_pct: float = 3.0
    stall_min_holding_days: float = 14.0

    # Embargo (calendar days) between the end of the training window and the
    # start of the test window in walk-forward CV. Should be at least
    # ``max(horizons_days)`` to avoid label leakage across folds (Lopez de
    # Prado, AFML ch. 7).
    embargo_days: int = 30

    @property
    def barrier_vertical_days(self) -> float:
        return float(max(self.horizons_days))

    @property
    def barrier_upper_pct(self) -> float:
        return self.success_min_profit_per_day_pct * self.barrier_vertical_days

    @property
    def barrier_lower_pct(self) -> float:
        return self.stall_min_gain_per_day_pct * self.barrier_vertical_days


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
                "success_min_profit_per_day_pct": self.labels.success_min_profit_per_day_pct,
                "stall_min_gain_per_day_pct": self.labels.stall_min_gain_per_day_pct,
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
    """Return the canonical dataset spec."""
    return DatasetSpec()


def get_effective_label_config() -> LabelConfig:
    """Label thresholds with optional overrides from settings.yaml."""
    base = get_default_spec().labels
    try:
        from src.utils.config import get_settings

        settings = get_settings()
        learning = settings.learning
        overrides: dict[str, float] = {}
        for key, yaml_key in (
            ("success_min_profit_per_day_pct", "success_min_profit_per_day_pct"),
            ("stall_min_gain_per_day_pct", "stall_min_gain_per_day_pct"),
        ):
            if yaml_key in learning:
                overrides[key] = float(learning[yaml_key])
        if overrides:
            return replace(base, **overrides)
    except Exception:
        pass
    return base


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
            "barrier_outcome",
            "barrier_days_to_touch",
            "barrier_mtm_max_drawdown_pct",
            "barrier_price_source",
        ]
    )
    return tuple(cols)
