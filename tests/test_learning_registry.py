"""Tests for learning registry champion resolution and promotion."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, LearningRun
from src.learning.registry import active_dataset_version, promote_champion_run, resolve_champion_run


@pytest.fixture
def registry_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _add_run(
    session,
    *,
    run_id: str,
    dataset_version: str = "v6",
    is_champion: bool = False,
    created_at: datetime | None = None,
) -> LearningRun:
    row = LearningRun(
        run_id=run_id,
        dataset_version=dataset_version,
        model_kind="bundle",
        status="completed",
        rows=100,
        label_distribution_json=json.dumps({"big_winner": 10}),
        metrics_json="{}",
        artifact_paths_json="{}",
        checksum="abc",
        is_champion=is_champion,
        created_at=created_at or datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return row


def test_resolve_champion_prefers_explicit_flag(registry_session, monkeypatch):
    monkeypatch.setattr("src.learning.registry.active_dataset_version", lambda: "v6")
    _add_run(
        registry_session,
        run_id="older",
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    _add_run(
        registry_session,
        run_id="champion",
        is_champion=True,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    row = resolve_champion_run(registry_session)
    assert row is not None
    assert row.run_id == "champion"


def test_resolve_champion_filters_dataset_version(registry_session, monkeypatch):
    monkeypatch.setattr("src.learning.registry.active_dataset_version", lambda: "v6")
    _add_run(registry_session, run_id="v5-run", dataset_version="v5", is_champion=True)
    _add_run(registry_session, run_id="v6-run", dataset_version="v6")

    row = resolve_champion_run(registry_session)
    assert row is not None
    assert row.run_id == "v6-run"


def test_promote_clears_other_champions_for_version(registry_session):
    _add_run(registry_session, run_id="old-champ", is_champion=True)
    _add_run(registry_session, run_id="new-champ")

    promoted = promote_champion_run(registry_session, "new-champ")
    assert promoted.is_champion is True

    old = (
        registry_session.query(LearningRun)
        .filter(LearningRun.run_id == "old-champ")
        .one()
    )
    assert old.is_champion is False


def test_promote_rejects_missing_run(registry_session):
    with pytest.raises(ValueError, match="not found"):
        promote_champion_run(registry_session, "missing")


def test_active_dataset_version_uses_settings(monkeypatch):
    class FakeSettings:
        learning_export_dataset_version = "v6"

    monkeypatch.setattr("src.learning.registry.get_settings", lambda: FakeSettings())
    assert active_dataset_version() == "v6"
