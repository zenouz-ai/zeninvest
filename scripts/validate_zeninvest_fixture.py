#!/usr/bin/env python3
"""Validate a Zenlab-compatible SQLite fixture built from ZenInvest parquet."""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERSION = "v6"
DEFAULT_DB = PROJECT_ROOT / "fixtures" / "dev" / "investment_agent.db"
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "zeninvest_imports" / DEFAULT_VERSION
REQUIRED_LOGGED_TRADES_COLUMNS = ("trade_id", "signal", "notional_gbp", "pnl_gbp")
RICH_TABLES = ("decisions", "features", "outcomes", "merged", "text_corpus", "rejected")


class ValidationError(RuntimeError):
    """Raised when the fixture does not satisfy the import contract."""


def _relation_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table', 'view')",
        (name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, relation: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{relation}")').fetchall()]


def _count(conn: sqlite3.Connection, relation: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{relation}"').fetchone()[0])


def _validate_logged_trades(conn: sqlite3.Connection) -> dict[str, int]:
    if not _relation_exists(conn, "logged_trades"):
        raise ValidationError("logged_trades table/view is missing.")
    columns = _columns(conn, "logged_trades")
    missing = [col for col in REQUIRED_LOGGED_TRADES_COLUMNS if col not in columns]
    if missing:
        raise ValidationError(f"logged_trades missing required columns: {missing}")
    rows = _count(conn, "logged_trades")
    if rows <= 0:
        raise ValidationError("logged_trades has zero rows.")
    null_counts: dict[str, int] = {}
    for column in REQUIRED_LOGGED_TRADES_COLUMNS:
        null_count = int(
            conn.execute(f'SELECT COUNT(*) FROM "logged_trades" WHERE "{column}" IS NULL').fetchone()[0]
        )
        if null_count:
            null_counts[column] = null_count
    if null_counts:
        raise ValidationError(f"logged_trades required columns contain NULLs: {null_counts}")
    return {"logged_trades": rows}


def _validate_rich_table_counts(conn: sqlite3.Connection, input_dir: Path | None) -> dict[str, int]:
    if input_dir is None:
        return {}
    if not input_dir.is_dir():
        raise ValidationError(f"Input directory does not exist: {input_dir}")
    counts: dict[str, int] = {}
    for table in RICH_TABLES:
        parquet_path = input_dir / f"{table}.parquet"
        if not parquet_path.exists():
            continue
        if not _relation_exists(conn, table):
            raise ValidationError(f"Expected rich table is missing from SQLite: {table}")
        expected = int(len(pd.read_parquet(parquet_path)))
        actual = _count(conn, table)
        if actual != expected:
            raise ValidationError(f"Row-count mismatch for {table}: expected {expected}, got {actual}")
        counts[table] = actual
    return counts


def _load_with_optional_zenlab_loader(db_path: Path, module_name: str | None, *, required: bool) -> int | None:
    if not module_name:
        if required:
            raise ValidationError("--require-loader was passed without --loader-module.")
        return None
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        if required:
            raise ValidationError(f"Could not import loader module {module_name!r}: {exc}") from exc
        return None
    missing = [name for name in ("open_zeninvest_db", "load_logged_trades_from_db") if not hasattr(module, name)]
    if missing:
        raise ValidationError(f"Loader module {module_name!r} missing expected functions: {missing}")

    open_db = getattr(module, "open_zeninvest_db")
    load_trades = getattr(module, "load_logged_trades_from_db")
    handle: Any | None = None
    try:
        handle = open_db(db_path)
    except TypeError:
        handle = open_db(str(db_path))

    try:
        try:
            loaded = load_trades(handle)
        except TypeError:
            loaded = load_trades(str(db_path))
        try:
            count = len(loaded)
        except TypeError:
            count = int(sum(1 for _ in loaded))
        if count <= 0:
            raise ValidationError(f"{module_name}.load_logged_trades_from_db returned no rows.")
        return count
    finally:
        close = getattr(handle, "close", None)
        if callable(close):
            close()


def validate_fixture(
    db_path: Path,
    *,
    input_dir: Path | None = None,
    loader_module: str | None = None,
    require_loader: bool = False,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise ValidationError(f"SQLite fixture does not exist: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        counts = _validate_logged_trades(conn)
        counts.update(_validate_rich_table_counts(conn, input_dir.resolve() if input_dir else None))
    finally:
        conn.close()
    loader_rows = _load_with_optional_zenlab_loader(db_path, loader_module, required=require_loader)
    return {
        "db": str(db_path),
        "counts": counts,
        "loader_module": loader_module,
        "loader_rows": loader_rows,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--loader-module", default=None)
    parser.add_argument("--require-loader", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = validate_fixture(
            args.db,
            input_dir=args.input_dir,
            loader_module=args.loader_module,
            require_loader=args.require_loader,
        )
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
