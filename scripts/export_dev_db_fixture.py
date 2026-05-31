#!/usr/bin/env python3
"""Export a sanitized dev SQLite fixture from the live production database.

Creates fixtures/dev/investment_agent.db suitable for Claude Code analytics and
dashboard smoke tests. Strips secrets, chat logs, bulk caches, and large LLM blobs.

Usage:
    poetry run python scripts/export_dev_db_fixture.py
    poetry run python scripts/export_dev_db_fixture.py --source /path/to/live.db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "investment_agent.db"
FIXTURE_DIR = PROJECT_ROOT / "fixtures" / "dev"
TMP_DB = FIXTURE_DIR / ".tmp.db"
OUTPUT_DB = FIXTURE_DIR / "investment_agent.db"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"

TABLES_TO_DELETE = [
    "chat_sessions",
    "chat_turns",
    "chat_actions",
    "chat_research_logs",
    "chat_workflow_steps",
    "slack_command_log",
    "notification_logs",
    "evolution_approvals",
    "evolution_artifacts",
    "evolution_deployments",
    "evolution_messages",
    "evolution_plans",
    "evolution_requests",
    "evolution_runs",
    "intent_detection_cache",
    "api_logs",
    "market_data_cache",
    "news_sentiment_cache",
    "events_log",
    "research_logs",
    "run_dataset_audits",
    "decision_shadow_scores",
    "learning_evaluation_runs",
    "learning_export_runs",
    "learning_runs",
    "apscheduler_jobs",
    "macro_headlines",
    "macro_signal_logs",
]

BLOB_COLUMNS_TO_NULL: dict[str, list[str]] = {
    "strategy_decisions": [
        "raw_response_json",
        "reasoning",
        "market_assessment",
        "portfolio_commentary",
        "news_sentiment_summary",
        "catalysts_json",
        "risks_json",
        "exit_conditions",
    ],
    "moderation_logs": ["reasoning", "modifications_json"],
    "risk_decisions": [
        "rules_checked_json",
        "triggered_rules_json",
        "reasoning",
        "portfolio_state_json",
    ],
    "orders": ["warning_note", "error_message"],
    "portfolio_snapshots": ["positions_json"],
    "opportunity_score_snapshots": ["top_signals_json"],
    "macro_state": [
        "action_plan_json",
        "sector_summary",
        "economic_highlights",
        "raw_payload_json",
    ],
    "macro_headlines": ["url"],
    "guidance_snapshots": [
        "prompt_guidance_summary",
        "applied_screening_bias_json",
        "pre_guidance_sector_distribution_json",
        "post_guidance_sector_distribution_json",
        "active_strategy_episode_ids_json",
    ],
    "guidance_sector_scores": ["rationale", "evidence_json"],
    "cycle_context_snapshots": [
        "prompt_guidance_summary",
        "applied_screening_bias_json",
        "pre_guidance_sector_distribution_json",
        "post_guidance_sector_distribution_json",
        "active_strategy_episode_ids_json",
    ],
    "strategy_change_episodes": ["summary", "notes", "metadata_json"],
    "strategy_change_evidence": ["rationale", "evidence_summary_json", "raw_payload_json"],
    "stop_loss_adjustments": ["reason", "metadata_json"],
    "trade_outcomes": ["metadata_json"],
    "system_state": ["peak_inflation_warning_note", "notes"],
    "instruments": ["business_summary"],
}

# NOT NULL text/json columns: use placeholders instead of NULL
BLOB_COLUMNS_TO_REDACT: dict[str, dict[str, str]] = {
    "macro_state": {"top_signals_json": "[]"},
}

SANITIZATION_NOTES = [
    "Sensitive tables removed: chat, Slack, notifications, evolution, intent cache.",
    "Bulk audit/cache tables removed: api_logs, market_data_cache, news_sentiment_cache, events_log, research_logs, learning_*, apscheduler_jobs.",
    "Large TEXT/JSON blobs nulled in retained analytics tables (strategy_decisions.raw_response_json stripped).",
    "Instrument rows trimmed to those referenced by orders, strategy_decisions, or portfolio_snapshots.",
    "Journal mode set to DELETE (no WAL sidecar files). Fixture is read-only (chmod 444).",
]


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _backup_source(source: Path, dest: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Source database not found: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    conn = sqlite3.connect(str(source))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        conn.close()


def _delete_tables(conn: sqlite3.Connection, tables: list[str]) -> list[str]:
    deleted: list[str] = []
    conn.execute("PRAGMA foreign_keys=OFF")
    for table in tables:
        if _table_exists(conn, table):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            deleted.append(table)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    return deleted


def _null_blob_columns(conn: sqlite3.Connection) -> list[str]:
    actions: list[str] = []
    for table, columns in BLOB_COLUMNS_TO_NULL.items():
        if not _table_exists(conn, table):
            continue
        for column in columns:
            if not _column_exists(conn, table, column):
                continue
            conn.execute(f"UPDATE {table} SET {column} = NULL")
            actions.append(f"{table}.{column}=NULL")
    for table, columns in BLOB_COLUMNS_TO_REDACT.items():
        if not _table_exists(conn, table):
            continue
        for column, placeholder in columns.items():
            if not _column_exists(conn, table, column):
                continue
            conn.execute(f"UPDATE {table} SET {column} = ?", (placeholder,))
            actions.append(f"{table}.{column}=[redacted]")
    conn.commit()
    return actions


def _trim_instruments(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "instruments"):
        return 0
    before = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
    conn.execute(
        """
        DELETE FROM instruments
        WHERE ticker NOT IN (
            SELECT DISTINCT ticker FROM orders WHERE ticker IS NOT NULL
            UNION
            SELECT DISTINCT ticker FROM strategy_decisions WHERE ticker IS NOT NULL
            UNION
            SELECT DISTINCT json_extract(je.value, '$.ticker')
            FROM portfolio_snapshots ps
            CROSS JOIN json_each(ps.positions_json) AS je
            WHERE ps.positions_json IS NOT NULL
              AND json_extract(je.value, '$.ticker') IS NOT NULL
        )
        """
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
    return before - after


def _finalize_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("VACUUM")
    conn.commit()


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    counts: dict[str, int] = {}
    for (table,) in tables:
        if table.startswith("sqlite_"):
            continue
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_fixture(source: Path = DEFAULT_SOURCE) -> Path:
    print(f"Backing up {source} -> {TMP_DB}")
    _backup_source(source, TMP_DB)

    conn = sqlite3.connect(str(TMP_DB))
    try:
        deleted = _delete_tables(conn, TABLES_TO_DELETE)
        print(f"Dropped {len(deleted)} tables")

        trimmed = _trim_instruments(conn)
        print(f"Removed {trimmed} unreferenced instrument rows")

        nulled = _null_blob_columns(conn)
        print(f"Nulled {len(nulled)} blob columns")

        _finalize_db(conn)
        row_counts = _row_counts(conn)
    finally:
        conn.close()

    if OUTPUT_DB.exists():
        OUTPUT_DB.chmod(0o644)
        OUTPUT_DB.unlink()
    TMP_DB.rename(OUTPUT_DB)
    OUTPUT_DB.chmod(0o444)

    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source),
        "git_commit": _git_commit(),
        "output_path": str(OUTPUT_DB.relative_to(PROJECT_ROOT)),
        "sha256": _sha256(OUTPUT_DB),
        "size_bytes": OUTPUT_DB.stat().st_size,
        "tables_deleted": deleted,
        "blob_columns_nulled": nulled,
        "instruments_removed": trimmed,
        "row_counts": row_counts,
        "sanitization_notes": SANITIZATION_NOTES,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    size_mb = OUTPUT_DB.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUTPUT_DB} ({size_mb:.1f} MB)")
    print(f"Wrote {MANIFEST_PATH}")
    return OUTPUT_DB


def main() -> int:
    parser = argparse.ArgumentParser(description="Export sanitized dev DB fixture")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Live SQLite path (default: {DEFAULT_SOURCE})",
    )
    args = parser.parse_args()

    try:
        export_fixture(args.source.resolve())
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
