"""Read-only helpers for learning dataset artifacts on disk."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.learning.spec import DatasetSpec, TextCorpusSpec
from src.utils.logger import get_logger

logger = get_logger("dashboard.learning_datasets")

PARQUET_ARTIFACTS = frozenset({"decisions", "features", "outcomes", "merged", "text_corpus", "rejected"})
JSON_ARTIFACTS = frozenset({"schema", "splits"})
TEXT_TRUNCATE = 600


def is_safe_version(version: str) -> bool:
    return bool(version) and version.replace("_", "").replace("-", "").isalnum() and ".." not in version


def learning_root(project_root: Path) -> Path:
    return project_root / "data" / "learning"


def list_dataset_versions(project_root: Path) -> list[str]:
    parquet_root = learning_root(project_root) / "parquet"
    if not parquet_root.exists():
        return []
    return sorted(
        p.name for p in parquet_root.iterdir() if p.is_dir() and is_safe_version(p.name)
    )


def _file_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "exists": True,
    }


def dataset_manifest(project_root: Path, version: str) -> dict[str, Any]:
    if not is_safe_version(version):
        raise ValueError("invalid dataset version")

    spec = DatasetSpec(version=version)
    corpus_spec = TextCorpusSpec(version=version)
    root = project_root / spec.output_dir / "parquet" / version
    exports_root = project_root / spec.output_dir / "exports" / version
    graphiti_path = project_root / spec.output_dir / "graphiti" / version / "episodes.json"
    vector_path = project_root / corpus_spec.vector_index_path()

    artifacts: dict[str, Any] = {}
    paths_map = dict(spec.parquet_paths())
    paths_map["merged"] = f"{spec.output_dir}/parquet/{version}/merged.parquet"
    paths_map["rejected"] = f"{spec.output_dir}/parquet/{version}/rejected.parquet"

    for key, rel in paths_map.items():
        path = project_root / rel
        kind = "json" if key in JSON_ARTIFACTS else "parquet"
        if path.exists():
            info = _file_info(path)
            info["kind"] = kind
            artifacts[key] = info
        else:
            artifacts[key] = {"exists": False, "path": str(path), "kind": kind}

    memory_bundle = project_root / corpus_spec.memory_bundle_path()
    extras: dict[str, Any] = {
        "memory_bundle": _file_info(memory_bundle) if memory_bundle.exists() else {"exists": False, "path": str(memory_bundle), "kind": "jsonl"},
        "graphiti_episodes": _file_info(graphiti_path) if graphiti_path.exists() else {"exists": False, "path": str(graphiti_path), "kind": "json"},
        "vector_index": _file_info(vector_path) if vector_path.exists() else {"exists": False, "path": str(vector_path), "kind": "jsonl"},
    }

    schema_summary: dict[str, Any] | None = None
    schema_path = root / "schema.json"
    if schema_path.exists():
        try:
            schema_summary = json.loads(schema_path.read_text())
        except json.JSONDecodeError:
            schema_summary = None

    audit_dir = learning_root(project_root)
    audit_files = (
        sorted(p.name for p in audit_dir.glob("audit_*.json"))
        if audit_dir.exists()
        else []
    )

    return {
        "version": version,
        "parquet_dir": str(root),
        "exports_dir": str(exports_root),
        "artifacts": artifacts,
        "extras": extras,
        "schema": schema_summary,
        "audit_files": audit_files[-5:],
    }


def _resolve_parquet_path(project_root: Path, version: str, artifact: str) -> Path:
    if artifact not in PARQUET_ARTIFACTS:
        raise ValueError("unknown parquet artifact")
    spec = DatasetSpec(version=version)
    if artifact == "merged":
        rel = f"{spec.output_dir}/parquet/{version}/merged.parquet"
    elif artifact == "rejected":
        rel = f"{spec.output_dir}/parquet/{version}/rejected.parquet"
    else:
        rel = spec.parquet_paths().get(artifact)
        if not rel:
            raise ValueError("unknown artifact")
    path = (project_root / rel).resolve()
    expected_root = (project_root / spec.output_dir / "parquet" / version).resolve()
    if expected_root not in path.parents:
        raise ValueError("invalid path")
    return path


def preview_parquet(
    project_root: Path,
    version: str,
    artifact: str,
    *,
    offset: int = 0,
    limit: int = 25,
) -> dict[str, Any]:
    path = _resolve_parquet_path(project_root, version, artifact)
    if not path.exists():
        raise FileNotFoundError(str(path))

    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pandas required") from exc

    df = pd.read_parquet(path)
    total = int(len(df))
    slice_df = df.iloc[offset : offset + limit].copy()

    if artifact == "text_corpus":
        for col in ("body", "strategy_reasoning", "gpt_reasoning", "gemini_reasoning", "risk_reasoning"):
            if col in slice_df.columns:
                slice_df[col] = slice_df[col].apply(
                    lambda v: (str(v)[:TEXT_TRUNCATE] + "…") if isinstance(v, str) and len(v) > TEXT_TRUNCATE else v
                )

    records: list[dict[str, Any]] = []
    for row in slice_df.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            elif isinstance(v, (dict, list, str, int, float, bool)) or v is None:
                clean[k] = v
            else:
                clean[k] = str(v)
        records.append(clean)

    return {
        "artifact": artifact,
        "version": version,
        "total_rows": total,
        "offset": offset,
        "limit": limit,
        "columns": list(df.columns),
        "rows": records,
    }


def preview_memory_bundle(
    project_root: Path,
    version: str,
    *,
    offset: int = 0,
    limit: int = 25,
) -> dict[str, Any]:
    spec = TextCorpusSpec(version=version)
    path = project_root / spec.memory_bundle_path()
    if not path.exists():
        raise FileNotFoundError(str(path))

    lines: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for idx, line in enumerate(fh):
            if idx < offset:
                continue
            if len(lines) >= limit:
                break
            lines.append(line.rstrip("\n"))

    total = 0
    with open(path, encoding="utf-8") as fh:
        for _ in fh:
            total += 1

    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        body = doc.get("body") or ""
        if isinstance(body, str) and len(body) > TEXT_TRUNCATE:
            doc = {**doc, "body": body[:TEXT_TRUNCATE] + "…", "body_truncated": True}
        rows.append(doc)

    return {
        "artifact": "memory_bundle",
        "version": version,
        "total_rows": total,
        "offset": offset,
        "limit": limit,
        "rows": rows,
    }


def read_json_artifact(project_root: Path, version: str, artifact: str) -> Any:
    if artifact not in JSON_ARTIFACTS:
        raise ValueError("unknown json artifact")
    spec = DatasetSpec(version=version)
    rel = spec.parquet_paths()[artifact]
    path = (project_root / rel).resolve()
    return json.loads(path.read_text())


def resolve_download_path(project_root: Path, version: str, filename: str) -> Path:
    allowed = {
        "decisions.parquet",
        "features.parquet",
        "outcomes.parquet",
        "merged.parquet",
        "rejected.parquet",
        "text_corpus.parquet",
        "schema.json",
        "splits.json",
        "memory_bundle.jsonl",
    }
    if filename not in allowed or "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("invalid filename")

    if filename == "memory_bundle.jsonl":
        path = (project_root / TextCorpusSpec(version=version).memory_bundle_path()).resolve()
    else:
        path = (project_root / "data" / "learning" / "parquet" / version / filename).resolve()

    expected_parquet = (project_root / "data" / "learning" / "parquet" / version).resolve()
    expected_exports = (project_root / "data" / "learning" / "exports" / version).resolve()
    if expected_parquet not in path.parents and expected_exports not in path.parents:
        raise ValueError("invalid download path")
    return path
