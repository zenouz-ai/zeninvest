"""Tests for dedicated public dashboard routes and redaction behavior."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase, Run, RunDatasetAudit
from dashboard.backend.app.routers import public as public_router
from src.data.models import (
    Base as AgentBase,
    Instrument,
    MacroState,
    OpportunityQueue,
    OpportunityScoreSnapshot,
    PortfolioSnapshot,
)


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AgentBase.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def _make_client(Session):
    app = FastAPI()
    app.include_router(public_router.router, prefix="/api/public")
    settings_patch = patch("dashboard.backend.app.routers.public.settings")
    session_patch = patch("dashboard.backend.app.routers.public.get_session", side_effect=lambda: Session())
    return app, settings_patch, session_patch


def test_public_universe_caps_rows_and_redacts_private_fields():
    Session, _ = _make_session_factory()
    seed = Session()
    now = datetime.now(timezone.utc)
    for idx in range(12):
        seed.add(
            Instrument(
                ticker=f"TICK{idx}",
                name=f"Ticker {idx}",
                sector="Technology",
                industry="Software",
                market_cap=250_000_000_000 if idx == 0 else 5_000_000_000,
                data_available=True,
                last_screened_at=now - timedelta(minutes=idx),
            )
        )
    seed.commit()
    seed.close()

    app, settings_patch, session_patch = _make_client(Session)
    with settings_patch as mock_settings, session_patch:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        resp = client.get("/api/public/universe")

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 10
    assert payload[0]["ticker"] == "TICK0"
    assert payload[0]["market_cap_bucket"] == "Mega Cap"
    assert "market_cap" not in payload[0]
    assert "data_available" not in payload[0]


def test_public_portfolio_survives_malformed_latest_snapshot_and_hides_private_fields():
    Session, _ = _make_session_factory()
    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add(
        PortfolioSnapshot(
            timestamp=now - timedelta(days=30),
            total_value_gbp=1000.0,
            cash_gbp=200.0,
            invested_gbp=800.0,
            pnl_gbp=50.0,
            pnl_pct=5.0,
            num_positions=1,
            positions_json=json.dumps(
                [
                    {
                        "ticker": "SAFE",
                        "value_gbp": 800.0,
                        "pnl_pct": 8.0,
                        "quantity": 4.0,
                        "profit_lock_status": "protected",
                    }
                ]
            ),
        )
    )
    seed.add(
        PortfolioSnapshot(
            timestamp=now,
            total_value_gbp=1200.0,
            cash_gbp=300.0,
            invested_gbp=900.0,
            pnl_gbp=60.0,
            pnl_pct=5.0,
            num_positions=2,
            positions_json="{bad json",
        )
    )
    seed.commit()
    seed.close()

    app, settings_patch, session_patch = _make_client(Session)
    with settings_patch as mock_settings, session_patch:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        resp = client.get("/api/public/portfolio")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["num_positions"] == 2
    assert payload["positions_visible"] == 0
    assert payload["value_index"] == 120.0
    assert "total_value_gbp" not in payload
    assert "cash_gbp" not in payload
    assert "invested_gbp" not in payload
    assert "actions" not in payload


def test_public_portfolio_history_returns_normalized_index_only():
    Session, _ = _make_session_factory()
    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add_all(
        [
            PortfolioSnapshot(
                timestamp=now - timedelta(days=2),
                total_value_gbp=1000.0,
                cash_gbp=250.0,
                invested_gbp=750.0,
                pnl_gbp=0.0,
                pnl_pct=0.0,
                num_positions=1,
                positions_json="[]",
            ),
            PortfolioSnapshot(
                timestamp=now - timedelta(days=1),
                total_value_gbp=1100.0,
                cash_gbp=200.0,
                invested_gbp=900.0,
                pnl_gbp=100.0,
                pnl_pct=10.0,
                num_positions=1,
                positions_json="[]",
            ),
        ]
    )
    seed.commit()
    seed.close()

    app, settings_patch, session_patch = _make_client(Session)
    with settings_patch as mock_settings, session_patch:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        resp = client.get("/api/public/portfolio/history?limit=10")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload == [
        {"timestamp": payload[0]["timestamp"], "value_index": 100.0},
        {"timestamp": payload[1]["timestamp"], "value_index": 110.0},
    ]
    assert all("total_value_gbp" not in row for row in payload)


def test_public_runs_caps_rows_and_omits_cycle_ids():
    Session, _ = _make_session_factory()
    seed = Session()
    now = datetime.now(timezone.utc)
    run_ids: list[int] = []
    for idx in range(6):
        run = Run(
            cycle_id=f"cycle-{idx}",
            run_type="scheduled",
            started_at=now - timedelta(hours=idx + 1),
            completed_at=now - timedelta(hours=idx),
            status="completed",
            summary_json={
                "duration_seconds": 45 + idx,
                "stocks_screened": 30,
                "decisions_made": 4,
                "orders_placed": 1,
            },
        )
        seed.add(run)
        seed.flush()
        run_ids.append(run.id)
        seed.add(
            RunDatasetAudit(
                run_id=run.id,
                cycle_id=run.cycle_id,
                run_type=run.run_type,
                dataset_key="macro_state",
                status="partial" if idx == 0 else "succeeded",
                started_at=run.started_at,
                completed_at=run.completed_at,
            )
        )
    seed.commit()
    seed.close()

    app, settings_patch, session_patch = _make_client(Session)
    with settings_patch as mock_settings, session_patch:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        resp = client.get("/api/public/runs")

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 5
    assert payload[0]["audit_status"] == "degraded"
    assert "cycle_id" not in payload[0]
    assert "summary_json" not in payload[0]


def test_public_opportunity_caps_rows_and_redacts_exact_scores():
    Session, _ = _make_session_factory()
    seed = Session()
    now = datetime.now(timezone.utc)
    for idx in range(3):
        ticker = f"Q{idx}"
        seed.add(
            Instrument(
                ticker=ticker,
                name=f"Queued {idx}",
                sector="Technology",
                industry="Software",
            )
        )
        seed.add(
            OpportunityQueue(
                ticker=ticker,
                updated_at=now - timedelta(minutes=idx),
                last_uov_ewma=2.4 - idx * 0.4,
                action="BUY",
            )
        )
    for idx in range(4):
        ticker = f"S{idx}"
        seed.add(
            Instrument(
                ticker=ticker,
                name=f"Scored {idx}",
                sector="Industrials",
                industry="Automation",
            )
        )
        seed.add(
            OpportunityScoreSnapshot(
                timestamp=now - timedelta(hours=idx),
                cycle_id=f"score-{idx}",
                ticker=ticker,
                action="WATCH",
                uov_raw=1.0,
                uov_z=1.0,
                uov_final=1.0,
                uov_ewma=1.6 - idx * 0.2,
                is_tradable=True,
            )
        )
    seed.commit()
    seed.close()

    app, settings_patch, session_patch = _make_client(Session)
    with settings_patch as mock_settings, session_patch:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        resp = client.get("/api/public/opportunity")

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 5
    assert payload[0]["stage"] == "Queued"
    assert "uov_ewma" not in payload[0]
    assert "reason" not in payload[0]


def test_public_macro_state_omits_operator_bias_and_private_reasoning():
    Session, _ = _make_session_factory()
    seed = Session()
    seed.add(
        MacroState(
            timestamp=datetime.now(timezone.utc),
            regime="RISK_ON",
            confidence_score=0.71,
            source="scheduled_scan",
            top_signals_json=json.dumps(
                [{"signal_type": "breadth", "signal_text": "Breadth improving", "source": "market_data"}]
            ),
            action_plan_json=json.dumps(
                {
                    "summary": "Broader risk appetite is improving.",
                    "portfolio_bias": "constructive",
                    "sector_implications": ["Technology leadership improving"],
                    "risks": ["Inflation surprise"],
                    "opportunities": ["Cyclicals stabilizing"],
                    "operator_notes": ["do not expose"],
                }
            ),
            sector_summary="Technology leading",
            economic_highlights="Fed remains data dependent",
            raw_payload_json=json.dumps({"sensitive": True}),
        )
    )
    seed.commit()
    seed.close()

    app, settings_patch, session_patch = _make_client(Session)
    with settings_patch as mock_settings, session_patch:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        resp = client.get("/api/public/macro/state")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["action_plan"]["summary"] == "Broader risk appetite is improving."
    assert "portfolio_bias" not in payload["action_plan"]
    assert "operator_notes" not in payload["action_plan"]
    assert "raw_payload_json" not in payload
