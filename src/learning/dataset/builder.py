"""End-to-end dataset builder for the trade-outcome learning pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import StrategyDecision
from src.learning.dataset.features import FeatureEngineer
from src.learning.dataset.labels import LabelComputer
from src.learning.dataset.splits import WalkForwardSplitter
from src.learning.dataset.text_corpus import TextCorpusBuilder
from src.learning.spec import DatasetSpec, get_default_spec, get_text_corpus_spec, label_columns
from src.utils.logger import get_logger

logger = get_logger("learning.builder")


@dataclass
class BuildResult:
    """Artifacts written to disk plus diagnostic information."""

    spec: DatasetSpec
    output_root: str
    decisions_rows: int
    features_rows: int
    labels_rows: int
    text_corpus_rows: int = 0
    label_distribution: dict[str, int] = field(default_factory=dict)
    folds: int = 0
    paths: dict[str, str] = field(default_factory=dict)
    checksum: str = ""

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.as_dict(),
            "output_root": self.output_root,
            "decisions_rows": self.decisions_rows,
            "features_rows": self.features_rows,
            "labels_rows": self.labels_rows,
            "text_corpus_rows": self.text_corpus_rows,
            "label_distribution": self.label_distribution,
            "folds": self.folds,
            "paths": self.paths,
            "checksum": self.checksum,
        }


class DatasetBuilder:
    """Build the v2 learning dataset (tabular + text sidecar).

    The builder reads from the production SQLite database (or any session you
    pass in) and writes parquet artifacts to ``data/learning/parquet/<v>/``.
    The dashboard's Learning page reads training artifacts via ``learning_runs``;
    weekly exports persist metadata in ``learning_export_runs``.
    """

    def __init__(
        self,
        session: Session | None = None,
        spec: DatasetSpec | None = None,
        *,
        project_root: str | None = None,
        price_fetcher=None,
    ) -> None:
        self._owned_session = session is None
        self.session = session or get_session()
        self.spec = spec or get_default_spec()
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
        self.feature_engineer = FeatureEngineer(self.session)
        self.label_computer = LabelComputer(self.session, self.spec, price_fetcher=price_fetcher)
        self.text_builder = TextCorpusBuilder(
            self.session,
            get_text_corpus_spec(),
            project_root=self.project_root,
        )

    def __enter__(self) -> "DatasetBuilder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._owned_session:
            self.session.close()

    def build(self, *, write: bool = True) -> BuildResult:
        decisions_df = self._load_decision_rows()
        if decisions_df.empty:
            logger.warning("No BUY-eligible decision rows; dataset build will be empty.")
            return BuildResult(
                spec=self.spec,
                output_root=str(self._output_root()),
                decisions_rows=0,
                features_rows=0,
                labels_rows=0,
                text_corpus_rows=0,
            )

        features_df = self.feature_engineer.build(decisions_df.to_dict(orient="records"))
        labels_df = self.label_computer.compute(decisions_df.to_dict(orient="records"))

        merged = features_df.merge(labels_df, on=["cycle_id", "ticker", "decision_ts"], how="inner")
        merged = merged.sort_values("decision_ts").reset_index(drop=True)

        splitter = WalkForwardSplitter(embargo_days=self.spec.labels.embargo_days)
        splits = splitter.split(merged["decision_ts"].tolist())

        label_set = set(label_columns(self.spec))
        feature_set = set(features_df.columns) - {"cycle_id", "ticker", "decision_ts"}
        overlap = feature_set & label_set
        if overlap:
            raise RuntimeError(f"Feature/label leakage detected for columns: {sorted(overlap)}")

        label_distribution = (
            merged["label_3class"].value_counts().to_dict() if "label_3class" in merged.columns else {}
        )

        text_corpus_df, text_paths = self.text_builder.build(
            decisions_df.to_dict(orient="records"),
            labels_df=labels_df,
            write=write,
        )

        paths: dict[str, str] = {}
        checksum = ""
        if write:
            paths = self._write_artifacts(decisions_df, features_df, labels_df, merged, splits)
            paths.update(text_paths)
            checksum = self._checksum(paths)

        return BuildResult(
            spec=self.spec,
            output_root=str(self._output_root()),
            decisions_rows=int(len(decisions_df)),
            features_rows=int(len(features_df)),
            labels_rows=int(len(labels_df)),
            text_corpus_rows=int(len(text_corpus_df)),
            label_distribution={str(k): int(v) for k, v in label_distribution.items()},
            folds=splits.n_folds,
            paths=paths,
            checksum=checksum,
        )

    def _load_decision_rows(self) -> pd.DataFrame:
        rows = (
            self.session.query(StrategyDecision)
            .filter(StrategyDecision.action.in_(self.spec.row_actions))
            .order_by(StrategyDecision.timestamp.asc())
            .all()
        )
        records: list[dict] = []
        for row in rows:
            records.append(
                {
                    "cycle_id": row.cycle_id,
                    "ticker": row.ticker,
                    "timestamp": row.timestamp,
                    "action": row.action,
                    "conviction": row.conviction,
                    "target_allocation_pct": row.target_allocation_pct,
                    "risk_parity_target_allocation_pct": row.risk_parity_target_allocation_pct,
                    "risk_parity_trailing_vol_pct": row.risk_parity_trailing_vol_pct,
                    "growth_potential": row.growth_potential,
                    "risk_level": row.risk_level,
                    "primary_strategy": row.primary_strategy,
                    "upside_target_pct": row.upside_target_pct,
                    "stop_loss_pct": row.stop_loss_pct,
                    "expected_holding_period": row.expected_holding_period,
                    "catalysts_json": row.catalysts_json,
                    "risks_json": row.risks_json,
                    "reasoning": row.reasoning,
                }
            )
        return pd.DataFrame.from_records(records)

    def _output_root(self) -> Path:
        return self.project_root / self.spec.output_dir / "parquet" / self.spec.version

    def _write_artifacts(
        self,
        decisions_df: pd.DataFrame,
        features_df: pd.DataFrame,
        labels_df: pd.DataFrame,
        merged_df: pd.DataFrame,
        splits,
    ) -> dict[str, str]:
        root = self._output_root()
        root.mkdir(parents=True, exist_ok=True)

        decisions_path = root / "decisions.parquet"
        features_path = root / "features.parquet"
        labels_path = root / "outcomes.parquet"
        merged_path = root / "merged.parquet"
        splits_path = root / "splits.json"
        schema_path = root / "schema.json"

        decisions_df.to_parquet(decisions_path, index=False)
        features_df.to_parquet(features_path, index=False)
        labels_df.to_parquet(labels_path, index=False)
        merged_df.to_parquet(merged_path, index=False)
        splits.dump(str(splits_path))

        schema_payload = {
            "spec": self.spec.as_dict(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "decisions_columns": list(decisions_df.columns),
            "features_columns": list(features_df.columns),
            "labels_columns": list(labels_df.columns),
            "merged_columns": list(merged_df.columns),
            "label_distribution": (
                merged_df["label_3class"].value_counts().to_dict()
                if "label_3class" in merged_df.columns
                else {}
            ),
            "folds": splits.n_folds,
        }
        with open(schema_path, "w") as fh:
            json.dump(schema_payload, fh, indent=2, default=str)

        return {
            "decisions": str(decisions_path),
            "features": str(features_path),
            "outcomes": str(labels_path),
            "merged": str(merged_path),
            "splits": str(splits_path),
            "schema": str(schema_path),
        }

    @staticmethod
    def _checksum(paths: dict[str, str]) -> str:
        hasher = hashlib.sha256()
        for name in sorted(paths):
            path = paths[name]
            try:
                with open(path, "rb") as fh:
                    while True:
                        chunk = fh.read(1 << 16)
                        if not chunk:
                            break
                        hasher.update(chunk)
            except OSError:
                continue
        return hasher.hexdigest()
