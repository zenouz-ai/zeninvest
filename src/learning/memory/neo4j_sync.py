"""Sync memory_bundle.jsonl into Neo4j (US-6.4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.learning.spec import get_text_corpus_spec
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("learning.memory.neo4j")


def sync_neo4j(jsonl_path: str | Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    password = settings.learning_neo4j_password
    if not password:
        raise RuntimeError("NEO4J_PASSWORD env var required for Neo4j sync")

    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Install memory extras: poetry install --with memory") from exc

    root = Path(__file__).resolve().parents[3]
    spec = get_text_corpus_spec()
    path = Path(jsonl_path) if jsonl_path else root / spec.memory_bundle_path()
    if not path.exists():
        raise FileNotFoundError(f"memory bundle missing: {path}")

    driver = GraphDatabase.driver(
        settings.learning_neo4j_uri,
        auth=(settings.learning_neo4j_user, password),
    )
    nodes = 0
    edges = 0
    with driver.session() as session:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                doc = json.loads(line)
                meta = doc.get("metadata") or {}
                session.run(
                    """
                    MERGE (d:Decision {doc_id: $doc_id})
                    SET d.cycle_id = $cycle_id, d.ticker = $ticker, d.decision_ts = $decision_ts,
                        d.action = $action, d.conviction = $conviction, d.label = $label,
                        d.pnl_pct = $pnl_pct, d.macro_regime = $macro_regime, d.sector = $sector
                    MERGE (i:Instrument {ticker: $ticker})
                    SET i.sector = $sector
                    MERGE (d)-[:ON_TICKER]->(i)
                    """,
                    doc_id=doc.get("doc_id"),
                    cycle_id=doc.get("cycle_id"),
                    ticker=doc.get("ticker"),
                    decision_ts=doc.get("decision_ts"),
                    action=meta.get("action"),
                    conviction=meta.get("conviction"),
                    label=meta.get("label_3class"),
                    pnl_pct=meta.get("realized_pnl_pct"),
                    macro_regime=meta.get("macro_regime"),
                    sector=meta.get("sector"),
                )
                nodes += 1
                if meta.get("macro_regime"):
                    session.run(
                        """
                        MATCH (d:Decision {doc_id: $doc_id})
                        MERGE (m:MacroRegime {regime: $regime})
                        MERGE (d)-[:DURING]->(m)
                        """,
                        doc_id=doc.get("doc_id"),
                        regime=meta.get("macro_regime"),
                    )
                    edges += 1
    driver.close()
    return {"nodes_upserted": nodes, "edges_upserted": edges}


def query_similar_sector_regime(sector: str, regime: str, limit: int = 10) -> list[dict[str, Any]]:
    """Parameterized read-only Cypher for dashboard API."""
    settings = get_settings()
    password = settings.learning_neo4j_password
    if not password:
        return []
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return []

    driver = GraphDatabase.driver(
        settings.learning_neo4j_uri,
        auth=(settings.learning_neo4j_user, password),
    )
    rows: list[dict[str, Any]] = []
    with driver.session() as session:
        result = session.run(
            """
            MATCH (d:Decision)-[:ON_TICKER]->(i:Instrument)
            MATCH (d)-[:DURING]->(m:MacroRegime {regime: $regime})
            WHERE i.sector = $sector
            RETURN d.cycle_id AS cycle_id, d.ticker AS ticker, d.label AS label,
                   d.pnl_pct AS pnl_pct, d.decision_ts AS decision_ts
            ORDER BY d.decision_ts DESC
            LIMIT $limit
            """,
            sector=sector,
            regime=regime,
            limit=limit,
        )
        for record in result:
            rows.append(dict(record))
    driver.close()
    return rows
