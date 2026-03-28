"""Regression tests for conversational trading orchestration."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.conversation.orchestrator import ConversationOrchestrator
from src.agents.conversation.compare_parser import parse_compare_request
from src.agents.conversation.specialists import ChatSpecialistEngine
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
            Instrument(
                ticker="AAPL_US_EQ",
                name="Apple",
                sector="Technology",
                industry="Consumer Electronics",
                market_cap=3_000_000_000_000,
                business_summary="Apple summary",
            ),
            Instrument(
                ticker="TSLA_US_EQ",
                name="Tesla",
                sector="Consumer Cyclical",
                industry="Auto Manufacturers",
                market_cap=800_000_000_000,
                business_summary="Tesla summary",
            ),
            Instrument(
                ticker="GOOGL_US_EQ",
                name="Alphabet (Class A)",
                sector="Technology",
                industry="Internet Content & Information",
                market_cap=2_000_000_000_000,
                business_summary="Google summary",
            ),
            Instrument(
                ticker="MSFT_US_EQ",
                name="Microsoft",
                sector="Technology",
                industry="Software - Infrastructure",
                market_cap=3_100_000_000_000,
                business_summary="Microsoft summary",
            ),
            Instrument(
                ticker="AMD_US_EQ",
                name="Advanced Micro Devices",
                sector="Technology",
                industry="Semiconductors",
                market_cap=300_000_000_000,
                business_summary="AMD summary",
            ),
            Instrument(
                ticker="AMZN_US_EQ",
                name="Amazon",
                sector="Consumer Cyclical",
                industry="Internet Retail",
                market_cap=2_100_000_000_000,
                business_summary="Amazon summary",
            ),
            Instrument(
                ticker="NVDA_US_EQ",
                name="NVIDIA",
                sector="Technology",
                industry="Semiconductors",
                market_cap=2_500_000_000_000,
                business_summary="NVDA summary",
            ),
            Instrument(
                ticker="TSM_US_EQ",
                name="Taiwan Semiconductor",
                sector="Technology",
                industry="Semiconductors",
                market_cap=850_000_000_000,
                business_summary="TSM summary",
            ),
            Instrument(
                ticker="TCEHY_OTC",
                name="Tencent",
                sector="Technology",
                industry="Internet Content & Information",
                market_cap=450_000_000_000,
                business_summary="Tencent summary",
            ),
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


def test_extract_agentic_subjects_handles_compare_phrase(orchestrator):
    plan = ChatPlannerDecision(
        route="compare",
        turn_mode="research",
        use_fast_path=False,
        requires_web_research=True,
        requires_related_scan=False,
        requires_committee=False,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.8,
        next_actions=[],
        explanation="Compare route.",
    )

    subjects = orchestrator._extract_agentic_subjects("compare tesla and google", plan, {})

    assert subjects == ["tesla", "google"]


def test_parse_compare_request_handles_three_tickers_and_time_horizon():
    parsed = parse_compare_request(
        "compare AAPL, MSFT, and NVDA, then tell me which looks strongest over the next 3-6 months"
    )

    assert parsed is not None
    assert parsed.subjects == ["AAPL", "MSFT", "NVDA"]
    assert parsed.comparison_goal == "pick_strongest"
    assert parsed.time_horizon == "3-6 months"
    assert parsed.post_compare_trade_intent is None


def test_parse_compare_request_handles_compare_then_buy_stronger_one():
    parsed = parse_compare_request("compare Amazon and Alphabet, then buy £20 of the stronger one")

    assert parsed is not None
    assert parsed.subjects == ["Amazon", "Alphabet"]
    assert parsed.comparison_goal == "pick_strongest"
    assert parsed.post_compare_trade_intent is not None
    assert parsed.post_compare_trade_intent.action == "BUY"
    assert parsed.post_compare_trade_intent.amount_gbp == 20.0
    assert parsed.post_compare_trade_intent.subject_phrases == ["the stronger one"]


def test_extract_agentic_subjects_handles_committee_phrase(orchestrator):
    plan = ChatPlannerDecision(
        route="committee_review",
        turn_mode="committee",
        use_fast_path=False,
        requires_web_research=True,
        requires_related_scan=False,
        requires_committee=True,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.8,
        next_actions=[],
        explanation="Committee route.",
    )

    subjects = orchestrator._extract_agentic_subjects("give me bull and bear views on AMD", plan, {})

    assert subjects == ["AMD"]


def test_extract_agentic_subjects_skips_help_prompt(orchestrator):
    plan = ChatPlannerDecision(
        route="help_or_explain",
        turn_mode="quick",
        use_fast_path=True,
        requires_web_research=False,
        requires_related_scan=False,
        requires_committee=False,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.9,
        next_actions=[],
        explanation="Help route.",
    )

    subjects = orchestrator._extract_agentic_subjects("help me understand this workflow", plan, {})

    assert subjects == []


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


def test_quick_mode_help_prompt_uses_explainer_not_placeholder(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Help")

    detail = orchestrator.process_turn(
        session_id=session["id"],
        message_text="help me understand this workflow",
        channel_type="dashboard",
        mode="quick",
    )

    assistant_text = detail["turns"][-1]["message_text"]

    assert "Nothing executes directly from chat" in assistant_text
    assert "Research summary" not in assistant_text
    assert detail["research_logs"] == []


def test_agentic_compare_partial_resolution_returns_warning_without_peer_scan(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Agentic compare")
    planned = ChatPlannerDecision(
        route="compare",
        turn_mode="research",
        use_fast_path=False,
        requires_web_research=True,
        requires_related_scan=True,
        requires_committee=False,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.8,
        next_actions=["show sources"],
        explanation="Compare route requested.",
    )

    with patch.object(orchestrator._planner, "plan_turn", return_value=planned):
        with patch.object(orchestrator, "_scan_related_tickers") as related_scan:
            detail = orchestrator.process_turn(
                session_id=session["id"],
                message_text="compare tesla and madeupcorp",
                channel_type="dashboard",
            )

    assistant_text = detail["turns"][-1]["message_text"]
    payload = detail["turns"][-1]["response_json"]

    related_scan.assert_not_called()
    assert "could only resolve" in assistant_text.lower() or "need two ticker" in assistant_text.lower()
    assert payload["related_tickers"] == []
    assert payload["warnings"][0]["code"] == "compare_resolution_incomplete"
    assert detail["research_logs"] == []


def test_agentic_committee_prompt_returns_views_for_resolved_ticker(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="Committee")
    planned = ChatPlannerDecision(
        route="committee_review",
        turn_mode="committee",
        use_fast_path=False,
        requires_web_research=True,
        requires_related_scan=False,
        requires_committee=True,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.8,
        next_actions=["preview trade"],
        explanation="Committee route requested.",
    )

    with patch.object(orchestrator._planner, "plan_turn", return_value=planned):
        with patch.object(orchestrator, "_run_agentic_research", return_value=[]):
            detail = orchestrator.process_turn(
                session_id=session["id"],
                message_text="give me bull and bear views on AMD",
                channel_type="dashboard",
            )

    assistant_text = detail["turns"][-1]["message_text"]
    payload = detail["turns"][-1]["response_json"]

    assert "Committee view" in assistant_text
    assert len(payload["committee_views"]) == 3
    assert payload["committee_views"][0]["role"] == "bull"
    assert payload["warnings"] == []


def test_plain_compare_does_not_auto_show_related_tickers(orchestrator):
    session = orchestrator.start_session(channel_type="dashboard", title="No peer scan")
    planned = ChatPlannerDecision(
        route="compare",
        turn_mode="research",
        use_fast_path=False,
        requires_web_research=True,
        requires_related_scan=False,
        requires_committee=False,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.8,
        next_actions=["show sources"],
        explanation="Compare route requested.",
    )

    with patch.object(orchestrator._planner, "plan_turn", return_value=planned):
        with patch.object(orchestrator, "_run_agentic_research", return_value=[]):
            detail = orchestrator.process_turn(
                session_id=session["id"],
                message_text="compare tesla and google",
                channel_type="dashboard",
            )

    payload = detail["turns"][-1]["response_json"]

    assert payload["related_tickers"] == []
    assert "TSLA_US_EQ" in detail["turns"][-1]["message_text"]
    assert "GOOGL_US_EQ" in detail["turns"][-1]["message_text"]


def test_related_ticker_scan_prefers_same_suffix_and_semiconductor_peers(orchestrator):
    related = orchestrator._scan_related_tickers(["AMD_US_EQ"])
    tickers = [row["ticker"] for row in related]

    assert "NVDA_US_EQ" in tickers
    assert "TCEHY_OTC" not in tickers
    assert all(ticker.endswith("_US_EQ") for ticker in tickers)


def test_committee_fallback_fills_missing_roles(orchestrator):
    with patch.object(orchestrator._specialists, "_bull_view", return_value=None):
        with patch.object(
            orchestrator._specialists,
            "_bear_view",
            return_value={"role": "bear", "summary": "Expensive setup.", "model": "gpt-4o"},
        ):
            with patch.object(orchestrator._specialists, "_risk_view", return_value=None):
                views = orchestrator._specialists.build_committee_views(
                    tickers=["AMD_US_EQ"],
                    evidence_bundle={
                        "market_snapshot": [{"ticker": "AMD_US_EQ", "relative_strength_6m": 1.29, "rsi_14": 49.2}],
                        "related_tickers": [{"ticker": "NVDA_US_EQ"}],
                    },
                    turn_mode="committee",
                )

    roles = [view["role"] for view in views]
    assert roles.count("bear") == 1
    assert "bull" in roles
    assert "risk" in roles


def test_specialist_payload_parser_salvages_plain_text():
    engine = ChatSpecialistEngine()

    payload = engine._parse_specialist_payload(  # noqa: SLF001
        "Bull case: AMD still has constructive AI demand momentum and improving relative strength.",
        role="bull",
        summary_keys=("summary", "thesis"),
    )

    assert "constructive AI demand momentum" in payload["summary"]
    assert payload["thesis"] == payload["summary"]


def test_specialist_payload_parser_extracts_fenced_json():
    engine = ChatSpecialistEngine()

    payload = engine._parse_specialist_payload(  # noqa: SLF001
        "```json\n{\"summary\":\"Macro risk remains elevated.\",\"confidence\":0.52}\n```",
        role="risk",
        summary_keys=("summary", "assessment"),
    )

    assert payload["summary"] == "Macro risk remains elevated."
    assert payload["confidence"] == 0.52


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
                            {"role": "bear", "summary": "Valuation leaves less room for error.", "model": "gpt-4o"},
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

    assert "AMD looks constructive, with NVIDIA as the strongest nearby peer." in latest_turn["message_text"]
    assert payload["turn_mode"] == "committee"
    assert payload["committee_views"][0]["role"] == "bull"
    assert payload["related_tickers"][0]["ticker"] == "NVDA_US_EQ"
    assert "planning" in step_keys
    assert "running_web_research" in step_keys
    assert "asking_specialist" in step_keys
    assert "building_answer" in step_keys


def test_threaded_explicit_trade_command_uses_deterministic_preview_even_with_prior_context(orchestrator):
    session = orchestrator.start_session(channel_type="slack", title="Slack thread", channel_session_key="thread-22")
    orchestrator.session_manager.update_session_context(
        session["id"],
        context_json={"last_subject_tickers": ["NVDA_US_EQ"]},
        last_channel_type="slack",
    )

    prepared = SingleTickerResult(
        ticker_t212="AAPL_US_EQ",
        ticker_yf="AAPL",
        cycle_id="slack-20260328T140936",
        user_action="BUY",
        status="ready",
        command_kind="trade",
        execution_mode="direct",
        price=248.8,
        price_gbp=187.4,
        quantity=2.93,
        value_gbp=550.0,
    )

    with patch("src.agents.conversation.orchestrator.DirectTradeRunner") as mock_runner_cls:
        mock_runner = mock_runner_cls.return_value
        mock_runner.prepare.return_value = prepared
        detail = orchestrator.process_turn(
            session_id=session["id"],
            message_text="BUY £550 AAPL",
            channel_type="slack",
        )

    assistant_text = detail["turns"][-1]["message_text"]
    action = detail["actions"][0]

    assert "Proposed BUY AAPL" in assistant_text
    assert action["ticker"] == "AAPL_US_EQ"
    assert action["status"] == "awaiting_confirmation"


def test_threaded_portfolio_rule_ignores_prior_research_context(orchestrator):
    session = orchestrator.start_session(channel_type="slack", title="Slack thread", channel_session_key="thread-portfolio")
    orchestrator.session_manager.update_session_context(
        session["id"],
        context_json={"last_subject_tickers": ["NVDA_US_EQ"]},
        last_channel_type="slack",
    )

    with patch.object(
        orchestrator,
        "_get_portfolio_positions",
        return_value=[
            {"ticker": "SUZ_US_EQ", "value_gbp": 90.0, "pnl_pct": -2.0, "quantity": 3.0, "current_price": 30.0},
            {"ticker": "JNJ_US_EQ", "value_gbp": 240.0, "pnl_pct": 1.0, "quantity": 1.0, "current_price": 240.0},
        ],
    ):
        detail = orchestrator.process_turn(
            session_id=session["id"],
            message_text="liquidate holdings below £100",
            channel_type="slack",
        )

    assistant_text = detail["turns"][-1]["message_text"]
    action = detail["actions"][0]

    assert assistant_text.startswith("Liquidate holdings below £100.00")
    assert "SUZ_US_EQ" in assistant_text
    assert "NVDA_US_EQ" not in assistant_text
    assert action["action_type"] == "portfolio_batch_sell"
    assert action["ticker"] == "SUZ_US_EQ"


def test_compare_then_buy_stronger_one_stages_preview_for_selected_winner(orchestrator):
    session = orchestrator.start_session(channel_type="slack", title="Slack compare", channel_session_key="thread-compare-buy")
    compare_request = parse_compare_request("compare Amazon and Alphabet, then buy £20 of the stronger one")
    planned = ChatPlannerDecision(
        route="compare",
        turn_mode="research",
        use_fast_path=False,
        requires_web_research=True,
        requires_related_scan=False,
        requires_committee=False,
        requires_trade_preview=False,
        should_suggest_opportunity=False,
        confidence=0.82,
        next_actions=["show sources", "preview trade"],
        explanation="Operator asked for a side-by-side comparison.",
        comparison_goal="pick_strongest",
        comparison_subjects=compare_request.subjects if compare_request else ["Amazon", "Alphabet"],
        time_horizon=compare_request.time_horizon if compare_request else None,
        post_compare_trade_intent=(
            compare_request.as_dict().get("post_compare_trade_intent") if compare_request else None
        ),
    )

    prepared = SingleTickerResult(
        ticker_t212="AMZN_US_EQ",
        ticker_yf="AMZN",
        cycle_id="chat-compare-buy",
        user_action="BUY",
        status="ready",
        command_kind="trade",
        execution_mode="direct",
        price=180.0,
        price_gbp=142.0,
        quantity=0.14,
        value_gbp=20.0,
    )

    snapshots = {
        "AMZN_US_EQ": {
            "ticker": "AMZN_US_EQ",
            "company_name": "Amazon",
            "current_price": 180.0,
            "relative_strength_6m": 1.34,
            "rsi_14": 56.0,
            "debt_equity": 1.2,
            "trailing_pe": 32.0,
        },
        "GOOGL_US_EQ": {
            "ticker": "GOOGL_US_EQ",
            "company_name": "Alphabet (Class A)",
            "current_price": 280.0,
            "relative_strength_6m": 1.08,
            "rsi_14": 44.0,
            "debt_equity": 0.3,
            "trailing_pe": 24.0,
        },
    }

    with patch.object(orchestrator._planner, "plan_turn", return_value=planned):
        with patch.object(orchestrator, "_run_agentic_research", return_value=[]):
            with patch.object(orchestrator, "_build_market_snapshot_payload", side_effect=lambda ticker: snapshots[ticker]):
                with patch("src.agents.conversation.orchestrator.DirectTradeRunner") as mock_runner_cls:
                    mock_runner = mock_runner_cls.return_value
                    mock_runner.prepare.return_value = prepared
                    detail = orchestrator.process_turn(
                        session_id=session["id"],
                        message_text="compare Amazon and Alphabet, then buy £20 of the stronger one",
                        channel_type="slack",
                    )

    latest_turn = detail["turns"][-1]
    payload = latest_turn["response_json"]

    assert "Strongest setup: AMZN_US_EQ" in latest_turn["message_text"]
    assert "Proposed BUY AMZN" in latest_turn["message_text"]
    assert payload["selection_summary"]["winner_ticker"] == "AMZN_US_EQ"
    assert payload["proposed_action"]["ticker"] == "AMZN_US_EQ"
    assert payload["proposed_action"]["status"] == "awaiting_confirmation"
