"""Gymnasium environment that replays logged ZenInvest decisions.

This is a **FinRL-style offline-RL surface** built on the parquet bundle
produced by :mod:`src.learning.dataset.builder`. Each parquet row becomes one
(state, action, reward, next-state) tuple:

- State: the leakage-safe feature vector for the decision row
  (everything ``label_columns`` excludes).
- Logged behaviour action: derived from ``decision_action`` —
  ``BUY -> buy_full``, ``QUEUED -> queue``. We treat the strategy +
  moderation + risk committee as a single behaviour policy.
- Reward: MTM forward return at ``ret_30d`` (in %), shaped by realized P&L on
  closed trades. The reward scale is documented in ``docs/RL_RESEARCH.md``.

The environment exposes a simple discrete action space
``{0: skip, 1: queue, 2: buy_small, 3: buy_full}`` so policies that
recommend ``skip`` or ``buy_small`` produce a counterfactual reward via the
mark-to-market columns (we do not have logged data for the other actions, so
the env explicitly returns ``info["counterfactual"] = True`` and a damped
reward in those cases).

The env is **not** an interactive trading simulator — it replays one
historical decision per step. For a closed-loop backtest use
:mod:`src.backtesting.engine` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

# Lazy gymnasium import: callers without the `rl` extra can still import
# everything else in src.learning.rl.
try:  # pragma: no cover - import gate
    import gymnasium as gym
    from gymnasium import spaces

    _GYM_AVAILABLE = True
except ImportError:  # pragma: no cover
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _GYM_AVAILABLE = False


# ---------------------------------------------------------------------------
# Action / behaviour-policy mapping
# ---------------------------------------------------------------------------

ACTIONS: tuple[str, ...] = ("skip", "queue", "buy_small", "buy_full")
ACTION_TO_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(ACTIONS)}


def behaviour_action_from_row(row: pd.Series) -> int:
    """Map a logged decision row to its discrete behaviour-policy action."""
    decision = str(row.get("decision_action") or "").upper()
    if decision == "BUY":
        return ACTION_TO_INDEX["buy_full"]
    if decision == "QUEUED":
        return ACTION_TO_INDEX["queue"]
    # We never log skip/buy_small directly. Treat anything else as `skip` so
    # downstream learners see a discrete behaviour distribution.
    return ACTION_TO_INDEX["skip"]


# ---------------------------------------------------------------------------
# Reward shaping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RewardConfig:
    """Reward shaping for the four discrete actions.

    ``primary_return_col`` is the MTM 30-day return. When ``realized_pnl_pct``
    is present we replace it (with a configurable ``realized_weight``) so
    closed trades contribute their final P&L instead of the marked one.
    """

    primary_return_col: str = "ret_30d"
    realized_return_col: str = "realized_pnl_pct"
    realized_weight: float = 1.0
    # Counterfactual penalties: actions we never observed get a damped
    # reward to discourage the learner from fabricating policy improvements
    # that the data cannot validate.
    counterfactual_damping: float = 0.5
    skip_reward: float = 0.0
    buy_small_scale: float = 0.5
    cost_basis_pct: float = 0.05  # transaction-cost proxy applied to buys


def compute_reward(
    row: pd.Series,
    action_idx: int,
    *,
    config: RewardConfig = RewardConfig(),
) -> tuple[float, bool]:
    """Return ``(reward, counterfactual)`` for one (row, action) pair."""
    action = ACTIONS[action_idx]
    realized = row.get(config.realized_return_col)
    mtm = row.get(config.primary_return_col)
    if pd.notna(realized):
        base = float(realized) * config.realized_weight
    elif pd.notna(mtm):
        base = float(mtm)
    else:
        return 0.0, action != ACTIONS[behaviour_action_from_row(row)]

    behaviour = behaviour_action_from_row(row)
    if action == "skip":
        return float(config.skip_reward), behaviour != ACTION_TO_INDEX["skip"]
    if action == "queue":
        # Queueing keeps the option open; reward the MTM ret without the
        # transaction cost.
        return float(base), behaviour != ACTION_TO_INDEX["queue"]
    if action == "buy_full":
        reward = base - config.cost_basis_pct
        if behaviour == ACTION_TO_INDEX["buy_full"]:
            return float(reward), False
        return float(reward * config.counterfactual_damping), True
    if action == "buy_small":
        reward = base * config.buy_small_scale - config.cost_basis_pct
        return float(reward * config.counterfactual_damping), True
    return 0.0, True


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@dataclass
class EpisodeMetrics:
    """Aggregate metrics returned by ``DecisionReplayEnv.summary()``."""

    total_steps: int = 0
    total_reward: float = 0.0
    behaviour_match_rate: float = 0.0
    counterfactual_rate: float = 0.0
    action_counts: dict[str, int] = field(default_factory=dict)


class DecisionReplayEnv:  # pragma: no cover - exercised in unit test
    """Offline replay env over the merged learning parquet.

    Sub-classes ``gymnasium.Env`` when the ``rl`` extra is installed and
    falls back to a plain class otherwise, so importing the module does not
    require gymnasium.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        df: pd.DataFrame,
        *,
        feature_columns: Sequence[str] | None = None,
        reward_config: RewardConfig | None = None,
        shuffle: bool = False,
        seed: int = 42,
    ) -> None:
        if df.empty:
            raise ValueError("DecisionReplayEnv requires a non-empty DataFrame")
        self.df = df.copy().sort_values("decision_ts").reset_index(drop=True)
        self.reward_config = reward_config or RewardConfig()
        self.feature_columns = list(feature_columns) if feature_columns else self._auto_features()
        self.shuffle = bool(shuffle)
        self._rng = np.random.default_rng(seed)
        self._order = np.arange(len(self.df))
        self._cursor = 0
        self._last_reward = 0.0
        self._action_counts: dict[str, int] = {a: 0 for a in ACTIONS}
        self._behaviour_match = 0
        self._counterfactual = 0

        if _GYM_AVAILABLE:
            self.action_space = spaces.Discrete(len(ACTIONS))
            self.observation_space = spaces.Box(
                low=-np.inf,
                high=np.inf,
                shape=(len(self.feature_columns),),
                dtype=np.float32,
            )
        else:  # pragma: no cover - gymnasium missing branch
            self.action_space = None
            self.observation_space = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self._order = np.arange(len(self.df))
        if self.shuffle:
            self._rng.shuffle(self._order)
        self._cursor = 0
        self._action_counts = {a: 0 for a in ACTIONS}
        self._behaviour_match = 0
        self._counterfactual = 0
        obs = self._observation(self._order[self._cursor])
        info = self._info(self._order[self._cursor])
        return obs, info

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        if not 0 <= int(action) < len(ACTIONS):
            raise ValueError(f"Action {action} out of range")
        row_idx = int(self._order[self._cursor])
        row = self.df.iloc[row_idx]
        reward, counterfactual = compute_reward(
            row, int(action), config=self.reward_config
        )
        self._last_reward = reward
        self._action_counts[ACTIONS[int(action)]] += 1
        behaviour = behaviour_action_from_row(row)
        if behaviour == int(action):
            self._behaviour_match += 1
        if counterfactual:
            self._counterfactual += 1
        info = self._info(row_idx)
        info["reward_counterfactual"] = counterfactual
        info["behaviour_action"] = behaviour
        info["row_index"] = row_idx
        self._cursor += 1
        terminated = self._cursor >= len(self.df)
        next_obs = (
            self._observation(self._order[self._cursor]) if not terminated else np.zeros_like(
                self._observation(row_idx)
            )
        )
        return next_obs, reward, terminated, False, info

    def summary(self) -> EpisodeMetrics:
        total_steps = sum(self._action_counts.values())
        return EpisodeMetrics(
            total_steps=int(total_steps),
            total_reward=float(self._last_reward),  # last-step reward; cumulative tracked via callbacks
            behaviour_match_rate=(self._behaviour_match / total_steps) if total_steps else 0.0,
            counterfactual_rate=(self._counterfactual / total_steps) if total_steps else 0.0,
            action_counts=dict(self._action_counts),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _auto_features(self) -> list[str]:
        exclude = {
            "cycle_id",
            "ticker",
            "decision_ts",
            "label_3class",
            "ret_3d",
            "ret_10d",
            "ret_30d",
            "mtm_max_drawdown_3d",
            "mtm_max_drawdown_10d",
            "mtm_max_drawdown_30d",
            "mtm_max_runup_3d",
            "mtm_max_runup_10d",
            "mtm_max_runup_30d",
            "realized_pnl_pct",
            "realized_holding_days",
            "exit_reason",
            "actually_traded",
        }
        return [
            c
            for c in self.df.columns
            if c not in exclude and pd.api.types.is_numeric_dtype(self.df[c])
        ]

    def _observation(self, row_index: int) -> np.ndarray:
        row = self.df.iloc[row_index]
        values = []
        for col in self.feature_columns:
            v = row.get(col)
            try:
                values.append(float(v) if pd.notna(v) else 0.0)
            except (TypeError, ValueError):
                values.append(0.0)
        return np.asarray(values, dtype=np.float32)

    def _info(self, row_index: int) -> dict[str, Any]:
        row = self.df.iloc[row_index]
        return {
            "decision_ts": row.get("decision_ts"),
            "cycle_id": row.get("cycle_id"),
            "ticker": row.get("ticker"),
            "label_3class": row.get("label_3class"),
            "decision_action": row.get("decision_action"),
        }


# Pretend to subclass gymnasium.Env when available — keeps callers happy
# without forcing the import at module load.
if _GYM_AVAILABLE:  # pragma: no cover
    class _GymCompatibleEnv(DecisionReplayEnv, gym.Env):  # type: ignore[misc]
        pass

    DecisionReplayEnv = _GymCompatibleEnv  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Convenience loader
# ---------------------------------------------------------------------------


def load_env(
    parquet_path: str | Path | None = None,
    **kwargs: Any,
) -> DecisionReplayEnv:
    """Load the env from the canonical parquet bundle."""
    parquet_path = (
        Path(parquet_path)
        if parquet_path
        else Path(__file__).resolve().parents[3] / "data" / "learning" / "parquet" / "v1" / "merged.parquet"
    )
    if not parquet_path.exists():
        raise FileNotFoundError(f"Merged parquet not found at {parquet_path}; run `cli build` first.")
    df = pd.read_parquet(parquet_path)
    return DecisionReplayEnv(df, **kwargs)


def build_offline_dataset(
    env: DecisionReplayEnv,
    *,
    policy: str = "behaviour",
) -> dict[str, np.ndarray]:
    """Build an offline (state, action, reward, next_state, done) bundle.

    ``policy='behaviour'`` follows the logged committee action (the canonical
    use case for offline RL training). Other strings raise — extending this
    is the job of :mod:`src.learning.rl.offline`.
    """
    if policy != "behaviour":
        raise ValueError(f"Unsupported policy for dataset construction: {policy}")
    obs_list: list[np.ndarray] = []
    actions: list[int] = []
    rewards: list[float] = []
    next_obs_list: list[np.ndarray] = []
    dones: list[bool] = []
    obs, _ = env.reset()
    while True:
        row_idx = int(env._order[env._cursor])
        action = behaviour_action_from_row(env.df.iloc[row_idx])
        obs_list.append(np.asarray(obs))
        actions.append(int(action))
        next_obs, reward, terminated, _, _ = env.step(action)
        rewards.append(float(reward))
        next_obs_list.append(np.asarray(next_obs))
        dones.append(bool(terminated))
        if terminated:
            break
        obs = next_obs
    return {
        "observations": np.asarray(obs_list, dtype=np.float32),
        "actions": np.asarray(actions, dtype=np.int64),
        "rewards": np.asarray(rewards, dtype=np.float32),
        "next_observations": np.asarray(next_obs_list, dtype=np.float32),
        "terminals": np.asarray(dones, dtype=np.float32),
    }
