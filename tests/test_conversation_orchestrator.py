"""Regression tests for conversational trading orchestration."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.conversation.orchestrator import ConversationOrchestrator
from src.agents.conversation.planner import ChatPlannerDecision
from src.agents.conversation.session_manager import SessionManager
from src.data.models import Base, Instrument
from src.orchestrator.single_ticker_run import SingleTickerResult
from src.utils.cost_tracker import Provider, log_cost


class FakeDataFetcher:
    """Deterministic research stub for orchestrator tests."""

    def get_stock_analysis_lite(self, yf_ticker: str) -> dict:
        return {
            "current_price": 100.0,
            "relative_strength_6m": 1.1,
            "indicators": {
                "current_price": 100.0,
                "rsi_14": 48.0,
                "volume_sma_ratio_20": 1.2,
            },
            "fundamentals": {
                "trailing_pe": 25.0,
                "debt_equity": 10.0,
            },
        }


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all(
        [
            Instrument(ticker="TSLA_US_EQ", name="Tesla", sector="Consumer Cyclical", business_summary="Tesla summary"),
            Instrument(ticker="GOOGL_US_EQ", name="Alphabet (Class A)", sector="Technology", business_summary="Google summary"),
            Instrument(ticker="AMD_US_EQ", name="Advanced Micro Devices", sector="Technology", business_summary="AMD summary"),
            Instrument(ticker="NVDA_US_EQ", name="NVIDIA", sector="Technology", business_summary="NVDA summary"),
        ]
    )
    session.commit()
    yield session
    session.close()


@pytest.fixture
def patched_db(db_session):
    with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
        with patch("src.agents.conversation.orchestrator.get_session", return_value=db_session):
            with patch("src.utils.ticker_utils.get_session", return_value=db_session):
                with patch("src.utils.cost_tracker.get_session", return_value=db_session):
                    with patch("src.agents.research.executor.get_session", return_value=db_session):
                        with patch("src.agents.conversation.orchestrator.log_event", None):
                            yield


@pytest.fixture
def orchestrator(patched_db):
    return ConversationOrchestrator(
        session_manager=SessionManager(),
        data_fetcher=FakeDataFetcher(),
    )


def test_compare_with_google_alias_returns_both_research_logs(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Compare")

    detail = orchestrator.process_turn(
        session_id=session["id"],
        message_text="compare tesla and google",
        channel_type="dashboard",
    )

    assistant_text = detail["turns"][-1]["message_text"]
    queries = [row["query"] for row in detail["research_logs"]]

    assert "Comparison" in assistant_text
    assert "TSLA_US_EQ" in assistant_text
    assert "GOOGL_US_EQ" in assistant_text
    assert set(queries) == {"TSLA_US_EQ", "GOOGL_US_EQ"}


def test_compare_partial_unresolved_reports_missing_name_instead_of_dropping_it(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Compare")

    detail = orchestrator.process_turn(
        session_id=session["id"],
        message_text="compare tesla and madeupcorp",
        channel_type="dashboard",
    )

    assistant_text = detail["turns"][-1]["message_text"].lower()

    assert "could only resolve" in assistant_text or "couldn't resolve" in assistant_text
    assert "madeupcorp" in assistant_text
    assert detail["research_logs"] == []


def test_what_about_followup_resolves_new_symbol_instead_of_reusing_previous_subjects(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Follow-up")

    first_detail = orchestrator.process_turn(
        session_id=session["id"],
        message_text="compare google and AMD",
        channel_type="dashboard",
    )
    assert {row["query"] for row in first_detail["research_logs"]} == {"GOOGL_US_EQ", "AMD_US_EQ"}

    second_detail = orchestrator.process_turn(
        session_id=session["id"],
        message_text="what about NVDA?",
        channel_type="dashboard",
    )

    assistant_text = second_detail["turns"][-1]["message_text"]
    queries = [row["query"] for row in second_detail["research_logs"]]

    assert "NVDA_US_EQ" in assistant_text
    assert queries[0] == "NVDA_US_EQ"
    assert set(queries) == {"GOOGL_US_EQ", "AMD_US_EQ", "NVDA_US_EQ"}


def test_dashboard_reply_is_mirrored_back_to_slack_thread(orchestrator):
    mock_client = MagicMock()
    orchestrator.settings.notifications.setdefault("slack_trade_commands", {})["channel_id"] = "C123"

    with patch.object(orchestrator, "_get_slack_web_client", return_value=mock_client):
        session = orchestrator.start_session(
            channel_type="slack",
            channel_session_key="thread-123",
            user_id="U1",
            title="Slack thread",
        )
        detail = orchestrator.process_turn(
            session_id=session["id"],
            message_text="help me understand this workflow",
            channel_type="dashboard",
        )

    assistant_text = detail["turns"][-1]["message_text"]

    mock_client.chat_postMessage.assert_called_once()
    assert mock_client.chat_postMessage.call_args.kwargs["channel"] == "C123"
    assert mock_client.chat_postMessage.call_args.kwargs["thread_ts"] == "thread-123"
    assert mock_client.chat_postMessage.call_args.kwargs["text"] == assistant_text


def test_review_turn_accumulates_session_cost_summary(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Costed review")

    def fake_prepare(**kwargs):
        log_cost(
            provider=Provider.OPENAI.value,
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            cycle_id="chat-cost-cycle",
            purpose="moderation_gpt4o",
        )
        from src.agents.research.executor import ResearchExecutor

        executor = ResearchExecutor(cycle_id="chat-cost-cycle")
        executor._log(  # noqa: SLF001 - test validates persisted attribution on the existing log path
            member="strategy",
            ticker="AMD_US_EQ",
            tool="web_search",
            query="amd catalysts",
            results=[{"title": "AMD result", "url": "https://example.com", "snippet": "chip update"}],
            provider="brave",
            cache_hit=False,
            latency_ms=18,
        )
        return SingleTickerResult(
            ticker_t212="AMD_US_EQ",
            ticker_yf="AMD",
            cycle_id="chat-cost-cycle",
            user_action="REVIEW",
            status="review_only",
            command_kind="review",
            execution_mode="strategy",
            strategy_action="BUY",
            moderation_consensus="APPROVED",
            conviction=7,
            price=100.0,
            price_gbp=79.0,
            quantity=0.0,
            value_gbp=0.0,
        )

    with patch("src.agents.conversation.orchestrator.SingleTickerRunner") as mock_runner_cls:
        mock_runner = mock_runner_cls.return_value
        mock_runner.prepare.side_effect = fake_prepare
        with patch("src.agents.conversation.orchestrator.format_trade_command_reply", return_value="Review complete"):
            detail = orchestrator.process_turn(
                session_id=session["id"],
                message_text="review AMD",
                channel_type="dashboard",
            )

    cost_summary = detail["cost_summary"]
    assert cost_summary["llm_calls"] == 1
    assert cost_summary["research_calls"] == 1
    assert cost_summary["by_provider_gbp"]["openai"] > 0
    assert cost_summary["by_model_gbp"]["gpt-4o"] > 0
    assert cost_summary["research_by_provider_gbp"]["brave"] > 0
    assert cost_summary["total_cost_gbp"] == pytest.approx(
        cost_summary["llm_cost_gbp"] + cost_summary["research_cost_gbp"]
    )


def test_agentic_turn_persists_workflow_and_evidence(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Agentic compare")
    planned = ChatPlannerDecision(
        route="committee_review",
        turn_mode="committee",
        use_fast_path=False,
        requires_web_research=True,
        requires_related_scan=True,
        requires_committee=True,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.82,
        next_actions=["preview trade", "show sources"],
        explanation="Committee review requested.",
    )

    with patch.object(orchestrator._planner, "plan_turn", return_value=planned):
        with patch.object(orchestrator, "_extract_agentic_subjects", return_value=["AMD"]):
            with patch.object(
                orchestrator,
                "_run_agentic_research",
                return_value=[
                    {
                        "ticker": "AMD_US_EQ",
                        "title": "AMD AI demand remains strong",
                        "summary": "New AI demand evidence",
                        "url": "https://example.com/amd",
                        "provider": "brave",
                        "tool_name": "news_search",
                    }
                ],
            ):
                with patch.object(
                    orchestrator,
                    "_scan_related_tickers",
                    return_value=[{"ticker": "NVDA_US_EQ", "label": "NVIDIA", "score": 1.2}],
                ):
                    with patch.object(
                        orchestrator._specialists,
                        "build_committee_views",
                        return_value=[
                            {"role": "bull", "summary": "AMD has the cleaner upside path.", "model": "claude"},
                            {"role": "bear", "summary": "Valuation leaves less room for error.", "model": "gpt-5.4"},
                            {"role": "risk", "summary": "Macro risk still matters.", "model": "gemini"},
                        ],
                    ):
                        with patch.object(
                            orchestrator._planner,
                            "compose_response",
                            return_value={
                                "assistant_text": "AMD looks constructive, with NVIDIA as the strongest nearby peer.",
                                "confidence": 0.78,
                                "next_actions": ["preview trade", "show sources"],
                            },
                        ):
                            detail = orchestrator.process_turn(
                                session_id=session["id"],
                                message_text="compare AMD and its best peers",
                                channel_type="dashboard",
                                mode="committee",
                                budget_tier="premium",
                            )

    latest_turn = detail["turns"][-1]
    payload = latest_turn["response_json"]
    step_keys = [step["step_key"] for step in detail["workflow_steps"]]

    assert latest_turn["message_text"] == "AMD looks constructive, with NVIDIA as the strongest nearby peer."
    assert payload["turn_mode"] == "committee"
    assert payload["committee_views"][0]["role"] == "bull"
    assert payload["related_tickers"][0]["ticker"] == "NVDA_US_EQ"
    assert "planning" in step_keys
    assert "running_web_research" in step_keys
    assert "asking_specialist" in step_keys
    assert "building_answer" in step_keys
