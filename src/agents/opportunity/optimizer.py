"""Execution optimizer for UOV-ranked buy decisions and queue management."""

import json
from datetime import datetime, timezone
from typing import Any

from src.data.database import get_session
from src.data.models import OpportunityQueue
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("opportunity_optimizer")


class OpportunityOptimizer:
    """Rank and stage BUY opportunities under slot/cash constraints."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def optimize_buys(
        self,
        cycle_id: str,
        approved_buys: list[dict[str, Any]],
        scores_by_ticker: dict[str, dict[str, Any]],
        existing_tickers: set[str],
        cash_pct: float,
        num_positions: int,
    ) -> dict[str, Any]:
        """Select immediate buys, manage queue, and produce swap suggestions."""
        ranked = sorted(
            approved_buys,
            key=lambda c: scores_by_ticker.get(c.get("ticker", ""), {}).get("uov_ewma", 0.0),
            reverse=True,
        )
        max_positions = self.settings.max_positions
        cash_floor = self.settings.cash_floor_pct
        immediate_threshold = self.settings.opportunity_immediate_threshold_z
        queue_threshold = self.settings.opportunity_queue_threshold_z
        queue_ttl = self.settings.opportunity_queue_ttl_cycles

        remaining_slots = max(0, max_positions - num_positions)
        remaining_cash = max(0.0, cash_pct - cash_floor)

        immediate_exec: list[str] = []
        queue_candidates: list[dict[str, Any]] = []

        for candidate in ranked:
            ticker = candidate.get("ticker", "")
            if not ticker:
                continue
            score = float(scores_by_ticker.get(ticker, {}).get("uov_ewma", 0.0))
            alloc = float(candidate.get("final_allocation_pct", 0.0))
            is_new_position = ticker not in existing_tickers

            has_slot = (not is_new_position) or remaining_slots > 0
            has_cash = alloc <= remaining_cash + 1e-9
            can_execute = has_slot and has_cash

            if score >= immediate_threshold and can_execute:
                immediate_exec.append(ticker)
                remaining_cash -= alloc
                if is_new_position:
                    remaining_slots -= 1
                continue

            if score >= queue_threshold:
                queue_candidates.append(
                    {
                        "ticker": ticker,
                        "uov_ewma": score,
                        "uov_final": float(scores_by_ticker.get(ticker, {}).get("uov_final", 0.0)),
                        "uov_z": float(scores_by_ticker.get(ticker, {}).get("uov_z", 0.0)),
                        "final_allocation_pct": alloc,
                        "blocked_by_capacity": not can_execute,
                    },
                )

        queue_state = self._update_queue(
            cycle_id=cycle_id,
            queue_candidates=queue_candidates,
            scores_by_ticker=scores_by_ticker,
            queue_ttl=queue_ttl,
        )

        promoted_exec: list[str] = []
        remaining_queue: list[dict[str, Any]] = []

        for queued in sorted(queue_state["active"], key=lambda x: x["uov_ewma"], reverse=True):
            ticker = queued["ticker"]
            if ticker in immediate_exec:
                continue
            alloc = float(queued.get("final_allocation_pct", 0.0))
            is_new_position = ticker not in existing_tickers
            has_slot = (not is_new_position) or remaining_slots > 0
            has_cash = alloc <= remaining_cash + 1e-9
            if queued.get("queued_cycles", 1) >= 2 and has_slot and has_cash:
                promoted_exec.append(ticker)
                remaining_cash -= alloc
                if is_new_position:
                    remaining_slots -= 1
            else:
                remaining_queue.append(queued)

        executed = immediate_exec + promoted_exec
        if executed:
            self._dequeue_executed(executed)

        swap_candidates = self._build_swap_suggestions(
            approved_buys=ranked,
            scores_by_ticker=scores_by_ticker,
            existing_tickers=existing_tickers,
        )

        return {
            "execution_order": executed,
            "queued_candidates": remaining_queue,
            "dropped_queue": queue_state["dropped"],
            "swap_candidates": swap_candidates,
        }

    def _update_queue(
        self,
        cycle_id: str,
        queue_candidates: list[dict[str, Any]],
        scores_by_ticker: dict[str, dict[str, Any]],
        queue_ttl: int,
    ) -> dict[str, Any]:
        active_now = {c["ticker"]: c for c in queue_candidates}
        session = get_session()
        dropped: list[dict[str, Any]] = []
        active_output: list[dict[str, Any]] = []
        try:
            existing_rows = session.query(OpportunityQueue).all()
            rows_by_ticker = {r.ticker: r for r in existing_rows}

            # Drop stale queue rows not selected this cycle.
            for row in existing_rows:
                if row.ticker not in active_now:
                    dropped.append(
                        {
                            "ticker": row.ticker,
                            "reason": "no_longer_eligible",
                            "last_uov_ewma": float(row.last_uov_ewma),
                        },
                    )
                    session.delete(row)

            # Upsert active queue rows.
            for ticker, candidate in active_now.items():
                row = rows_by_ticker.get(ticker)
                if row is None:
                    row = OpportunityQueue(
                        ticker=ticker,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                        last_seen_cycle_id=cycle_id,
                        queued_cycles=1,
                        last_uov_z=float(candidate.get("uov_z", 0.0)),
                        last_uov_final=float(candidate.get("uov_final", 0.0)),
                        last_uov_ewma=float(candidate.get("uov_ewma", 0.0)),
                        action="BUY",
                        reason="queued_by_uov",
                        metadata_json=json.dumps(
                            {
                                "final_allocation_pct": candidate.get("final_allocation_pct"),
                                "blocked_by_capacity": candidate.get("blocked_by_capacity", False),
                            },
                        ),
                    )
                    session.add(row)
                else:
                    row.updated_at = datetime.now(timezone.utc)
                    row.last_seen_cycle_id = cycle_id
                    row.queued_cycles = int(row.queued_cycles) + 1
                    row.last_uov_z = float(candidate.get("uov_z", 0.0))
                    row.last_uov_final = float(candidate.get("uov_final", 0.0))
                    row.last_uov_ewma = float(candidate.get("uov_ewma", 0.0))
                    row.reason = "queued_by_uov"
                    row.metadata_json = json.dumps(
                        {
                            "final_allocation_pct": candidate.get("final_allocation_pct"),
                            "blocked_by_capacity": candidate.get("blocked_by_capacity", False),
                        },
                    )

            session.flush()

            # Expire rows above TTL.
            for row in session.query(OpportunityQueue).all():
                if int(row.queued_cycles) > queue_ttl:
                    dropped.append(
                        {
                            "ticker": row.ticker,
                            "reason": "queue_ttl_expired",
                            "last_uov_ewma": float(row.last_uov_ewma),
                        },
                    )
                    session.delete(row)
                    continue

                metadata = self._load_metadata(row.metadata_json)
                active_output.append(
                    {
                        "ticker": row.ticker,
                        "queued_cycles": int(row.queued_cycles),
                        "uov_ewma": float(row.last_uov_ewma),
                        "uov_final": float(row.last_uov_final),
                        "uov_z": float(row.last_uov_z),
                        "final_allocation_pct": float(metadata.get("final_allocation_pct", 0.0)),
                        "blocked_by_capacity": bool(metadata.get("blocked_by_capacity", False)),
                    },
                )

            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error(f"Failed to update opportunity queue: {exc}")
        finally:
            session.close()

        # Patch in the latest score from this cycle where available.
        for item in active_output:
            ticker = item["ticker"]
            score = scores_by_ticker.get(ticker, {})
            item["uov_ewma"] = float(score.get("uov_ewma", item["uov_ewma"]))
            item["uov_final"] = float(score.get("uov_final", item["uov_final"]))
            item["uov_z"] = float(score.get("uov_z", item["uov_z"]))
        return {"active": active_output, "dropped": dropped}

    @staticmethod
    def _load_metadata(metadata_json: str | None) -> dict[str, Any]:
        if not metadata_json:
            return {}
        try:
            return json.loads(metadata_json)
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _dequeue_executed(tickers: list[str]) -> None:
        if not tickers:
            return
        session = get_session()
        try:
            session.query(OpportunityQueue).filter(OpportunityQueue.ticker.in_(tickers)).delete(  # noqa: E712
                synchronize_session="fetch",
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def _build_swap_suggestions(
        self,
        approved_buys: list[dict[str, Any]],
        scores_by_ticker: dict[str, dict[str, Any]],
        existing_tickers: set[str],
    ) -> list[dict[str, Any]]:
        if not approved_buys or not existing_tickers:
            return []

        held_scores: list[tuple[str, float]] = []
        for ticker in existing_tickers:
            if ticker in scores_by_ticker:
                held_scores.append((ticker, float(scores_by_ticker[ticker].get("uov_ewma", 0.0))))

        if not held_scores:
            return []

        weakest_ticker, weakest_score = min(held_scores, key=lambda x: x[1])
        min_delta = self.settings.opportunity_swap_delta_z

        suggestions: list[dict[str, Any]] = []
        for candidate in approved_buys:
            ticker = candidate.get("ticker", "")
            if not ticker or ticker in existing_tickers:
                continue
            cand_score = float(scores_by_ticker.get(ticker, {}).get("uov_ewma", 0.0))
            delta = cand_score - weakest_score
            if delta >= min_delta:
                suggestions.append(
                    {
                        "candidate_ticker": ticker,
                        "candidate_uov_ewma": round(cand_score, 4),
                        "weakest_held_ticker": weakest_ticker,
                        "weakest_held_uov_ewma": round(weakest_score, 4),
                        "delta": round(delta, 4),
                    },
                )

        suggestions.sort(key=lambda s: s["delta"], reverse=True)
        return suggestions
