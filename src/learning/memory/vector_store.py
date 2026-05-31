"""Local vector index for similar-case retrieval (US-6.2)."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from src.learning.spec import get_text_corpus_spec
from src.utils.logger import get_logger

logger = get_logger("learning.memory.vector")


def _project_root() -> Path:
    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


def _index_path() -> Path:
    spec = get_text_corpus_spec()
    return _project_root() / spec.vector_index_path()


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def load_index() -> list[dict[str, Any]]:
    path = _index_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def save_index(rows: list[dict[str, Any]]) -> str:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")
    return str(path)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed via OpenAI text-embedding-3-small."""
    from openai import OpenAI

    from src.utils.config import get_settings

    settings = get_settings()
    api_key = settings.openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY required for embeddings")
    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [item.embedding for item in response.data]


def build_index_from_jsonl(jsonl_path: str | Path | None = None) -> dict[str, Any]:
    """Read memory_bundle.jsonl, embed bodies, write index.jsonl."""
    root = _project_root()
    spec = get_text_corpus_spec()
    path = Path(jsonl_path) if jsonl_path else root / spec.memory_bundle_path()
    if not path.exists():
        raise FileNotFoundError(f"memory bundle missing: {path}")

    docs: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                docs.append(json.loads(line))
    if not docs:
        return {"indexed": 0, "path": str(_index_path())}

    bodies = [d.get("body") or "" for d in docs]
    vectors = embed_texts(bodies)
    rows: list[dict[str, Any]] = []
    for doc, vec in zip(docs, vectors):
        rows.append(
            {
                "doc_id": doc.get("doc_id"),
                "cycle_id": doc.get("cycle_id"),
                "ticker": doc.get("ticker"),
                "decision_ts": doc.get("decision_ts"),
                "metadata": doc.get("metadata") or {},
                "embedding": vec,
            }
        )
    out = save_index(rows)
    return {"indexed": len(rows), "path": out}


def search_similar(
    query_text: str,
    *,
    as_of_ts: str | None = None,
    ticker: str | None = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Return top-k similar documents by cosine similarity."""
    index = load_index()
    if not index:
        return []
    query_vec = embed_texts([query_text])[0]
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in index:
        if as_of_ts and row.get("decision_ts") and row["decision_ts"] >= as_of_ts:
            continue
        if ticker and row.get("ticker") != ticker:
            continue
        vec = row.get("embedding") or []
        score = _cosine(query_vec, vec)
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, row in scored[:k]:
        results.append(
            {
                "score": score,
                "doc_id": row.get("doc_id"),
                "cycle_id": row.get("cycle_id"),
                "ticker": row.get("ticker"),
                "decision_ts": row.get("decision_ts"),
                "metadata": row.get("metadata") or {},
            }
        )
    return results
