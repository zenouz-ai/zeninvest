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
from src.data.models import Base, LearningExportRun, LearningRun


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
            artifact_paths_json=json.dumps({"merged": "data/learning/parquet/v2/merged.parquet"}),
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
    session = get_session()
    try:
        from src.data.models import LearningEvaluationRun

        session.query(LearningEvaluationRun).delete()
        session.commit()
    finally:
        session.close()
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/evaluation/latest")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "eval-disk"


def test_shadow_summary_empty(dashboard_env) -> None:
    client = TestClient(_make_app(), base_url="http://localhost")
    _login(client)
    resp = client.get("/api/learning/shadow/summary?days=30")
    assert resp.status_code == 200
    assert resp.json()["total_scores"] == 0
