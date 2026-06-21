"""Learning model registry helpers (champion resolution and promotion)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.learning.spec import DATASET_VERSION
from src.utils.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.data.models import LearningRun


def active_dataset_version() -> str:
    """Dataset version used for champion inference and shadow scoring."""
    return get_settings().learning_export_dataset_version or DATASET_VERSION


def resolve_champion_run(
    session: Session,
    *,
    dataset_version: str | None = None,
) -> LearningRun | None:
    """Return the champion training run for the active dataset version.

    Prefers an explicit ``is_champion`` row; otherwise falls back to the latest
    completed run for that version.
    """
    from src.data.models import LearningRun

    version = dataset_version or active_dataset_version()
    champion = (
        session.query(LearningRun)
        .filter(
            LearningRun.status == "completed",
            LearningRun.dataset_version == version,
            LearningRun.is_champion.is_(True),
        )
        .order_by(LearningRun.created_at.desc())
        .first()
    )
    if champion is not None:
        return champion
    return (
        session.query(LearningRun)
        .filter(
            LearningRun.status == "completed",
            LearningRun.dataset_version == version,
        )
        .order_by(LearningRun.created_at.desc())
        .first()
    )


def promote_champion_run(session: Session, run_id: str) -> LearningRun:
    """Mark one completed run as champion for its dataset version."""
    from src.data.models import LearningRun

    row = session.query(LearningRun).filter(LearningRun.run_id == run_id).first()
    if row is None:
        raise ValueError(f"learning run not found: {run_id}")
    if row.status != "completed":
        raise ValueError(f"run {run_id} is not completed (status={row.status})")

    session.query(LearningRun).filter(
        LearningRun.dataset_version == row.dataset_version,
        LearningRun.is_champion.is_(True),
        LearningRun.run_id != run_id,
    ).update({LearningRun.is_champion: False}, synchronize_session=False)
    row.is_champion = True
    session.commit()
    session.refresh(row)
    return row
