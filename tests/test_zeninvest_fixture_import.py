from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = PROJECT_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_script = _load_script("build_zeninvest_fixture")
validate_script = _load_script("validate_zeninvest_fixture")


def _write_parquet_inputs(root: Path) -> None:
    root.mkdir(parents=True)
    merged = pd.DataFrame(
        [
            {
                "cycle_id": "cycle-2",
                "ticker": "MSFT_US_EQ",
                "decision_ts": pd.Timestamp("2026-01-02T10:00:00"),
                "decision_action": "QUEUED",
                "conviction": 70,
                "actually_traded": False,
                "trade_pnl_gbp": None,
                "trade_buy_value_gbp": None,
            },
            {
                "cycle_id": "cycle-1",
                "ticker": "AAPL_US_EQ",
                "decision_ts": pd.Timestamp("2026-01-01T10:00:00"),
                "decision_action": "BUY",
                "conviction": 80,
                "actually_traded": True,
                "trade_pnl_gbp": -12.5,
                "trade_buy_value_gbp": 250.0,
            },
            {
                "cycle_id": "cycle-3",
                "ticker": "NVDA_US_EQ",
                "decision_ts": pd.Timestamp("2026-01-03T10:00:00"),
                "decision_action": "QUEUED",
                "conviction": 75,
                "actually_traded": True,
                "trade_pnl_gbp": 5.0,
                "trade_buy_value_gbp": 100.0,
            },
        ]
    )
    merged.to_parquet(root / "merged.parquet", index=False)
    merged[["cycle_id", "ticker", "decision_ts", "decision_action"]].rename(
        columns={"decision_ts": "timestamp", "decision_action": "action"}
    ).to_parquet(root / "decisions.parquet", index=False)
    merged[["cycle_id", "ticker", "decision_ts", "conviction", "decision_action"]].to_parquet(
        root / "features.parquet", index=False
    )
    merged[
        [
            "cycle_id",
            "ticker",
            "decision_ts",
            "actually_traded",
            "trade_pnl_gbp",
            "trade_buy_value_gbp",
        ]
    ].to_parquet(root / "outcomes.parquet", index=False)
    pd.DataFrame(
        [
            {
                "doc_id": "doc-1",
                "cycle_id": "cycle-1",
                "ticker": "AAPL_US_EQ",
                "decision_ts": pd.Timestamp("2026-01-01T10:00:00"),
                "macro_headlines": [{"title": "example"}],
                "body": "reasoning",
            }
        ]
    ).to_parquet(root / "text_corpus.parquet", index=False)
    pd.DataFrame(
        [{"cycle_id": "cycle-r", "ticker": "TSLA_US_EQ", "timestamp": pd.Timestamp("2026-01-04"), "cf_label": "stall"}]
    ).to_parquet(root / "rejected.parquet", index=False)


def test_build_fixture_creates_logged_trades_and_rich_tables(tmp_path: Path) -> None:
    input_dir = tmp_path / "imports" / "v6"
    output = tmp_path / "fixtures" / "investment_agent.db"
    _write_parquet_inputs(input_dir)

    summary = build_script.build_fixture(input_dir, output, replace=True)

    assert summary.logged_trades_rows == 2
    conn = sqlite3.connect(output)
    try:
        rows = conn.execute(
            "SELECT trade_id, signal, notional_gbp, pnl_gbp FROM logged_trades ORDER BY trade_id"
        ).fetchall()
        assert rows == [(1, 1.0, 250.0, -12.5), (2, 0.0, 100.0, 5.0)]
        target_rows = conn.execute(
            "SELECT trade_id, downside_loss_gbp FROM logged_trades_with_target ORDER BY trade_id"
        ).fetchall()
        assert target_rows == [(1, 12.5), (2, 0.0)]
        assert conn.execute("SELECT COUNT(*) FROM text_corpus").fetchone()[0] == 1
    finally:
        conn.close()


def test_validate_fixture_checks_contract_and_counts(tmp_path: Path) -> None:
    input_dir = tmp_path / "imports" / "v6"
    output = tmp_path / "fixtures" / "investment_agent.db"
    _write_parquet_inputs(input_dir)
    build_script.build_fixture(input_dir, output, replace=True)

    result = validate_script.validate_fixture(output, input_dir=input_dir)

    assert result["counts"]["logged_trades"] == 2
    assert result["counts"]["merged"] == 3
    assert result["counts"]["rejected"] == 1


def test_validate_fixture_can_call_optional_zenlab_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_dir = tmp_path / "imports" / "v6"
    output = tmp_path / "fixtures" / "investment_agent.db"
    _write_parquet_inputs(input_dir)
    build_script.build_fixture(input_dir, output, replace=True)

    loader = tmp_path / "fake_loader.py"
    loader.write_text(
        """
import sqlite3

def open_zeninvest_db(path):
    return sqlite3.connect(path)

def load_logged_trades_from_db(conn):
    return conn.execute("SELECT trade_id, signal, notional_gbp, pnl_gbp FROM logged_trades").fetchall()
"""
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    result = validate_script.validate_fixture(
        output,
        input_dir=input_dir,
        loader_module="fake_loader",
        require_loader=True,
    )

    assert result["loader_rows"] == 2


def test_build_fixture_reports_mapping_candidates_when_required_columns_missing(tmp_path: Path) -> None:
    input_dir = tmp_path / "imports" / "v6"
    input_dir.mkdir(parents=True)
    pd.DataFrame({"cycle_id": ["cycle-1"], "pnl": [1.0]}).to_parquet(input_dir / "merged.parquet", index=False)

    with pytest.raises(build_script.FixtureBuildError, match="Available mapping candidates"):
        build_script.build_fixture(input_dir, tmp_path / "fixture.db", replace=True)
