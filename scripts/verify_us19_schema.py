#!/usr/bin/env python3
"""Verify the live US-1.9 conversational workflow schema and Alembic state."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from src.data.database import engine

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "chat_sessions": (
        "id",
        "status",
        "channel_type",
        "channel_session_key",
        "user_id",
        "title",
        "last_channel_type",
        "started_at",
        "last_activity_at",
        "ended_at",
        "context_json",
        "linked_cycle_id",
        "previous_session_id",
    ),
    "chat_turns": (
        "id",
        "session_id",
        "turn_index",
        "role",
        "channel_type",
        "message_text",
        "intent_json",
        "resolution_json",
        "response_json",
        "created_at",
    ),
    "chat_actions": (
        "id",
        "session_id",
        "turn_id",
        "action_type",
        "status",
        "title",
        "ticker",
        "payload_json",
        "preview_text",
        "result_json",
        "requires_confirmation",
        "rejection_reason",
        "expires_at",
        "confirmed_at",
        "executed_at",
        "created_at",
        "updated_at",
        "version",
    ),
    "chat_research_logs": (
        "id",
        "session_id",
        "turn_id",
        "tool_name",
        "provider",
        "query",
        "result_summary",
        "cache_hit",
        "latency_ms",
        "created_at",
    ),
    "chat_workflow_steps": (
        "id",
        "session_id",
        "turn_id",
        "step_key",
        "status",
        "label",
        "detail",
        "provider",
        "model",
        "tool_name",
        "cost_gbp",
        "latency_ms",
        "detail_json",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    ),
    "cost_logs": (
        "chat_session_id",
        "chat_turn_id",
    ),
    "research_logs": (
        "chat_session_id",
        "chat_turn_id",
    ),
}


def get_head_revisions() -> list[str]:
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)
    return sorted(script.get_heads())


def get_current_revisions() -> list[str]:
    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        return []
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    return sorted(str(row[0]) for row in rows)


def build_report() -> dict[str, object]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    head_revisions = get_head_revisions()
    current_revisions = get_current_revisions()

    tables: list[dict[str, object]] = []
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}

    for table_name, required_columns in REQUIRED_COLUMNS.items():
        if table_name not in table_names:
            missing_tables.append(table_name)
            continue

        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        absent = [column for column in required_columns if column not in actual_columns]
        if absent:
            missing_columns[table_name] = absent

        tables.append(
            {
                "table": table_name,
                "columns_ok": not absent,
                "missing_columns": absent,
            }
        )

    current_matches_head = bool(current_revisions) and current_revisions == head_revisions

    return {
        "ok": not missing_tables and not missing_columns and current_matches_head,
        "database_url": str(engine.url),
        "alembic": {
            "current": current_revisions,
            "head": head_revisions,
            "current_matches_head": current_matches_head,
        },
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "tables": tables,
    }


def main() -> int:
    report = build_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
