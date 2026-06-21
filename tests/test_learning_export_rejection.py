"""Learning export rejection analysis hook (US-6.7)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.data.models import LearningExportRun
from src.learning.export import run_learning_export


@pytest.fixture
def export_env(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(tmp_path / "learning"))
    return tmp_path


def test_run_learning_export_records_rejection_metadata(
    export_env, orchestrator_db_session, patch_orchestrator_get_session
):
    build_result = MagicMock()
    build_result.to_dict.return_value = {
        "decisions_rows": 5,
        "text_corpus_rows": 3,
        "label_distribution": {},
        "paths": {"decisions": "data/learning/parquet/v6/decisions.parquet"},
        "checksum": "abc",
    }
    rejection_result = {
        "rows": 10,
        "resolved": 9,
        "parquet_path": "/tmp/rejected.parquet",
        "analysis_artifact": "/tmp/rejected_analysis.json",
        "funnel_metrics": {"forward_precision_at_veto": 0.4},
    }

    with (
        patch("src.learning.export.run_audit") as mock_audit,
        patch("src.learning.export.DatasetBuilder") as mock_builder_cls,
        patch(
            "src.learning.dataset.rejected_builder.run_rejection_analysis_job",
            return_value=rejection_result,
        ),
    ):
        mock_audit.return_value.to_dict.return_value = {}
        mock_builder = MagicMock()
        mock_builder.__enter__.return_value = mock_builder
        mock_builder.build.return_value = build_result
        mock_builder_cls.return_value = mock_builder

        result = run_learning_export(project_root=export_env, write_audit_json=False)

    assert result["rejection_analysis"] == rejection_result
    row = orchestrator_db_session.query(LearningExportRun).order_by(LearningExportRun.id.desc()).first()
    assert row is not None
    paths = json.loads(row.artifact_paths_json or "{}")
    assert paths.get("rejection_analysis") == rejection_result


def test_run_learning_export_sync_embeddings_when_enabled(
    export_env, orchestrator_db_session, patch_orchestrator_get_session, monkeypatch
):
    build_result = MagicMock()
    build_result.to_dict.return_value = {
        "decisions_rows": 5,
        "text_corpus_rows": 3,
        "label_distribution": {},
        "paths": {"decisions": "data/learning/parquet/v6/decisions.parquet"},
        "checksum": "abc",
    }
    emb_result = {"indexed": 2, "path": "/tmp/index.jsonl"}

    with (
        patch("src.learning.export.run_audit") as mock_audit,
        patch("src.learning.export.DatasetBuilder") as mock_builder_cls,
        patch(
            "src.learning.dataset.rejected_builder.run_rejection_analysis_job",
            return_value={"rows": 0},
        ),
        patch("src.learning.memory.vector_store.build_index_from_jsonl", return_value=emb_result) as mock_emb,
        patch("src.learning.export.get_settings") as mock_settings,
    ):
        settings = mock_settings.return_value
        settings.learning_export_sync_embeddings_enabled = True
        settings.learning_embeddings_enabled = True
        mock_audit.return_value.to_dict.return_value = {}
        mock_builder = MagicMock()
        mock_builder.__enter__.return_value = mock_builder
        mock_builder.build.return_value = build_result
        mock_builder_cls.return_value = mock_builder

        result = run_learning_export(project_root=export_env, write_audit_json=False)

    mock_emb.assert_called_once()
    assert result["embeddings_sync"] == emb_result
