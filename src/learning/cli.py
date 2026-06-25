"""Command-line entrypoint for the learning pipeline.

Usage::

    poetry run python -m src.learning.cli audit
    poetry run python -m src.learning.cli build
    poetry run python -m src.learning.cli train --run-id 2026-05-11-baseline
    poetry run python -m src.learning.cli report --run-id 2026-05-11-baseline

``train`` builds the dataset (if missing) and trains the calibrator, GBM
scorer, and stall model. ``report`` regenerates the HTML/JSON report from
already-persisted artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.database import get_session
from src.data.models import LearningRun
from src.learning.audit import run_audit
from src.learning.dataset.builder import DatasetBuilder
from src.learning.export import run_learning_export
from src.learning.spec import DatasetSpec, get_default_spec, get_text_corpus_spec
from src.utils.logger import get_logger

logger = get_logger("learning.cli")


def _resolve_project_root() -> Path:
    """Project root for artifact writes.

    ``INVESTMENT_AGENT_LEARNING_ROOT`` lets tests redirect every artifact to
    a sandbox directory without monkeypatching `Path`.
    """
    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2]


def _git_commit_short() -> str | None:
    """Best-effort git SHA for model governance metadata."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_resolve_project_root(),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()[:12] or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ZenInvest learning pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("audit", help="Run schema audit and print JSON report")

    p_build = sub.add_parser("build", help="Build the dataset (parquet + splits)")
    p_build.add_argument("--no-write", action="store_true", help="Build in memory only")

    p_train = sub.add_parser("train", help="Train calibrator + GBM + stall model")
    p_train.add_argument("--run-id", required=False, default=None, help="Override the auto-generated run id")
    p_train.add_argument("--skip-gbm", action="store_true", help="Skip GBM training (calibrator only)")
    p_train.add_argument("--skip-stall", action="store_true", help="Skip stall training")
    p_train.add_argument("--seed", type=int, default=42)
    p_train.add_argument(
        "--promote",
        action="store_true",
        help="Mark this run as champion for its dataset version after training",
    )

    p_promote = sub.add_parser("promote", help="Mark a completed training run as champion")
    p_promote.add_argument("--run-id", required=True)

    p_report = sub.add_parser("report", help="Re-render the HTML report from saved metrics.json")
    p_report.add_argument("--run-id", required=True)

    p_viz = sub.add_parser(
        "visualize", help="Render insights PNGs (calibration, label dist, importance, decile lift)"
    )
    p_viz.add_argument("--run-id", required=True)

    sub.add_parser("export", help="Print parquet paths for current dataset version")

    sub.add_parser("export-memory", help="Write memory_bundle.jsonl from latest text_corpus build")
    sub.add_parser("run-export", help="Audit + build + export (weekly scheduler job)")
    sub.add_parser("sync-embeddings", help="Build vector index from memory_bundle.jsonl (on-demand)")
    sub.add_parser("sync-neo4j", help="Ingest memory_bundle.jsonl into Neo4j")
    sub.add_parser("sync-graphiti", help="Write Graphiti temporal episodes JSON")

    p_list = sub.add_parser("list-runs", help="List persisted learning_runs rows")
    p_list.add_argument("--limit", type=int, default=20)

    p_eval = sub.add_parser("evaluate", help="Champion vs challenger counterfactual evaluation")
    p_eval.add_argument("--run-id", default=None)
    p_eval.add_argument(
        "--policies",
        default=None,
        help="Comma-separated policy ids (default: champion,gbm,memory,combined)",
    )

    p_gates = sub.add_parser("gates", help="Check promotion gates")
    p_gates_sub = p_gates.add_subparsers(dest="gates_command", required=True)
    p_gates_check = p_gates_sub.add_parser("check", help="Run gate check on latest evaluation")
    p_gates_check.add_argument("--run-id", default=None)

    sub.add_parser("shadow-outcome-join", help="Mature shadow scores with trade outcomes")

    return parser.parse_args()


def _output_paths(spec: DatasetSpec) -> dict[str, str]:
    paths = spec.parquet_paths()
    project_root = _resolve_project_root()
    return {k: str(project_root / v) for k, v in paths.items()}


def _run_audit() -> int:
    report = run_audit()
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0


def _run_build(no_write: bool) -> int:
    with DatasetBuilder() as builder:
        result = builder.build(write=not no_write)
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0


def _run_export() -> int:
    paths = _output_paths(get_default_spec())
    print(json.dumps(paths, indent=2))
    return 0


def _run_export_memory() -> int:
    from src.learning.dataset.text_corpus import TextCorpusBuilder

    project_root = _resolve_project_root()
    spec = get_text_corpus_spec()
    corpus_path = project_root / spec.text_corpus_path()
    if not corpus_path.exists():
        logger.error("text_corpus missing at %s; run `build` first", corpus_path)
        return 2
    df = pd.read_parquet(corpus_path)
    session = get_session()
    try:
        builder = TextCorpusBuilder(session, project_root=project_root)
        path = builder.export_memory_jsonl(df)
    finally:
        session.close()
    print(json.dumps({"rows": len(df), "memory_bundle": path}, indent=2))
    return 0


def _run_run_export() -> int:
    result = run_learning_export(project_root=_resolve_project_root())
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") == "failed":
        return 1
    try:
        eval_result = _run_evaluate(run_id=None, policies=None)
        if eval_result != 0:
            logger.warning("Post-export evaluation returned non-zero")
    except Exception as exc:
        logger.warning("Post-export evaluation failed: %s", exc)
    return 0


def _run_evaluate(run_id: str | None, policies: str | None) -> int:
    from src.learning.evaluation.counterfactual import run_counterfactual_evaluation
    from src.learning.evaluation.policies import PolicyId

    policy_list = None
    if policies:
        policy_list = [PolicyId(p.strip()) for p in policies.split(",") if p.strip()]
    result = run_counterfactual_evaluation(
        project_root=_resolve_project_root(),
        run_id=run_id,
        policies=policy_list,
        write_report=True,
    )
    print(json.dumps(result, indent=2, default=str))
    return 1 if result.get("status") == "failed" else 0


def _run_gates_check(run_id: str | None) -> int:
    from src.data.models import LearningEvaluationRun
    from src.learning.evaluation.gates import check_promotion_gates

    session = get_session()
    try:
        if run_id:
            row = session.query(LearningEvaluationRun).filter(LearningEvaluationRun.run_id == run_id).first()
        else:
            row = (
                session.query(LearningEvaluationRun)
                .order_by(LearningEvaluationRun.created_at.desc())
                .first()
            )
        if row is None:
            print(json.dumps({"error": "no evaluation run found"}, indent=2))
            return 2
        metrics = json.loads(row.metrics_json) if row.metrics_json else {}
        train_metrics = {}
        artifact_id = row.artifact_run_id or metrics.get("artifact_run_id")
        if artifact_id:
            metrics_path = _resolve_project_root() / "data" / "learning" / "reports" / artifact_id / "metrics.json"
            if metrics_path.exists():
                train_metrics = json.loads(metrics_path.read_text())
        from src.learning.evaluation.outcome_join import shadow_summary

        shadow = shadow_summary(days=30)
        gates = check_promotion_gates(
            evaluation_metrics=metrics,
            train_metrics=train_metrics,
            closed_trades=int(row.closed_trades or 0),
            shadow_days=int(shadow.get("span_days") or 0),
            shadow_rows=int(shadow.get("total_scores") or 0),
        )
        print(json.dumps(gates.to_dict(), indent=2))
        return 0 if not gates.stop_the_line else 1
    finally:
        session.close()


def _run_shadow_outcome_join() -> int:
    from src.learning.evaluation.outcome_join import join_shadow_outcomes

    result = join_shadow_outcomes()
    print(json.dumps(result, indent=2))
    return 1 if result.get("status") == "failed" else 0


def _run_sync_embeddings() -> int:
    from src.learning.memory.vector_store import build_index_from_jsonl

    result = build_index_from_jsonl()
    print(json.dumps(result, indent=2))
    return 0


def _run_sync_neo4j() -> int:
    from src.utils.config import get_settings

    if not get_settings().learning_neo4j_enabled:
        print(
            "Neo4j sync disabled (learning.neo4j_enabled=false). "
            "Enable for local dev or re-deploy US-6.4 on the VPS."
        )
        return 1
    from src.learning.memory.neo4j_sync import sync_neo4j

    result = sync_neo4j()
    print(json.dumps(result, indent=2))
    return 0


def _run_sync_graphiti() -> int:
    from src.learning.memory.graphiti_sync import sync_graphiti_episodes

    result = sync_graphiti_episodes()
    print(json.dumps(result, indent=2))
    return 0


def _run_train(args: argparse.Namespace) -> int:
    from src.learning.dataset.splits import WalkForwardSplitter
    from src.learning.models.calibration import fit_conviction_calibrator
    from src.learning.reports import LearningReport, write_report

    spec = get_default_spec()
    project_root = _resolve_project_root()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    booster_dir = project_root / "data" / "learning" / "models" / run_id
    report_dir = project_root / "data" / "learning" / "reports" / run_id

    with DatasetBuilder(project_root=str(project_root)) as builder:
        result = builder.build(write=True)
    merged_path = Path(result.paths["merged"])
    if not merged_path.exists():
        logger.error("Merged parquet missing at %s", merged_path)
        return 2
    df = pd.read_parquet(merged_path)
    if df.empty:
        logger.error("Merged dataset is empty; aborting training.")
        return 3

    calibrator = fit_conviction_calibrator(df)
    calibrator.save(booster_dir / "calibrator")
    logger.info("Calibrator fitted on %s rows", len(df))

    gbm_result = None
    stall_result = None
    splits = WalkForwardSplitter(embargo_days=spec.labels.embargo_days).split(df["decision_ts"].tolist())
    if not args.skip_gbm:
        try:
            from src.learning.models.gbm import train_lightgbm_walk_forward

            gbm_result = train_lightgbm_walk_forward(
                df,
                walk_forward=splits,
                booster_dir=str(booster_dir / "gbm"),
                seed=args.seed,
            )
        except Exception as exc:  # pragma: no cover - LightGBM optional / data dependent
            logger.warning("LightGBM training failed: %s", exc)
    if not args.skip_stall:
        try:
            from src.learning.models.stall import train_stall_model

            stall_result = train_stall_model(
                df,
                walk_forward=splits,
                seed=args.seed,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Stall training failed: %s", exc)

    baseline_metrics: dict[str, Any] = _baseline_metrics(df)
    report = LearningReport(
        run_id=run_id,
        dataset_version=spec.version,
        rows=int(len(df)),
        label_distribution=result.label_distribution,
        calibrator=calibrator,
        gbm_result=gbm_result,
        stall_result=stall_result,
        baseline_metrics=baseline_metrics,
        metadata={
            "dataset_paths": result.paths,
            "dataset_checksum": result.checksum,
            "embargo_days": spec.labels.embargo_days,
            "horizons_days": list(spec.labels.horizons_days),
            "label_config": asdict(spec.labels),
            "git_commit": _git_commit_short(),
        },
    )
    paths = write_report(report, report_dir)

    insights_paths: dict[str, str] = {}
    try:
        from src.learning.visualisations import render_insight_charts

        insights_paths = render_insight_charts(
            df=df,
            gbm_result=gbm_result,
            calibrator=calibrator,
            output_dir=report_dir / "insights",
        )
    except Exception as exc:  # pragma: no cover - matplotlib optional / data dependent
        logger.warning("Insight rendering failed: %s", exc)

    metrics_dict = report.to_metrics_dict()
    metrics_dict["insights"] = insights_paths
    train_warnings: list[str] = []
    if not args.skip_gbm and gbm_result is None:
        train_warnings.append("gbm_training_failed")
    if not args.skip_stall and stall_result is None:
        train_warnings.append("stall_training_failed")
    if train_warnings:
        metrics_dict["train_warnings"] = train_warnings

    artifact_paths = {**paths, **result.paths}
    if insights_paths:
        artifact_paths["insights_dir"] = str(report_dir / "insights")
    _record_learning_run(
        run_id=run_id,
        dataset_version=spec.version,
        rows=int(len(df)),
        label_distribution=result.label_distribution,
        metrics=metrics_dict,
        paths=artifact_paths,
        checksum=result.checksum,
    )

    try:
        from src.learning.tracking import mirror_train_run_to_mlflow

        mirror_train_run_to_mlflow(
            run_id=run_id,
            dataset_version=spec.version,
            seed=args.seed,
            metrics=metrics_dict,
            booster_dir=booster_dir,
            label_config=asdict(spec.labels),
            git_commit=_git_commit_short(),
        )
    except Exception as exc:
        logger.warning("MLflow mirror logging failed (non-fatal): %s", exc)

    _maybe_promote_champion(
        run_id=run_id,
        dataset_version=spec.version,
        promote=bool(getattr(args, "promote", False)),
    )

    try:
        _run_evaluate(run_id=f"eval-post-{run_id}", policies=None)
    except Exception as exc:
        logger.warning("Post-train evaluation failed: %s", exc)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "paths": paths,
                "insights": insights_paths,
                "rows": len(df),
            },
            indent=2,
        )
    )
    return 0


def _run_visualize(run_id: str) -> int:
    project_root = _resolve_project_root()
    parquet_dir = project_root / get_default_spec().output_dir / "parquet" / get_default_spec().version
    merged_path = parquet_dir / "merged.parquet"
    if not merged_path.exists():
        logger.error("Merged parquet missing at %s; run `build` first.", merged_path)
        return 2
    df = pd.read_parquet(merged_path)
    report_dir = project_root / "data" / "learning" / "reports" / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    try:
        from src.learning.visualisations import render_insight_charts
    except Exception as exc:
        logger.error("Cannot import visualisations module: %s", exc)
        return 5
    metrics_path = report_dir / "metrics.json"
    gbm_result = None
    calibrator = None
    if metrics_path.exists():
        try:
            # Artefacts come only from paths written by ``train`` (operator-local FS).
            import pickle  # nosec B403

            booster_dir = project_root / "data" / "learning" / "models" / run_id
            calibrator_path = booster_dir / "calibrator" / "calibrator.pkl"
            if calibrator_path.exists():
                with open(calibrator_path, "rb") as fh:
                    calibrator = pickle.load(fh)  # nosec B301
        except Exception:  # pragma: no cover - optional
            calibrator = None
    paths = render_insight_charts(
        df=df,
        gbm_result=gbm_result,
        calibrator=calibrator,
        output_dir=report_dir / "insights",
    )
    print(json.dumps({"run_id": run_id, "insights": paths}, indent=2))
    return 0


def _run_list_runs(limit: int) -> int:
    session = get_session()
    try:
        rows = (
            session.query(LearningRun)
            .order_by(LearningRun.created_at.desc())
            .limit(limit)
            .all()
        )
        out = [
            {
                "id": r.id,
                "run_id": r.run_id,
                "dataset_version": r.dataset_version,
                "model_kind": r.model_kind,
                "rows": r.rows,
                "status": r.status,
                "is_champion": bool(r.is_champion),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "label_distribution": (
                    json.loads(r.label_distribution_json) if r.label_distribution_json else None
                ),
            }
            for r in rows
        ]
        print(json.dumps(out, indent=2))
        return 0
    finally:
        session.close()


def _run_report(run_id: str) -> int:
    project_root = _resolve_project_root()
    report_dir = project_root / "data" / "learning" / "reports" / run_id
    metrics_path = report_dir / "metrics.json"
    if not metrics_path.exists():
        logger.error("No saved metrics at %s", metrics_path)
        return 4
    print(metrics_path.read_text())
    return 0


def _maybe_promote_champion(*, run_id: str, dataset_version: str, promote: bool) -> None:
    """Promote a run when requested or when no champion exists for the version."""
    from src.data.models import LearningRun
    from src.learning.registry import promote_champion_run

    session = get_session()
    try:
        if not promote:
            explicit = (
                session.query(LearningRun)
                .filter(
                    LearningRun.dataset_version == dataset_version,
                    LearningRun.status == "completed",
                    LearningRun.is_champion.is_(True),
                )
                .first()
            )
            if explicit is not None:
                return
        promote_champion_run(session, run_id)
        logger.info("Promoted %s as champion for %s", run_id, dataset_version)
    except Exception as exc:
        session.rollback()
        logger.warning("Champion promotion failed for %s: %s", run_id, exc)
    finally:
        session.close()


def _run_promote(run_id: str) -> int:
    from src.learning.registry import promote_champion_run

    session = get_session()
    try:
        row = promote_champion_run(session, run_id)
        print(
            json.dumps(
                {
                    "run_id": row.run_id,
                    "dataset_version": row.dataset_version,
                    "is_champion": bool(row.is_champion),
                },
                indent=2,
            )
        )
        return 0
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2
    finally:
        session.close()


def _record_learning_run(
    *,
    run_id: str,
    dataset_version: str,
    rows: int,
    label_distribution: dict[str, int],
    metrics: dict[str, Any],
    paths: dict[str, str],
    checksum: str | None,
    status: str = "completed",
    model_kind: str = "bundle",
) -> None:
    """Persist a row in ``learning_runs`` describing this training run.

    Heavy artifacts stay on disk under ``data/learning/``; this row just
    captures the metadata operators need to navigate the bundle from the
    dashboard. Failures here are logged but never raised so we don't
    crash a successful training run.
    """
    session = get_session()
    try:
        existing = session.query(LearningRun).filter(LearningRun.run_id == run_id).first()
        payload = {
            "dataset_version": dataset_version,
            "model_kind": model_kind,
            "status": status,
            "rows": int(rows),
            "label_distribution_json": json.dumps(label_distribution, default=str),
            "metrics_json": json.dumps(metrics, default=str),
            "artifact_paths_json": json.dumps(paths, default=str),
            "checksum": checksum,
        }
        if existing is not None:
            for key, value in payload.items():
                setattr(existing, key, value)
        else:
            session.add(LearningRun(run_id=run_id, **payload))
        session.commit()
        logger.info("Listed run %s in learning_runs", run_id)
    except Exception as exc:  # pragma: no cover - DB write failures must not abort
        session.rollback()
        logger.warning("Failed to persist learning_runs row for %s: %s", run_id, exc)
    finally:
        session.close()


def _baseline_metrics(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or "label_3class" not in df.columns:
        return {}
    label = df["label_3class"].astype(str)
    counts = label.value_counts(normalize=True).to_dict()
    baseline: dict[str, Any] = {"class_priors": {k: float(v) for k, v in counts.items()}}
    if "conviction" in df.columns and "label_3class" in df.columns:
        win_rate_by_bin = (
            df.assign(
                conviction_bin=pd.cut(
                    df["conviction"].astype(float),
                    bins=[0, 50, 60, 70, 80, 100.001],
                    right=False,
                    include_lowest=True,
                )
            )
            .groupby("conviction_bin", observed=False)["label_3class"]
            .apply(lambda series: float((series == "big_winner").mean()))
            .to_dict()
        )
        baseline["conviction_only_win_rate"] = {str(k): v for k, v in win_rate_by_bin.items()}
    return baseline


def main() -> int:
    args = _parse_args()
    if args.command == "audit":
        return _run_audit()
    if args.command == "build":
        return _run_build(no_write=args.no_write)
    if args.command == "train":
        return _run_train(args)
    if args.command == "report":
        return _run_report(args.run_id)
    if args.command == "visualize":
        return _run_visualize(args.run_id)
    if args.command == "export":
        return _run_export()
    if args.command == "export-memory":
        return _run_export_memory()
    if args.command == "run-export":
        return _run_run_export()
    if args.command == "sync-embeddings":
        return _run_sync_embeddings()
    if args.command == "sync-neo4j":
        return _run_sync_neo4j()
    if args.command == "sync-graphiti":
        return _run_sync_graphiti()
    if args.command == "list-runs":
        return _run_list_runs(args.limit)
    if args.command == "promote":
        return _run_promote(args.run_id)
    if args.command == "evaluate":
        return _run_evaluate(args.run_id, args.policies)
    if args.command == "gates":
        if args.gates_command == "check":
            return _run_gates_check(args.run_id)
    if args.command == "shadow-outcome-join":
        return _run_shadow_outcome_join()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
