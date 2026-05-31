"""Tests for champion/challenger counterfactual evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.data.database import engine, get_session
from src.data.models import Base, LearningEvaluationRun
from src.learning.evaluation.counterfactual import run_counterfactual_evaluation
from src.learning.evaluation.gates import check_promotion_gates
from src.learning.evaluation.policies import PolicyId


@pytest.fixture
def eval_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path))
    root = tmp_path
    parquet_dir = root / "data" / "learning" / "parquet" / "v2"
    exports_dir = root / "data" / "learning" / "exports" / "v2"
    parquet_dir.mkdir(parents=True)
    exports_dir.mkdir(parents=True)

    rows = []
    for i in range(10):
        label = ["big_winner", "big_loser", "neutral", "stall"][i % 4]
        pnl = 50.0 if label == "big_winner" else (-50.0 if label == "big_loser" else 5.0)
        rows.append(
            {
                "cycle_id": f"c{i}",
                "ticker": f"T{i}_US_EQ",
                "decision_ts": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "action": "BUY",
                "conviction": 40 + i * 5,
                "label_3class": label,
                "ret_30d": pnl,
                "actually_traded": i % 2 == 0,
                "trade_pnl_gbp": pnl if i % 2 == 0 else None,
                "realized_pnl_pct": pnl if i % 2 == 0 else None,
            }
        )
    df = pd.DataFrame(rows)
    df.to_parquet(parquet_dir / "merged.parquet", index=False)

    with open(exports_dir / "memory_bundle.jsonl", "w", encoding="utf-8") as fh:
        for i, row in enumerate(rows):
            fh.write(
                json.dumps(
                    {
                        "doc_id": f"d{i}",
                        "ticker": row["ticker"],
                        "label_3class": row["label_3class"],
                        "metadata": {"label_3class": row["label_3class"]},
                    }
                )
                + "\n"
            )

    Base.metadata.create_all(bind=engine)
    return root


def test_counterfactual_evaluation_completes(eval_sandbox) -> None:
    result = run_counterfactual_evaluation(
        project_root=eval_sandbox,
        run_id="eval-test",
        policies=[
            PolicyId.CHAMPION_AS_IS,
            PolicyId.CHALLENGER_GBM,
            PolicyId.CHALLENGER_MEMORY,
            PolicyId.CHALLENGER_COMBINED,
        ],
    )
    assert result["status"] == "completed"
    assert result["n_rows"] == 10
    assert PolicyId.CHAMPION_AS_IS.value in result["policies"]
    assert PolicyId.CHALLENGER_COMBINED.value in result["policies"]
    assert "gates" in result
    assert (eval_sandbox / "data" / "learning" / "evaluation" / "eval-test" / "metrics.json").exists()

    session = get_session()
    try:
        row = session.query(LearningEvaluationRun).filter(LearningEvaluationRun.run_id == "eval-test").first()
        assert row is not None
        assert row.n_rows == 10
    finally:
        session.close()


def test_promotion_gates_low_sample_not_ready(eval_sandbox) -> None:
    result = run_counterfactual_evaluation(project_root=eval_sandbox, run_id="eval-gates")
    gates = check_promotion_gates(
        evaluation_metrics=result,
        closed_trades=int(result.get("closed_trades") or 0),
    )
    assert gates.tiers[0].passed is True
    assert gates.promotion_ready is False
    assert "Not promotion-ready" in gates.summary or "Continue shadow" in gates.summary
