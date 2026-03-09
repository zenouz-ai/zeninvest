"""Add test data to verify dashboard endpoints work."""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.data.database import get_session
from dashboard.backend.app.database import EventsLog, Run
from dashboard.backend.app.services.event_logger import log_event

def add_test_data():
    """Add sample events and runs for testing."""
    session = get_session()
    
    try:
        # Add a test run
        test_run = Run(
            cycle_id="test-2026-03-09T08:00:00Z",
            run_type="manual",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            status="completed",
            summary_json={
                "stocks_reviewed": 5,
                "decisions_made": 3,
                "orders_placed": 1
            }
        )
        session.add(test_run)
        
        # Add some test events
        events = [
            EventsLog(
                timestamp=datetime.now(timezone.utc),
                event_type="run_started",
                source="scheduler",
                message="Test cycle started",
                metadata_json={"cycle_id": "test-2026-03-09T08:00:00Z"}
            ),
            EventsLog(
                timestamp=datetime.now(timezone.utc),
                event_type="decision_made",
                source="strategy",
                message="BUY AAPL_US_EQ with conviction 80",
                metadata_json={"ticker": "AAPL_US_EQ", "action": "BUY", "conviction": 80}
            ),
            EventsLog(
                timestamp=datetime.now(timezone.utc),
                event_type="order_placed",
                source="execution",
                message="Placed BUY order for AAPL_US_EQ",
                metadata_json={"ticker": "AAPL_US_EQ", "quantity": 10, "order_id": "test-123"}
            ),
            EventsLog(
                timestamp=datetime.now(timezone.utc),
                event_type="run_completed",
                source="scheduler",
                message="Test cycle completed successfully",
                metadata_json={"cycle_id": "test-2026-03-09T08:00:00Z", "duration_seconds": 45}
            ),
        ]
        
        for event in events:
            session.add(event)
        
        session.commit()
        print("✅ Added test data:")
        print(f"   - 1 test run")
        print(f"   - {len(events)} test events")
        print("\nNow test the endpoints:")
        print("  curl http://localhost:8000/api/runs/")
        print("  curl http://localhost:8000/api/events/")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error adding test data: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    add_test_data()
