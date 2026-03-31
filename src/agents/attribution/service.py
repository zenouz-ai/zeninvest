"""Git-backed strategy episode attribution."""

from __future__ import annotations

import json
import subprocess  # nosec B404
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import CycleContextSnapshot, StrategyChangeEpisode, StrategyChangeEvidence
from src.utils.logger import get_logger

logger = get_logger("attribution")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PATH_ALLOWLIST = (
    "src/agents/strategy/",
    "src/agents/risk/",
    "src/agents/execution/",
    "src/agents/opportunity/",
    "src/agents/guidance/",
    "src/agents/market_data/data_fetcher.py",
    "src/orchestrator/main.py",
    "src/utils/config.py",
    "src/agents/strategy/prompts.py",
    "config/settings.yaml",
    "src/data/models.py",
)


@dataclass
class EpisodeCandidate:
    """Deterministic candidate episode grouped from git commits."""

    commits: list[dict[str, Any]]
    change_type: str


class StrategyAttributionService:
    """Backfill and manage strategy change episodes."""

    def backfill_recent_episodes(
        self,
        *,
        days: int = 30,
        auto_confirm: bool = True,
    ) -> list[dict[str, Any]]:
        """Scan recent git history and persist episodes.

        Args:
            days: Git history lookback window (days).
            auto_confirm: If True, episodes are persisted with status='confirmed'.
                If False, status='proposed'.

        Returns:
            List of persisted episodes with {id, title, status}.
        """
        candidates = self._scan_git(days=days)
        persisted: list[dict[str, Any]] = []
        session = get_session()
        try:
            for candidate in candidates:
                first = candidate.commits[0]
                last = candidate.commits[-1]
                if self._episode_exists(session, first["sha"], last["sha"]):
                    continue
                status = "confirmed" if auto_confirm else "proposed"
                episode = StrategyChangeEpisode(
                    status=status,
                    title=self._build_title(candidate),
                    summary=self._build_summary(candidate),
                    change_type=candidate.change_type,
                    review_confidence=0.6,
                    commit_start_sha=first["sha"],
                    commit_end_sha=last["sha"],
                    effective_start_at=first["committed_at"],
                    confirmed_at=datetime.now(timezone.utc) if auto_confirm else None,
                    notes="Observational attribution only.",
                    metadata_json=json.dumps(
                        {
                            "commit_count": len(candidate.commits),
                            "paths": sorted({path for commit in candidate.commits for path in commit["files"]}),
                        },
                        default=str,
                    ),
                )
                session.add(episode)
                session.flush()
                for commit in candidate.commits:
                    session.add(
                        StrategyChangeEvidence(
                            episode_id=int(episode.id),
                            commit_sha=commit["sha"],
                            committed_at=commit["committed_at"],
                            author_name=commit.get("author_name"),
                            title=commit["title"],
                            summary=commit.get("body"),
                            affected_files_json=json.dumps(commit["files"]),
                            metadata_json=json.dumps({"change_type": candidate.change_type}),
                        )
                    )
                persisted.append({"id": int(episode.id), "title": episode.title, "status": episode.status})
            session.commit()
            return persisted
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def confirm_episode(
        self,
        *,
        episode_id: int,
        title: str | None = None,
        summary: str | None = None,
        effective_start_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Confirm a proposed episode and return the updated row."""
        session = get_session()
        try:
            episode = session.query(StrategyChangeEpisode).filter(StrategyChangeEpisode.id == episode_id).first()
            if episode is None:
                raise ValueError(f"Episode {episode_id} not found")
            if title:
                episode.title = title
            if summary:
                episode.summary = summary
            if effective_start_at:
                episode.effective_start_at = effective_start_at
            episode.status = "confirmed"
            episode.confirmed_at = datetime.now(timezone.utc)
            session.commit()
            return self.get_episode_detail(episode_id=episode_id)
        finally:
            session.close()

    def reject_episode(self, *, episode_id: int) -> dict[str, Any]:
        """Reject a proposed episode and return the updated row."""
        session = get_session()
        try:
            episode = session.query(StrategyChangeEpisode).filter(StrategyChangeEpisode.id == episode_id).first()
            if episode is None:
                raise ValueError(f"Episode {episode_id} not found")
            episode.status = "rejected"
            episode.rejected_at = datetime.now(timezone.utc)
            session.commit()
            return self.get_episode_detail(episode_id=episode_id)
        finally:
            session.close()

    def resolve_active_episode_ids(self, *, cycle_started_at: datetime) -> list[int]:
        """Return confirmed episodes active for a given cycle start."""
        session = get_session()
        try:
            rows = (
                session.query(StrategyChangeEpisode.id)
                .filter(
                    StrategyChangeEpisode.status == "confirmed",
                    StrategyChangeEpisode.effective_start_at <= cycle_started_at,
                )
                .filter(
                    (StrategyChangeEpisode.effective_end_at.is_(None))
                    | (StrategyChangeEpisode.effective_end_at >= cycle_started_at)
                )
                .order_by(desc(StrategyChangeEpisode.effective_start_at))
                .all()
            )
            return [int(row[0]) for row in rows]
        finally:
            session.close()

    def list_episodes(self) -> list[dict[str, Any]]:
        """Return episodes ordered by newest first."""
        session = get_session()
        try:
            rows = (
                session.query(StrategyChangeEpisode)
                .order_by(desc(StrategyChangeEpisode.effective_start_at), desc(StrategyChangeEpisode.id))
                .all()
            )
            return [self._serialize_episode_summary(row) for row in rows]
        finally:
            session.close()

    def get_episode_detail(self, *, episode_id: int) -> dict[str, Any]:
        """Return a full episode detail payload with observational impact windows."""
        session = get_session()
        try:
            episode = session.query(StrategyChangeEpisode).filter(StrategyChangeEpisode.id == episode_id).first()
            if episode is None:
                raise ValueError(f"Episode {episode_id} not found")
            evidence_rows = (
                session.query(StrategyChangeEvidence)
                .filter(StrategyChangeEvidence.episode_id == episode_id)
                .order_by(StrategyChangeEvidence.committed_at.asc())
                .all()
            )
            impact = self._build_impact_summary(session, episode)
            payload = self._serialize_episode_summary(episode)
            payload["evidence"] = [
                {
                    "id": row.id,
                    "commit_sha": row.commit_sha,
                    "committed_at": row.committed_at,
                    "author_name": row.author_name,
                    "title": row.title,
                    "summary": row.summary,
                    "affected_files": json.loads(row.affected_files_json or "[]"),
                }
                for row in evidence_rows
            ]
            payload["impact_summary"] = impact
            return payload
        finally:
            session.close()

    def _build_impact_summary(self, session: Any, episode: StrategyChangeEpisode) -> dict[str, Any]:
        start = self._normalize_ts(episode.effective_start_at)
        context_rows = (
            session.query(CycleContextSnapshot)
            .filter(CycleContextSnapshot.captured_at >= start - timedelta(days=30))
            .order_by(CycleContextSnapshot.captured_at.asc())
            .all()
        )
        active_rows = [row for row in context_rows if row.captured_at >= start]
        pre_rows = [row for row in context_rows if row.captured_at < start]
        overlap_warning = any(
            json.loads(row.active_strategy_episode_ids_json or "[]")
            for row in active_rows
            if row.active_strategy_episode_ids_json and str(episode.id) not in row.active_strategy_episode_ids_json
        )
        return {
            "window_1d_cycles": self._count_within_days(active_rows, start, 1),
            "window_7d_cycles": self._count_within_days(active_rows, start, 7),
            "window_30d_cycles": self._count_within_days(active_rows, start, 30),
            "pre_cycle_count": len(pre_rows),
            "post_cycle_count": len(active_rows),
            "screening_conversion_delta": self._conversion_rate(active_rows) - self._conversion_rate(pre_rows),
            "low_sample_warning": len(active_rows) < 3,
            "overlap_warning": overlap_warning,
            "observational_only": True,
        }

    @staticmethod
    def _count_within_days(rows: list[CycleContextSnapshot], start: datetime, days: int) -> int:
        cutoff = start + timedelta(days=days)
        return sum(1 for row in rows if row.captured_at <= cutoff)

    @staticmethod
    def _conversion_rate(rows: list[CycleContextSnapshot]) -> float:
        total_pre = 0
        total_post = 0
        for row in rows:
            total_pre += int(row.pre_guidance_candidate_count or 0)
            total_post += int(row.post_guidance_candidate_count or 0)
        if total_pre <= 0:
            return 0.0
        return total_post / total_pre

    @staticmethod
    def _normalize_ts(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _episode_exists(session: Any, start_sha: str, end_sha: str) -> bool:
        return (
            session.query(StrategyChangeEpisode)
            .filter(
                StrategyChangeEpisode.commit_start_sha == start_sha,
                StrategyChangeEpisode.commit_end_sha == end_sha,
            )
            .first()
            is not None
        )

    def _scan_git(self, *, days: int) -> list[EpisodeCandidate]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            result = subprocess.run(  # nosec B603 B607
                [
                    "git",
                    "log",
                    "--since",
                    since,
                    "--pretty=format:%H%x1f%ct%x1f%an%x1f%s%x1f%b%x1e",
                    "--name-only",
                ],
                cwd=_REPO_ROOT,
                capture_output=True,
                check=True,
                text=True,
            )
        except Exception as exc:
            logger.warning("Failed to scan git history: %s", exc)
            return []

        raw_records = [record for record in result.stdout.split("\x1e") if record.strip()]
        commits: list[dict[str, Any]] = []
        for record in raw_records:
            lines = [line for line in record.splitlines() if line.strip()]
            if not lines:
                continue
            header = lines[0].split("\x1f")
            if len(header) < 5:
                continue
            files = [line.strip() for line in lines[1:] if line.strip()]
            relevant_files = [path for path in files if path.startswith(_PATH_ALLOWLIST)]
            if not relevant_files:
                continue
            committed_at = datetime.fromtimestamp(int(header[1]), tz=timezone.utc)
            commits.append(
                {
                    "sha": header[0],
                    "committed_at": committed_at,
                    "author_name": header[2],
                    "title": header[3],
                    "body": header[4].strip() or None,
                    "files": relevant_files,
                }
            )

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for commit in reversed(commits):
            change_type = self._classify_change_type(commit["files"])
            grouped[change_type].append(commit)

        candidates: list[EpisodeCandidate] = []
        for change_type, items in grouped.items():
            chunk: list[dict[str, Any]] = []
            previous_ts: datetime | None = None
            for item in items:
                if previous_ts and (item["committed_at"] - previous_ts) > timedelta(days=2):
                    if chunk:
                        candidates.append(EpisodeCandidate(commits=chunk, change_type=change_type))
                    chunk = []
                chunk.append(item)
                previous_ts = item["committed_at"]
            if chunk:
                candidates.append(EpisodeCandidate(commits=chunk, change_type=change_type))
        return sorted(candidates, key=lambda candidate: candidate.commits[0]["committed_at"], reverse=True)

    @staticmethod
    def _classify_change_type(files: list[str]) -> str:
        joined = " ".join(files)
        if "strategy" in joined or "prompts" in joined:
            return "strategy"
        if "risk" in joined:
            return "risk"
        if "execution" in joined or "order" in joined:
            return "execution"
        if "guidance" in joined or "data_fetcher" in joined:
            return "screening"
        if "opportunity" in joined:
            return "opportunity"
        return "system"

    @staticmethod
    def _build_title(candidate: EpisodeCandidate) -> str:
        first = candidate.commits[0]
        if len(candidate.commits) == 1:
            return f"{candidate.change_type.title()} update: {first['title'][:120]}"
        return f"{candidate.change_type.title()} episode ({len(candidate.commits)} commits)"

    @staticmethod
    def _build_summary(candidate: EpisodeCandidate) -> str:
        titles = [commit["title"] for commit in candidate.commits[:3]]
        files = sorted({path for commit in candidate.commits for path in commit["files"]})
        return (
            "Grouped strategy-affecting changes from git history. "
            f"Representative commits: {' | '.join(titles)}. "
            f"Affected files: {', '.join(files[:6])}."
        )

    @staticmethod
    def _serialize_episode_summary(episode: StrategyChangeEpisode) -> dict[str, Any]:
        return {
            "id": int(episode.id),
            "status": episode.status,
            "title": episode.title,
            "summary": episode.summary,
            "change_type": episode.change_type,
            "review_confidence": float(episode.review_confidence or 0.0),
            "commit_start_sha": episode.commit_start_sha,
            "commit_end_sha": episode.commit_end_sha,
            "effective_start_at": episode.effective_start_at,
            "effective_end_at": episode.effective_end_at,
            "confirmed_at": episode.confirmed_at,
            "rejected_at": episode.rejected_at,
            "notes": episode.notes,
        }
