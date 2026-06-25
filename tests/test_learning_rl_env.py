"""Tests for ``src.learning.rl.env`` — RL surface is research-only.

The d3rlpy-dependent training and evaluation modules are gated behind
``pytest.importorskip("d3rlpy")`` so unit testing works without the ``rl``
extra installed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


def _build_decisions(n: int = 20) -> pd.DataFrame:
    base_ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        action = "BUY" if i % 2 == 0 else "QUEUED"
        ret = 5.0 if i % 4 == 0 else (-5.0 if i % 4 == 1 else 0.5)
        rows.append(
            {
                "cycle_id": f"cycle-rl-{i:03d}",
                "ticker": "AAPL_US_EQ",
                "decision_ts": base_ts + timedelta(days=i),
                "decision_action": action,
                "conviction": float(50 + (i % 5) * 10),
                "uov_raw": float(0.4 + 0.01 * i),
                "label_3class": "big_winner" if ret > 0 else "big_loser" if ret < 0 else "neutral",
                "ret_30d": ret,
                "realized_pnl_pct": ret * 1.1 if i % 5 == 0 else None,
            }
        )
    return pd.DataFrame(rows)


def test_env_constructs_offline_dataset() -> None:
    from src.learning.rl.env import (
        ACTIONS,
        DecisionReplayEnv,
        behaviour_action_from_row,
        build_offline_dataset,
    )

    df = _build_decisions()
    env = DecisionReplayEnv(df, feature_columns=["conviction", "uov_raw"])
    obs, info = env.reset()
    assert obs.shape == (2,)
    assert "decision_ts" in info

    bundle = build_offline_dataset(env)
    assert bundle["observations"].shape[1] == 2
    assert bundle["actions"].shape[0] == len(df)
    assert bundle["rewards"].shape[0] == len(df)
    assert bundle["terminals"][-1] == 1.0

    # Action mapping deterministic.
    first = behaviour_action_from_row(df.iloc[0])
    assert ACTIONS[first] == "buy_full"
    second = behaviour_action_from_row(df.iloc[1])
    assert ACTIONS[second] == "queue"


def test_env_reward_uses_realized_when_present() -> None:
    from src.learning.rl.env import DecisionReplayEnv, RewardConfig

    df = _build_decisions()
    env = DecisionReplayEnv(
        df,
        feature_columns=["conviction", "uov_raw"],
        reward_config=RewardConfig(cost_basis_pct=0.0),
    )
    obs, _ = env.reset()
    # First row is BUY (action_idx=3) with realized_pnl_pct=5.5
    _, reward, _, _, info = env.step(3)
    assert reward >= 5.0, f"reward should track realized PnL: {reward}"
    assert "reward_counterfactual" in info
    assert info["behaviour_action"] in {0, 1, 2, 3}


def test_env_summary_tracks_action_distribution() -> None:
    from src.learning.rl.env import DecisionReplayEnv, build_offline_dataset

    df = _build_decisions()
    env = DecisionReplayEnv(df, feature_columns=["conviction", "uov_raw"])
    build_offline_dataset(env)
    summary = env.summary()
    assert summary.total_steps == len(df)
    assert summary.action_counts["buy_full"] + summary.action_counts["queue"] == len(df)


def test_wis_runs_without_d3rlpy() -> None:
    from src.learning.rl.evaluation import weighted_importance_sampling

    df = _build_decisions()

    def uniform_policy(_row: pd.Series) -> np.ndarray:
        return np.full(4, 0.25)

    result = weighted_importance_sampling(df, uniform_policy)
    assert result.estimator == "wis"
    assert result.n_transitions == len(df)
    assert "weight_mean" in result.diagnostic


def test_load_env_default_uses_active_dataset_version(monkeypatch) -> None:
    from src.learning.rl import env as rl_env
    from src.learning.spec import DATASET_VERSION

    captured: dict[str, str] = {}

    def fake_exists(self):
        captured["path"] = str(self)
        return False

    monkeypatch.setattr(rl_env.Path, "exists", fake_exists)

    try:
        rl_env.load_env()
    except FileNotFoundError:
        pass

    assert f"data/learning/parquet/{DATASET_VERSION}/merged.parquet" in captured["path"]
