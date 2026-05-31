"""Off-policy evaluation (OPE) for the offline RL research surface.

Implements two complementary estimators:

- **Weighted Importance Sampling (WIS)** — closed-form, treats the env as a
  contextual bandit (one-step decisions). Robust to a small dataset because
  it does not learn a Q-function, but very sensitive to large importance
  weights.
- **Fitted Q Evaluation (FQE)** — learns a Q-function for the target policy
  on the logged transitions. Implemented via d3rlpy's
  ``DiscreteFQEConfig``. More sample-efficient but requires the ``rl``
  extra to be installed.

Both estimators output ``(value_estimate, n_transitions, diagnostic)``. The
promotion criteria for the offline policies live in ``docs/RL_RESEARCH.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.learning.rl.env import ACTIONS, behaviour_action_from_row, load_env


@dataclass
class OPEResult:
    """Container for a single off-policy evaluation."""

    estimator: str
    value_estimate: float
    n_transitions: int
    diagnostic: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimator": self.estimator,
            "value_estimate": float(self.value_estimate),
            "n_transitions": int(self.n_transitions),
            "diagnostic": self.diagnostic,
        }


# ---------------------------------------------------------------------------
# Behaviour-policy estimation (simple empirical distribution per row)
# ---------------------------------------------------------------------------


def behaviour_action_probabilities(df: pd.DataFrame) -> np.ndarray:
    """Per-row probability mass over the four actions for the logged policy.

    We treat the strategy + moderation + risk committee as a deterministic
    policy *after* the fact (each row was either a BUY or a QUEUED), but we
    smooth the empirical distribution with a small ``epsilon`` so the
    importance weights stay finite.
    """
    epsilon = 0.05
    probs = np.full((len(df), len(ACTIONS)), epsilon / (len(ACTIONS) - 1), dtype=float)
    for idx, (_, row) in enumerate(df.iterrows()):
        action = behaviour_action_from_row(row)
        probs[idx, :] = epsilon / (len(ACTIONS) - 1)
        probs[idx, action] = 1.0 - epsilon
    return probs


# ---------------------------------------------------------------------------
# Weighted Importance Sampling
# ---------------------------------------------------------------------------


def weighted_importance_sampling(
    df: pd.DataFrame,
    target_policy: Callable[[pd.Series], np.ndarray],
    rewards: np.ndarray | None = None,
) -> OPEResult:
    """WIS estimator on the logged decision rows.

    ``target_policy`` returns an action probability vector for one row. If
    ``rewards`` is omitted we compute it on-the-fly via
    :func:`src.learning.rl.env.compute_reward` for the *behaviour* action,
    so the estimator answers the canonical "would target_policy have done
    better than committee?" question.
    """
    from src.learning.rl.env import RewardConfig, compute_reward

    behaviour_probs = behaviour_action_probabilities(df)
    rewards_arr = (
        np.asarray(rewards, dtype=float)
        if rewards is not None
        else np.asarray(
            [
                compute_reward(row, behaviour_action_from_row(row), config=RewardConfig())[0]
                for _, row in df.iterrows()
            ],
            dtype=float,
        )
    )

    weighted_sum = 0.0
    weight_sum = 0.0
    raw_weights: list[float] = []
    for idx, (_, row) in enumerate(df.iterrows()):
        target_probs = np.asarray(target_policy(row), dtype=float)
        if target_probs.shape != (len(ACTIONS),):
            raise ValueError(
                f"target_policy must return shape ({len(ACTIONS)},); got {target_probs.shape}"
            )
        # Clip to avoid division explosions.
        b_prob = float(np.clip(behaviour_probs[idx, behaviour_action_from_row(row)], 1e-3, None))
        t_prob = float(target_probs[behaviour_action_from_row(row)])
        weight = t_prob / b_prob
        raw_weights.append(weight)
        weighted_sum += weight * rewards_arr[idx]
        weight_sum += weight

    estimate = (weighted_sum / weight_sum) if weight_sum else 0.0
    return OPEResult(
        estimator="wis",
        value_estimate=float(estimate),
        n_transitions=int(len(df)),
        diagnostic={
            "weight_mean": float(np.mean(raw_weights)) if raw_weights else 0.0,
            "weight_max": float(np.max(raw_weights)) if raw_weights else 0.0,
            "effective_sample_size": (float(np.sum(raw_weights) ** 2 / np.sum(np.square(raw_weights))))
            if raw_weights and np.sum(np.square(raw_weights)) > 0
            else 0.0,
        },
    )


# ---------------------------------------------------------------------------
# Fitted Q Evaluation (FQE)
# ---------------------------------------------------------------------------


def fitted_q_evaluation(
    *,
    policy_path: str | Path,
    parquet_path: str | Path | None = None,
    n_steps: int = 2_000,
    seed: int = 42,
) -> OPEResult:
    """FQE estimate using d3rlpy's DiscreteFQE.

    Returns the initial-state value estimate (V(s_0)) for the loaded policy.
    Falls back gracefully if d3rlpy is not installed.
    """
    try:  # pragma: no cover - import gate
        import d3rlpy  # type: ignore
        from d3rlpy.algos import DiscreteCQLConfig  # type: ignore
        from d3rlpy.ope import DiscreteFQEConfig  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "d3rlpy is required for FQE. Install with `poetry install --with rl`."
        ) from exc

    env = load_env(parquet_path)
    from src.learning.rl.env import build_offline_dataset

    bundle = build_offline_dataset(env)
    from d3rlpy.dataset import MDPDataset  # type: ignore

    dataset = MDPDataset(
        observations=bundle["observations"],
        actions=bundle["actions"],
        rewards=bundle["rewards"],
        terminals=bundle["terminals"],
    )
    d3rlpy.seed(seed)
    algo = DiscreteCQLConfig().create(device="cpu:0")
    algo.load(str(policy_path))

    fqe = DiscreteFQEConfig().create(device="cpu:0")
    fqe.fit(
        dataset,
        n_steps=int(n_steps),
        n_steps_per_epoch=max(100, int(n_steps) // 10),
        with_timestamp=False,
        show_progress=False,
    )

    # Estimate V(s_0) via the FQE Q values of the policy's argmax action.
    first_obs = bundle["observations"][:1]
    policy_action = algo.predict(first_obs)
    q_values = fqe.predict_value(first_obs, policy_action)
    value = float(np.asarray(q_values).mean())
    return OPEResult(
        estimator="fqe",
        value_estimate=value,
        n_transitions=int(bundle["actions"].size),
        diagnostic={"n_steps": int(n_steps)},
    )


def write_report(results: list[OPEResult], output_path: str | Path) -> str:
    """Persist a small JSON report for the dashboard."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([r.to_dict() for r in results], indent=2))
    return str(output_path)
