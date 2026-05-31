"""Offline RL training entry points (CQL / IQL).

Wraps the d3rlpy implementations of Conservative Q-Learning (Kumar et al.
2020) and Implicit Q-Learning (Kostrikov et al. 2021), trained on the
``MDPDataset`` produced by :mod:`src.learning.rl.env`.

The promotion criteria live in ``docs/RL_RESEARCH.md``. These models are
**research-only** and never wired into autonomous trading.

Imports are deferred so that callers without the ``rl`` poetry extra can
still import :mod:`src.learning.rl`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from src.learning.rl.env import build_offline_dataset, load_env


@dataclass
class OfflineTrainingResult:
    """Lightweight, JSON-safe summary of an offline training run."""

    algo: str
    n_transitions: int
    n_steps: int
    loss_history: list[float] = field(default_factory=list)
    policy_path: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "algo": self.algo,
            "n_transitions": self.n_transitions,
            "n_steps": self.n_steps,
            "loss_history": list(self.loss_history),
            "policy_path": self.policy_path,
            "metrics": self.metrics,
        }


def _lazy_d3rlpy():
    try:  # pragma: no cover - import gate
        import d3rlpy  # type: ignore

        return d3rlpy
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "d3rlpy is required for offline RL training. "
            "Install with `poetry install --with rl`."
        ) from exc


def _build_mdp_dataset(dataset_bundle: dict[str, np.ndarray]):
    d3rlpy = _lazy_d3rlpy()
    from d3rlpy.dataset import MDPDataset  # type: ignore

    return MDPDataset(
        observations=dataset_bundle["observations"],
        actions=dataset_bundle["actions"],
        rewards=dataset_bundle["rewards"],
        terminals=dataset_bundle["terminals"],
    )


def train_offline(
    *,
    algo: str = "cql",
    n_steps: int = 5_000,
    parquet_path: str | Path | None = None,
    seed: int = 42,
    output_dir: str | Path | None = None,
) -> OfflineTrainingResult:
    """Train CQL or IQL on the logged ZenInvest dataset."""
    algo_name = algo.lower()
    if algo_name not in {"cql", "iql"}:
        raise ValueError(f"Unsupported algo: {algo}; pick 'cql' or 'iql'.")

    d3rlpy = _lazy_d3rlpy()
    env = load_env(parquet_path)
    bundle = build_offline_dataset(env)
    dataset = _build_mdp_dataset(bundle)

    if algo_name == "cql":
        from d3rlpy.algos import DiscreteCQLConfig  # type: ignore

        algo_obj = DiscreteCQLConfig(learning_rate=1e-4).create(device="cpu:0")
    else:
        from d3rlpy.algos import DiscreteBCQConfig  # type: ignore

        # d3rlpy does not have a discrete-action IQL; DiscreteBCQ is the
        # closest behaviour-regularised offline learner for discrete spaces.
        algo_obj = DiscreteBCQConfig().create(device="cpu:0")

    d3rlpy.seed(seed)
    fitter = algo_obj.fit(
        dataset,
        n_steps=int(n_steps),
        n_steps_per_epoch=max(100, int(n_steps) // 10),
        with_timestamp=False,
        show_progress=False,
    )
    loss_history = [float(item.get("loss", 0.0)) for item in fitter or []]

    policy_path: str | None = None
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        policy_path = str(output_dir / f"{algo_name}.d3")
        algo_obj.save(policy_path)
        with open(output_dir / f"{algo_name}.metadata.json", "w") as fh:
            json.dump(
                {
                    "algo": algo_name,
                    "n_steps": int(n_steps),
                    "n_transitions": int(bundle["actions"].size),
                    "seed": int(seed),
                },
                fh,
                indent=2,
            )

    return OfflineTrainingResult(
        algo=algo_name,
        n_transitions=int(bundle["actions"].size),
        n_steps=int(n_steps),
        loss_history=loss_history,
        policy_path=policy_path,
        metrics={"final_loss": loss_history[-1] if loss_history else None},
    )
