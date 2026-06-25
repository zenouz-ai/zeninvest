#!/usr/bin/env python3
"""Build a Zenlab-compatible SQLite fixture from ZenInvest parquet exports."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERSION = "v6"
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "zeninvest_imports" / DEFAULT_VERSION
DEFAULT_OUTPUT = PROJECT_ROOT / "fixtures" / "dev" / "investment_agent.db"

PARQUET_TABLES = ("decisions", "features", "outcomes", "merged", "text_corpus", "rejected")
LOGGED_TRADES_COLUMNS = ("trade_id", "signal", "notional_gbp", "pnl_gbp")
LOGGED_TRADES_REQUIRED_SOURCE_COLUMNS = (
    "cycle_id",
    "ticker",
    "decision_ts",
    "decision_action",
    "actually_traded",
    "trade_pnl_gbp",
    "trade_buy_value_gbp",
)
ACTION_SIGNAL_MAP = {"BUY": 1.0, "QUEUED": 0.0}


class FixtureBuildError(RuntimeError):
    """Raised when staged parquet cannot be converted safely."""


@dataclass(frozen=True)
class BuildSummary:
    output: Path
    source_dir: Path
    table_counts: dict[str, int]
    logged_trades_rows: int


def _candidate_columns(columns: list[str], needles: tuple[str, ...]) -> list[str]:
    lowered = [(col, col.lower()) for col in columns]
    return [col for col, lower in lowered if any(needle in lower for needle in needles)]


def _require_columns(df: pd.DataFrame, required: tuple[str, ...], *, source_name: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if not missing:
        return
    candidates = {
        "pnl": _candidate_columns(list(df.columns), ("pnl", "profit", "loss")),
        "notional": _candidate_columns(list(df.columns), ("notional", "value", "amount", "allocation")),
        "signal": _candidate_columns(list(df.columns), ("signal", "action", "decision", "conviction")),
        "trade_id": _candidate_columns(list(df.columns), ("trade", "id", "cycle", "ticker")),
    }
    raise FixtureBuildError(
        f"{source_name} is missing required columns {missing}. "
        f"Available mapping candidates: {json.dumps(candidates, sort_keys=True)}"
    )


def _truthy_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(float) != 0.0
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "t", "yes", "y"})


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return value


def _sqlite_ready_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].map(_sqlite_value)
        elif out[column].dtype == "object":
            out[column] = out[column].map(_sqlite_value)
    return out


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FixtureBuildError(f"Missing parquet file: {path}")
    try:
        return pd.read_parquet(path)
    except ImportError as exc:
        raise FixtureBuildError(
            "Reading parquet requires pyarrow. Install with: poetry install --with learning-data"
        ) from exc


def _build_logged_trades(merged: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        merged,
        LOGGED_TRADES_REQUIRED_SOURCE_COLUMNS,
        source_name="merged.parquet",
    )
    traded = merged[_truthy_series(merged["actually_traded"])].copy()
    traded = traded[
        traded["trade_pnl_gbp"].notna()
        & traded["trade_buy_value_gbp"].notna()
        & traded["decision_action"].notna()
    ].copy()
    if traded.empty:
        raise FixtureBuildError("No realized trade rows found for logged_trades.")

    traded["_decision_action_upper"] = traded["decision_action"].astype(str).str.upper()
    unknown_actions = sorted(set(traded["_decision_action_upper"]) - set(ACTION_SIGNAL_MAP))
    if unknown_actions:
        raise FixtureBuildError(
            "Cannot derive signal for unexpected decision_action values: "
            f"{unknown_actions}. Update ACTION_SIGNAL_MAP deliberately."
        )

    sort_cols = [col for col in ("decision_ts", "cycle_id", "ticker") if col in traded.columns]
    traded = traded.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    logged = pd.DataFrame(
        {
            "trade_id": range(1, len(traded) + 1),
            "signal": traded["_decision_action_upper"].map(ACTION_SIGNAL_MAP).astype(float).to_numpy(),
            "notional_gbp": pd.to_numeric(traded["trade_buy_value_gbp"], errors="coerce"),
            "pnl_gbp": pd.to_numeric(traded["trade_pnl_gbp"], errors="coerce"),
        }
    )
    null_counts = logged[list(LOGGED_TRADES_COLUMNS)].isna().sum()
    bad = {col: int(count) for col, count in null_counts.items() if count}
    if bad:
        raise FixtureBuildError(f"logged_trades mapping produced NULL values: {bad}")
    return logged


def _write_metadata(
    conn: sqlite3.Connection,
    *,
    source_dir: Path,
    table_counts: dict[str, int],
    logged_trades_rows: int,
) -> None:
    mapping = {
        "source_table": "merged",
        "row_filter": "actually_traded=true and trade_pnl_gbp/trade_buy_value_gbp/decision_action are non-null",
        "trade_id": "1-based stable row number after sorting by decision_ts, cycle_id, ticker",
        "signal": {"BUY": 1.0, "QUEUED": 0.0},
        "notional_gbp": "trade_buy_value_gbp",
        "pnl_gbp": "trade_pnl_gbp",
        "target": "logged_trades_with_target.downside_loss_gbp = max(0, -pnl_gbp)",
    }
    rows = [
        ("generated_at", datetime.now(timezone.utc).isoformat()),
        ("source_dir", str(source_dir)),
        ("table_counts_json", json.dumps(table_counts, sort_keys=True)),
        ("logged_trades_rows", str(logged_trades_rows)),
        ("logged_trades_mapping_json", json.dumps(mapping, sort_keys=True)),
    ]
    conn.execute("DROP TABLE IF EXISTS zeninvest_import_metadata")
    conn.execute("CREATE TABLE zeninvest_import_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.executemany("INSERT INTO zeninvest_import_metadata (key, value) VALUES (?, ?)", rows)


def build_fixture(input_dir: Path, output: Path, *, replace: bool = False) -> BuildSummary:
    input_dir = input_dir.resolve()
    output = output.resolve()
    if not input_dir.is_dir():
        raise FixtureBuildError(f"Input directory does not exist: {input_dir}")
    if output.exists() and not replace:
        raise FixtureBuildError(f"Output already exists: {output}. Pass --replace to overwrite it.")

    loaded: dict[str, pd.DataFrame] = {}
    for table in PARQUET_TABLES:
        path = input_dir / f"{table}.parquet"
        if path.exists():
            loaded[table] = _read_parquet(path)
    if "merged" not in loaded:
        raise FixtureBuildError(f"merged.parquet is required in {input_dir}")

    logged_trades = _build_logged_trades(loaded["merged"])
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_name(f".{output.name}.tmp")
    if tmp_output.exists():
        tmp_output.unlink()

    conn = sqlite3.connect(str(tmp_output))
    try:
        table_counts: dict[str, int] = {}
        for table, df in loaded.items():
            ready = _sqlite_ready_frame(df)
            ready.to_sql(table, conn, if_exists="replace", index=False)
            table_counts[table] = int(len(df))

        logged_trades.to_sql("logged_trades", conn, if_exists="replace", index=False)
        conn.execute("DROP VIEW IF EXISTS logged_trades_with_target")
        conn.execute(
            """
            CREATE VIEW logged_trades_with_target AS
            SELECT
                trade_id,
                signal,
                notional_gbp,
                pnl_gbp,
                MAX(0.0, -pnl_gbp) AS downside_loss_gbp
            FROM logged_trades
            """
        )
        _write_metadata(
            conn,
            source_dir=input_dir,
            table_counts=table_counts,
            logged_trades_rows=int(len(logged_trades)),
        )
        conn.commit()
    finally:
        conn.close()

    if output.exists():
        output.unlink()
    tmp_output.replace(output)
    return BuildSummary(
        output=output,
        source_dir=input_dir,
        table_counts=table_counts,
        logged_trades_rows=int(len(logged_trades)),
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true", help="Overwrite the output SQLite file if it exists.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = build_fixture(args.input_dir, args.output, replace=args.replace)
    except FixtureBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "output": str(summary.output),
                "source_dir": str(summary.source_dir),
                "table_counts": summary.table_counts,
                "logged_trades_rows": summary.logged_trades_rows,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
