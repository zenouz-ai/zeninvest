"""Schema contract coverage for the US-1.9 conversational workflow."""

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base


def test_us19_schema_contract_includes_chat_tables_and_attribution_columns():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        inspector = inspect(engine)

        expected_tables = {
            "chat_sessions": {
                "context_json",
                "previous_session_id",
            },
            "chat_turns": {
                "intent_json",
                "resolution_json",
                "response_json",
            },
            "chat_actions": {
                "requires_confirmation",
                "expires_at",
                "version",
            },
            "chat_research_logs": {
                "tool_name",
                "provider",
                "cache_hit",
            },
            "chat_workflow_steps": {
                "step_key",
                "status",
                "detail_json",
                "cost_gbp",
            },
            "cost_logs": {
                "chat_session_id",
                "chat_turn_id",
            },
            "research_logs": {
                "chat_session_id",
                "chat_turn_id",
            },
        }

        for table_name, expected_columns in expected_tables.items():
            actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
            assert expected_columns <= actual_columns, (
                f"{table_name} missing {sorted(expected_columns - actual_columns)}"
            )
    finally:
        session.close()
