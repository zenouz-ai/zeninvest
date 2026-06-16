"""Tests for the learning router (``/api/learning/*``)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend.app.database import Base as DashboardBase
from dashboard.backend.app.middleware.auth import DashboardSessionMiddleware
from dashboard.backend.app.routers import auth as auth_router
from dashboard.backend.app.routers import learning as learning_router
from dashboard.backend.app.services.auth import hash_password
from src.data.database import engine, get_session
from src.data.models import Base, LearningExportRun, LearningRun, LearningEvaluationRun


# A tiny 1x1 PNG so the insight endpoint has something real to serve.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(DashboardSessionMiddleware)
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(learning_router.router, prefix="/api/learning")
    return app


def _reset_runs() -> None:
    Base.metadata.create_all(bind=engine)
    DashboardBase.metadata.create_all(bind=engine)
    session = get_session()
    try:
        session.query(LearningRun).delete()
        session.commit()
    finally:
        session.close()


def _reset_evaluation_runs() -> None:
    Base.metadata.create_all(bind=engine)
    session = get_session()
    try:
        session.query(LearningEvaluationRun).delete()
        session.commit()
    finally:
        session.close()


def _seed_run(run_id: str = "20260512T100400Z") -> int:
    session = get_session()
    try:
        row = LearningRun(
            run_id=run_id,
            dataset_version="v2",
            model_kind="bundle",
            status="completed",
            rows=1950,
            label_distribution_json=json.dumps(
                {"neutral": 894, "stall": 632, "big_winner": 247, "big_loser": 177}
            ),
            metrics_json=json.dumps({"gbm": {"accuracy": 0.41}}),
            artifact_paths_json=json.dumps({"merged": "data/learning/parquet/v6/merged.parquet"}),
            checksum="abc123",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        session.add(row)
        session.commit()
        return int(row.id)
    finally:
        session.close()


def _seed_report_artifacts(tmp_root: Path, run_id: str) -> Path:
    run_dir = tmp_root / "data" / "learning" / "reports" / run_id
    insights_dir = run_dir / "insights"
    insights_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "index.html").write_text("<html><body>fake</body></html>")
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "rows": 1950,
                "label_distribution": {"big_winner": 247},
                "gbm": {"aggregate_metrics": {"accuracy": 0.41}},
            }
        )
    )
    for name in ("01_label_distribution.png", "06_gbm_feature_importance.png"):
        (insights_dir / name).write_bytes(_TINY_PNG)
    audit_path = tmp_root / "data" / "learning" / "audit_20260512.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps({"eligible_rows": 1950, "closed_trades": 80}))
    return run_dir


@pytest.fixture
def dashboard_env():
    with patch.dict(
        "os.environ",
        {
            "DASHBOARD_OPERATOR_USERNAME": "operator",
            "DASHBOARD_OPERATOR_PASSWORD_HASH": hash_password("super-secret-password"),
            "DASHBOARD_SESSION_SECRET": "session-secret-1234567890",
            "DASHBOARD_INSECURE_DEV_MODE": "true",
        },
        clear=False,
    ):
        yield


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "super-secret-password"},
    )
    assert resp.status_code == 200, resp.text


def test_runs_endpoints_require_auth(dashboard_env) -> None:
    _reset_runs()
    client = TestClient(_make_app(), base_url="http://localhost")
    unauth = client.get("/api/learning/runs")
    assert unauth.status_code == 401


def test_runs_empty_returns_empty_list(dashboard_env) -> None:
    _reset_runs()
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"runs": [], "count": 0}


def test_runs_list_and_detail(monkeypatch, tmp_path, dashboard_env) -> None:
    _reset_runs()
    run_id = "20260512T100400Z"
    _seed_run(run_id)
    run_dir = _seed_report_artifacts(tmp_path, run_id)
    # Re-point the router at the temp filesystem.
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    listing = client.get("/api/learning/runs?limit=10")
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    assert body["runs"][0]["run_id"] == run_id
    assert body["runs"][0]["label_distribution"]["big_winner"] == 247

    detail = client.get(f"/api/learning/runs/{run_id}")
    assert detail.status_code == 200
    detail_json = detail.json()
    assert detail_json["run"]["run_id"] == run_id
    assert detail_json["report_available"] is True
    assert "01_label_distribution.png" in detail_json["insight_files"]
    assert detail_json["metrics"]["gbm"]["aggregate_metrics"]["accuracy"] == 0.41


def test_runs_detail_missing(dashboard_env) -> None:
    _reset_runs()
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/runs/does-not-exist")
    assert resp.status_code == 404


def test_runs_report_and_insight_served(monkeypatch, tmp_path, dashboard_env) -> None:
    _reset_runs()
    run_id = "20260512T100400Z"
    _seed_run(run_id)
    _seed_report_artifacts(tmp_path, run_id)
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    report = client.get(f"/api/learning/runs/{run_id}/report")
    assert report.status_code == 200
    assert "fake" in report.text

    png = client.get(f"/api/learning/runs/{run_id}/insights/01_label_distribution.png")
    assert png.status_code == 200
    assert png.headers["content-type"].startswith("image/")
    assert png.content == _TINY_PNG


def test_insight_traversal_rejected(monkeypatch, tmp_path, dashboard_env) -> None:
    _reset_runs()
    run_id = "20260512T100400Z"
    _seed_run(run_id)
    _seed_report_artifacts(tmp_path, run_id)
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    # ``..%2F`` may be decoded by Starlette as a literal ``..``/ -> the route
    # never matches and 404 is returned. Either 400 or 404 is acceptable as
    # long as we don't serve a file outside the insights dir.
    bad_filename = client.get(f"/api/learning/runs/{run_id}/insights/..%2Fmetrics.json")
    assert bad_filename.status_code in (400, 404)

    non_png = client.get(f"/api/learning/runs/{run_id}/insights/metrics.json")
    assert non_png.status_code == 400

    bad_run = client.get("/api/learning/runs/..%2F%2Fetc/insights/01_label_distribution.png")
    assert bad_run.status_code in (400, 404)

    missing_png = client.get(f"/api/learning/runs/{run_id}/insights/zz_missing.png")
    assert missing_png.status_code == 404


def test_audit_endpoint(monkeypatch, tmp_path, dashboard_env) -> None:
    _reset_runs()
    run_id = "20260512T100400Z"
    _seed_run(run_id)
    _seed_report_artifacts(tmp_path, run_id)
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    audit = client.get(f"/api/learning/runs/{run_id}/audit")
    assert audit.status_code == 200
    assert audit.json()["eligible_rows"] == 1950


def _seed_dataset_artifacts(tmp_root: Path, version: str = "v2") -> None:
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas required for dataset preview tests")

    parquet_dir = tmp_root / "data" / "learning" / "parquet" / version
    exports_dir = tmp_root / "data" / "learning" / "exports" / version
    parquet_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [{"decision_id": 1, "ticker": "AAPL_US_EQ", "action": "BUY", "conviction": 0.72}]
    ).to_parquet(parquet_dir / "decisions.parquet", index=False)
    pd.DataFrame([{"decision_id": 1, "ret_30d": 5.2}]).to_parquet(parquet_dir / "merged.parquet", index=False)
    (parquet_dir / "schema.json").write_text(json.dumps({"version": version, "columns": ["decision_id"]}))
    (parquet_dir / "splits.json").write_text(json.dumps({"train": [1], "test": [2]}))
    (exports_dir / "memory_bundle.jsonl").write_text(
        json.dumps({"doc_id": "d1", "ticker": "AAPL", "body": "sample thesis"}) + "\n"
    )
    (tmp_root / "data" / "learning" / "audit_20260512.json").write_text(
        json.dumps({"eligible_rows": 10})
    )


def test_dataset_versions_and_manifest(monkeypatch, tmp_path, dashboard_env) -> None:
    _seed_dataset_artifacts(tmp_path)
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    versions = client.get("/api/learning/datasets/versions")
    assert versions.status_code == 200
    assert "v2" in versions.json()["versions"]

    manifest = client.get("/api/learning/datasets/v2")
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["artifacts"]["decisions"]["exists"] is True
    assert body["extras"]["memory_bundle"]["exists"] is True


def test_dataset_preview_and_download(monkeypatch, tmp_path, dashboard_env) -> None:
    _seed_dataset_artifacts(tmp_path)
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    preview = client.get("/api/learning/datasets/v2/preview/decisions?limit=10")
    assert preview.status_code == 200
    rows = preview.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL_US_EQ"

    memory = client.get("/api/learning/datasets/v2/preview/memory_bundle")
    assert memory.status_code == 200
    assert memory.json()["rows"][0]["doc_id"] == "d1"

    schema = client.get("/api/learning/datasets/v2/json/schema")
    assert schema.status_code == 200
    assert schema.json()["version"] == "v2"

    download = client.get("/api/learning/datasets/v2/download/decisions.parquet")
    assert download.status_code == 200
    assert len(download.content) > 0


def test_audit_latest(monkeypatch, tmp_path, dashboard_env) -> None:
    _seed_dataset_artifacts(tmp_path)
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/audit/latest")
    assert resp.status_code == 200
    assert resp.json()["eligible_rows"] == 10


def test_exports_list(dashboard_env) -> None:
    _reset_runs()
    session = get_session()
    try:
        session.add(
            LearningExportRun(
                run_id="export-weekly",
                dataset_version="v2",
                status="completed",
                rows=100,
                text_corpus_rows=100,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    finally:
        session.close()
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/exports")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert body["exports"][0]["run_id"] == "export-weekly"


def test_evaluation_latest_from_disk(monkeypatch, tmp_path, dashboard_env) -> None:
    eval_dir = tmp_path / "data" / "learning" / "evaluation" / "eval-disk"
    eval_dir.mkdir(parents=True)
    payload = {
        "run_id": "eval-disk",
        "status": "completed",
        "n_rows": 10,
        "closed_trades": 5,
        "policies": {"champion_as_is": {"realized_n": 5}},
        "gates": {"summary": "test", "tiers": []},
    }
    (eval_dir / "metrics.json").write_text(json.dumps(payload))
    (eval_dir / "index.html").write_text("<html>eval</html>")
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    _reset_evaluation_runs()
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/evaluation/latest")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "eval-disk"


def test_evaluation_committee(monkeypatch, tmp_path, dashboard_env) -> None:
    eval_dir = tmp_path / "data" / "learning" / "evaluation" / "eval-committee"
    eval_dir.mkdir(parents=True)
    payload = {
        "run_id": "eval-committee",
        "status": "completed",
        "committee": {"stage_funnel": {"strategy_buy_queued": 10}},
        "context_influence": {"macro_regime": {"rows": []}},
        "policies": {
            "champion_as_is": {"realized_n": 5},
            "challenger_moderation": {"forward_precision_at_veto": 0.7},
        },
    }
    (eval_dir / "metrics.json").write_text(json.dumps(payload))
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    _reset_evaluation_runs()
    session = get_session()
    try:
        session.add(
            LearningEvaluationRun(
                run_id="eval-committee",
                dataset_version="v6",
                status="completed",
                n_rows=10,
                closed_trades=5,
                metrics_json=json.dumps(payload),
                gates_json="{}",
            )
        )
        session.commit()
    finally:
        session.close()
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/evaluation/committee")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "eval-committee"
    assert "challenger_moderation" in body["policies"]


def test_evaluation_research(monkeypatch, tmp_path, dashboard_env) -> None:
    eval_dir = tmp_path / "data" / "learning" / "evaluation" / "eval-research"
    eval_dir.mkdir(parents=True)
    payload = {
        "run_id": "eval-research",
        "status": "completed",
        "research_influence": {
            "descriptive": {"total_decisions_with_research": 12, "query_overlap_pct": 0.15},
            "stratified": {"by_intensity": [{"bucket": "0", "n": 5, "bad_rate": 0.4}]},
            "citation": {"citation_rate": 0.3, "by_cited": []},
        },
        "policies": {
            "champion_as_is": {"realized_n": 5},
            "challenger_no_research": {"forward_precision_at_veto": 0.6},
        },
    }
    (eval_dir / "metrics.json").write_text(json.dumps(payload))
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    _reset_evaluation_runs()
    session = get_session()
    try:
        session.add(
            LearningEvaluationRun(
                run_id="eval-research",
                dataset_version="v5",
                status="completed",
                n_rows=10,
                closed_trades=5,
                metrics_json=json.dumps(payload),
                gates_json="{}",
            )
        )
        session.commit()
    finally:
        session.close()
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/evaluation/research")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "eval-research"
    assert body["research_influence"]["descriptive"]["total_decisions_with_research"] == 12
    assert "challenger_no_research" in body["policies"]


def _seed_rejection_artifact(tmp_root: Path, stamp: str, *, false_reject_rate: float = 0.3) -> Path:
    reports_dir = tmp_root / "data" / "learning" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": f"2026-06-{stamp[-2:]}T00:00:00+00:00",
        "horizon_days": 30,
        "rejected_total": 120,
        "rejected_resolved": 90,
        "accepted_total": 40,
        "accepted_resolved": 35,
        "coverage_pct": 0.75,
        "good_miss_rate": 0.55,
        "false_reject_rate": false_reject_rate,
        "stall_rate": 0.15,
        "rejected_mean_forward_ret_pct": -2.5,
        "accepted_mean_forward_ret_pct": 4.0,
        "selection_gap_pct": 6.5,
        "rejected_label_counts": {"big_loser": 50, "stall": 14, "big_winner": 26},
        "accepted_label_counts": {"big_winner": 20, "stall": 10, "big_loser": 5},
        "by_stage": [
            {
                "stage": "risk_reject",
                "n": 70,
                "n_resolved": 55,
                "good_miss_rate": 0.6,
                "false_reject_rate": false_reject_rate,
                "stall_rate": 0.1,
                "mean_forward_ret_pct": -3.1,
            }
        ],
    }
    path = reports_dir / f"rejected_analysis_{stamp}.json"
    path.write_text(json.dumps(payload))
    return path


def test_rejection_analysis_serves_latest(monkeypatch, tmp_path, dashboard_env) -> None:
    _seed_rejection_artifact(tmp_path, "20260601")
    latest = _seed_rejection_artifact(tmp_path, "20260615")
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    monkeypatch.delenv("INVESTMENT_AGENT_LEARNING_ROOT", raising=False)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    resp = client.get("/api/learning/rejection-analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["artifact_name"] == latest.name
    assert body["artifact_name"].endswith("20260615.json")
    assert "artifact_mtime" in body
    assert body["rejected_total"] == 120
    assert body["by_stage"][0]["stage"] == "risk_reject"
    assert body.get("available") is not False


def test_rejection_analysis_empty_state(monkeypatch, tmp_path, dashboard_env) -> None:
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    monkeypatch.delenv("INVESTMENT_AGENT_LEARNING_ROOT", raising=False)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    resp = client.get("/api/learning/rejection-analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "analyze_rejected_tickers" in body["hint"]


def test_rejection_analysis_honors_learning_root(monkeypatch, tmp_path, dashboard_env) -> None:
    # When INVESTMENT_AGENT_LEARNING_ROOT is set it wins over _project_root.
    other_root = tmp_path / "sandbox"
    _seed_rejection_artifact(other_root, "20260610")
    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path / "unused")
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(other_root))
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)

    resp = client.get("/api/learning/rejection-analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["artifact_name"] == "rejected_analysis_20260610.json"


def test_rejection_analysis_requires_auth(dashboard_env) -> None:
    client = TestClient(_make_app(), base_url="http://localhost")
    resp = client.get("/api/learning/rejection-analysis")
    assert resp.status_code == 401


def test_shadow_summary_empty(dashboard_env) -> None:
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/shadow/summary?days=30")
    assert resp.status_code == 200
    assert resp.json()["total_scores"] == 0


def test_learning_status_aggregator(dashboard_env, tmp_path, monkeypatch) -> None:
    _reset_runs()
    _seed_run()
    session = get_session()
    try:
        session.add(
            LearningExportRun(
                run_id="export-status",
                dataset_version="v6",
                status="completed",
                rows=2500,
                text_corpus_rows=2500,
                checksum="chk",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(learning_router, "_project_root", lambda: tmp_path)
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "north_star" in body
    assert body["dataset_version"] == "v6"
    assert body["latest_export"]["run_id"] == "export-status"
    assert body["latest_train_run"]["run_id"] == "20260512T100400Z"
    assert "staleness_warnings" in body
    assert body["shadow_summary"]["total_scores"] == 0
