"""Backfill historical data from existing tables into dashboard events/runs.

This script reads from strategy_decisions, orders, portfolio_snapshots, etc.
and creates corresponding events_log and runs entries.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.data.database import get_session
from src.data.models import (
    StrategyDecision,
    ModerationLog,
    RiskDecision,
    Order,
    PortfolioSnapshot,
)
from dashboard.backend.app.database import EventsLog, Run

def backfill_runs():
    """Create run records from strategy_decisions cycle_id groups."""
    session = get_session()
    try:
        # Get distinct cycle_ids from strategy_decisions
        cycle_ids = (
            session.query(StrategyDecision.cycle_id)
            .distinct()
            .order_by(StrategyDecision.cycle_id)
            .all()
        )
        
        runs_created = 0
        for (cycle_id,) in cycle_ids:
            # Check if run already exists
            existing = session.query(Run).filter(Run.cycle_id == cycle_id).first()
            if existing:
                continue
            
            # Get first and last timestamps for this cycle
            first_decision = (
                session.query(StrategyDecision)
                .filter(StrategyDecision.cycle_id == cycle_id)
                .order_by(StrategyDecision.timestamp)
                .first()
            )
            
            last_decision = (
                session.query(StrategyDecision)
                .filter(StrategyDecision.cycle_id == cycle_id)
                .order_by(StrategyDecision.timestamp.desc())
                .first()
            )
            
            if not first_decision:
                continue
            
            # Count decisions and orders
            num_decisions = (
                session.query(StrategyDecision)
                .filter(StrategyDecision.cycle_id == cycle_id)
                .count()
            )
            
            num_orders = (
                session.query(Order)
                .filter(Order.cycle_id == cycle_id)
                .count()
            )
            
            # Determine status
            status = "completed"
            if num_orders == 0 and num_decisions > 0:
                status = "completed"  # No trades but cycle completed
            
            run = Run(
                cycle_id=cycle_id,
                run_type="scheduled",  # Assume scheduled for historical data
                started_at=first_decision.timestamp,
                completed_at=last_decision.timestamp if last_decision else first_decision.timestamp,
                status=status,
                summary_json={
                    "num_decisions": num_decisions,
                    "num_orders": num_orders,
                },
            )
            session.add(run)
            runs_created += 1
        
        session.commit()
        print(f"✅ Created {runs_created} run records")
        return runs_created
    except Exception as e:
        session.rollback()
        print(f"❌ Error backfilling runs: {e}")
        raise
    finally:
        session.close()


def backfill_events():
    """Create event records from historical data."""
    session = get_session()
    try:
        events_created = 0
        
        # Backfill from strategy_decisions
        decisions = (
            session.query(StrategyDecision)
            .order_by(StrategyDecision.timestamp)
            .all()
        )
        
        for decision in decisions:
            # Check if event already exists
            existing = (
                session.query(EventsLog)
                .filter(
                    EventsLog.event_type == "decision_made",
                    EventsLog.source == "strategy",
                    EventsLog.metadata_json["cycle_id"].astext == decision.cycle_id,
                    EventsLog.metadata_json["ticker"].astext == decision.ticker,
                )
                .first()
            )
            if existing:
                continue
            
            event = EventsLog(
                timestamp=decision.timestamp,
                event_type="decision_made",
                source="strategy",
                message=f"{decision.action} {decision.ticker} - {decision.reasoning[:100] if decision.reasoning else ''}",
                metadata_json={
                    "cycle_id": decision.cycle_id,
                    "ticker": decision.ticker,
                    "action": decision.action,
                    "conviction": decision.conviction,
                    "reasoning": decision.reasoning[:500] if decision.reasoning else None,
                },
            )
            session.add(event)
            events_created += 1
        
        # Backfill from orders
        orders = (
            session.query(Order)
            .filter(Order.status.in_(["filled", "dry_run"]))
            .order_by(Order.timestamp)
            .all()
        )
        
        for order in orders:
            # Check if event already exists
            existing = (
                session.query(EventsLog)
                .filter(
                    EventsLog.event_type == "order_executed",
                    EventsLog.source == "execution",
                    EventsLog.metadata_json["order_id"].astext == str(order.id),
                )
                .first()
            )
            if existing:
                continue
            
            event = EventsLog(
                timestamp=order.timestamp,
                event_type="order_executed",
                source="execution",
                message=f"Order executed: {order.action} {abs(order.quantity)} x {order.ticker} @ {order.price}",
                metadata_json={
                    "order_id": order.id,
                    "t212_order_id": order.t212_order_id,
                    "ticker": order.ticker,
                    "action": order.action,
                    "quantity": abs(order.quantity),
                    "price": order.price,
                    "value_gbp": order.value_gbp,
                    "status": order.status,
                    "strategy": order.strategy,
                    "conviction": order.conviction,
                },
            )
            session.add(event)
            events_created += 1
        
        session.commit()
        print(f"✅ Created {events_created} event records")
        return events_created
    except Exception as e:
        session.rollback()
        print(f"❌ Error backfilling events: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print("Backfilling historical data into dashboard tables...")
    print("=" * 60)
    
    runs_count = backfill_runs()
    events_count = backfill_events()
    
    print("=" * 60)
    print(f"✅ Backfill complete:")
    print(f"   - {runs_count} runs created")
    print(f"   - {events_count} events created")
    print("\nTest the endpoints:")
    print("  curl http://localhost:8000/api/runs/ | python -m json.tool")
    print("  curl http://localhost:8000/api/events/ | python -m json.tool")
