"""Research tool-call influence attribution for offline evaluation."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from src.data.models import ModerationLog, ResearchLog
from src.learning.evaluation.counterfactual import _is_bad_row


def _research_bucket(total: float | int | None) -> str:
    if total is None or pd.isna(total):
        return "unknown"
    n = int(total)
    if n == 0:
        return "0"
    if n <= 2:
        return "1-2"
    if n <= 5:
        return "3-5"
    return "6+"


def _tokenize_query(query: str | None) -> set[str]:
    if not query:
        return set()
    tokens = re.findall(r"[a-z0-9]{4,}", query.lower())
    return {t for t in tokens if t not in {"with", "from", "that", "this", "what", "when", "have"}}


def _reasoning_cites_query(reasoning: str | None, query: str | None) -> bool:
    if not reasoning or not query:
        return False
    text = reasoning.lower()
    tokens = _tokenize_query(query)
    if not tokens:
        return query.lower()[:20] in text if len(query) >= 8 else False
    hits = sum(1 for t in tokens if t in text)
    return hits >= max(1, len(tokens) // 3)


def compute_query_overlap_pct(session: Session, cycle_ids: set[str]) -> float | None:
    """Mean pairwise Jaccard similarity of queries across members per cycle/ticker."""
    if not cycle_ids:
        return None
    rows = (
        session.query(ResearchLog)
        .filter(ResearchLog.cycle_id.in_(list(cycle_ids)))
        .filter(ResearchLog.query.isnot(None))
        .all()
    )
    if not rows:
        return None

    by_key: dict[tuple[str, str], dict[str, set[str]]] = {}
    for row in rows:
        key = (str(row.cycle_id), str(row.ticker or ""))
        member_sets = by_key.setdefault(key, {})
        member_sets.setdefault(str(row.member), set()).update(_tokenize_query(row.query))

    scores: list[float] = []
    for member_sets in by_key.values():
        members = list(member_sets.values())
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if not a and not b:
                    continue
                union = a | b
                if not union:
                    continue
                scores.append(len(a & b) / len(union))

    return float(sum(scores) / len(scores)) if scores else None


def compute_research_descriptive(df: pd.DataFrame, session: Session) -> dict[str, Any]:
    """Aggregate research call stats from dataset + DB overlap."""
    if df.empty:
        return {
            "calls_by_member": {},
            "calls_by_tool": {},
            "cache_hit_rate": None,
            "mean_cost_usd": None,
            "query_overlap_pct": None,
            "total_decisions_with_research": 0,
        }

    total_col = df.get("research_calls_total", pd.Series(dtype=float))
    cache_col = df.get("research_cache_hit_rate", pd.Series(dtype=float))
    cost_col = df.get("research_cost_usd", pd.Series(dtype=float))

    member_cols = [c for c in df.columns if c.startswith("research_member_") and c.endswith("_count")]
    tool_cols = [c for c in df.columns if c.startswith("research_") and c.endswith("_count") and "member" not in c and c != "research_calls_total"]

    calls_by_member: dict[str, int] = {}
    for col in member_cols:
        label = col.replace("research_member_", "").replace("_count", "")
        calls_by_member[label] = int(df[col].fillna(0).sum())

    calls_by_tool: dict[str, int] = {}
    for col in tool_cols:
        label = col.replace("research_", "").replace("_count", "")
        calls_by_tool[label] = int(df[col].fillna(0).sum())

    cycle_ids = set(df["cycle_id"].dropna().astype(str).unique()) if "cycle_id" in df.columns else set()

    return {
        "calls_by_member": calls_by_member,
        "calls_by_tool": calls_by_tool,
        "cache_hit_rate": float(cache_col.mean()) if cache_col.notna().any() else None,
        "mean_cost_usd": float(cost_col.mean()) if cost_col.notna().any() else None,
        "query_overlap_pct": compute_query_overlap_pct(session, cycle_ids),
        "total_decisions_with_research": int((total_col.fillna(0) > 0).sum()) if len(total_col) else 0,
    }


def compute_research_stratified(df: pd.DataFrame) -> dict[str, Any]:
    """Outcome bad-rates stratified by research intensity and tools."""
    if df.empty or "research_calls_total" not in df.columns:
        return {"by_intensity": [], "by_skeptic_research": [], "by_news_search": [], "by_moderation_when_research": []}

    work = df.copy()
    work["bad"] = work.apply(_is_bad_row, axis=1).astype(int)
    work["intensity_bucket"] = work["research_calls_total"].apply(_research_bucket)

    by_intensity: list[dict[str, Any]] = []
    for bucket, group in work.groupby("intensity_bucket"):
        by_intensity.append(
            {
                "bucket": str(bucket),
                "n": int(len(group)),
                "bad_rate": float(group["bad"].mean()),
            }
        )

    skeptic_col = "research_member_skeptic_count"
    by_skeptic: list[dict[str, Any]] = []
    if skeptic_col in work.columns:
        work["skeptic_research"] = work[skeptic_col].fillna(0) > 0
        for flag, group in work.groupby("skeptic_research"):
            by_skeptic.append(
                {
                    "skeptic_research": bool(flag),
                    "n": int(len(group)),
                    "bad_rate": float(group["bad"].mean()),
                }
            )

    by_news: list[dict[str, Any]] = []
    if "research_news_search_count" in work.columns:
        work["has_news_search"] = work["research_news_search_count"].fillna(0) > 0
        for flag, group in work.groupby("has_news_search"):
            by_news.append(
                {
                    "has_news_search": bool(flag),
                    "n": int(len(group)),
                    "bad_rate": float(group["bad"].mean()),
                }
            )

    by_mod: list[dict[str, Any]] = []
    if "gpt_verdict" in work.columns:
        researched = work[work["research_calls_total"].fillna(0) > 0]
        if not researched.empty:
            for verdict, group in researched.groupby(researched["gpt_verdict"].fillna("UNKNOWN")):
                by_mod.append(
                    {
                        "gpt_verdict_when_research": str(verdict),
                        "n": int(len(group)),
                        "bad_rate": float(group["bad"].mean()),
                    }
                )

    return {
        "by_intensity": by_intensity,
        "by_skeptic_research": by_skeptic,
        "by_news_search": by_news,
        "by_moderation_when_research": by_mod,
    }


def compute_citation_stratified(session: Session, df: pd.DataFrame) -> dict[str, Any]:
    """Heuristic: moderator reasoning contains tokens from research queries."""
    if df.empty or "cycle_id" not in df.columns or "ticker" not in df.columns:
        return {"by_cited": [], "citation_rate": None}

    keys = list(zip(df["cycle_id"].astype(str), df["ticker"].astype(str)))
    unique_keys = list(dict.fromkeys(keys))

    research_by_key: dict[tuple[str, str], list[ResearchLog]] = {}
    moderation_by_key: dict[tuple[str, str], list[ModerationLog]] = {}

    if unique_keys:
        cycle_ids = {k[0] for k in unique_keys}
        tickers = {k[1] for k in unique_keys}
        research_rows = (
            session.query(ResearchLog)
            .filter(ResearchLog.cycle_id.in_(list(cycle_ids)))
            .filter(ResearchLog.ticker.in_(list(tickers)))
            .all()
        )
        for row in research_rows:
            key = (str(row.cycle_id), str(row.ticker or ""))
            research_by_key.setdefault(key, []).append(row)

        mod_rows = (
            session.query(ModerationLog)
            .filter(ModerationLog.cycle_id.in_(list(cycle_ids)))
            .filter(ModerationLog.ticker.in_(list(tickers)))
            .filter(ModerationLog.moderator.in_(["gpt-4o", "gemini-2.5-flash", "gemini-2.0-flash"]))
            .all()
        )
        for row in mod_rows:
            key = (str(row.cycle_id), str(row.ticker))
            moderation_by_key.setdefault(key, []).append(row)

    cited_flags: list[bool] = []
    work = df.copy()
    work["bad"] = work.apply(_is_bad_row, axis=1).astype(int)
    work["research_cited"] = False

    for idx, row in work.iterrows():
        key = (str(row["cycle_id"]), str(row["ticker"]))
        research = research_by_key.get(key, [])
        mods = moderation_by_key.get(key, [])
        if not research or not mods:
            continue
        cited = False
        for mod in mods:
            for res in research:
                if res.member == "skeptic" and mod.moderator != "gpt-4o":
                    continue
                if res.member == "risk" and "gemini" not in (mod.moderator or ""):
                    continue
                if _reasoning_cites_query(mod.reasoning, res.query):
                    cited = True
                    break
            if cited:
                break
        work.at[idx, "research_cited"] = cited
        if research:
            cited_flags.append(cited)

    by_cited: list[dict[str, Any]] = []
    researched_mask = work["research_calls_total"].fillna(0) > 0 if "research_calls_total" in work.columns else pd.Series(True, index=work.index)
    subset = work[researched_mask]
    if not subset.empty:
        for cited, group in subset.groupby("research_cited"):
            by_cited.append(
                {
                    "research_cited_in_reasoning": bool(cited),
                    "n": int(len(group)),
                    "bad_rate": float(group["bad"].mean()),
                }
            )

    citation_rate = float(sum(cited_flags) / len(cited_flags)) if cited_flags else None

    return {"by_cited": by_cited, "citation_rate": citation_rate}


def build_research_influence_report(session: Session, df: pd.DataFrame) -> dict[str, Any]:
    """Full research influence payload for evaluate + dashboard."""
    return {
        "descriptive": compute_research_descriptive(df, session),
        "stratified": compute_research_stratified(df),
        "citation": compute_citation_stratified(session, df),
    }
