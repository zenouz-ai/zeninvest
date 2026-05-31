"""Temporal episode export for Graphiti (US-6.5 research surface)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.learning.spec import get_text_corpus_spec
from src.utils.logger import get_logger

logger = get_logger("learning.memory.graphiti")


def _project_root() -> Path:
    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


def sync_graphiti_episodes(jsonl_path: str | Path | None = None) -> dict[str, Any]:
    """Build temporal episode JSON from memory bundle (Graphiti-ready).

    Full Graphiti Docker integration is optional; this writes a local episode
    archive operators can ingest when Graphiti is enabled.
    """
    root = _project_root()
    spec = get_text_corpus_spec()
    path = Path(jsonl_path) if jsonl_path else root / spec.memory_bundle_path()
    if not path.exists():
        raise FileNotFoundError(f"memory bundle missing: {path}")

    episodes: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            doc = json.loads(line)
            meta = doc.get("metadata") or {}
            episodes.append(
                {
                    "episode_id": doc.get("doc_id"),
                    "valid_at": doc.get("decision_ts"),
                    "entity": doc.get("ticker"),
                    "regime": meta.get("macro_regime"),
                    "outcome_label": meta.get("label_3class"),
                    "pnl_pct": meta.get("realized_pnl_pct"),
                    "narrative": (doc.get("body") or "")[:4000],
                    "source_cycle_id": doc.get("cycle_id"),
                }
            )

    out_dir = root / "data" / "learning" / "graphiti" / spec.version
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "episodes.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": spec.version,
        "episodes": episodes,
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote %s Graphiti episodes to %s", len(episodes), out_path)
    return {"episodes": len(episodes), "path": str(out_path)}
