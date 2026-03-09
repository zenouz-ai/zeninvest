#!/bin/bash
# Quick verification script after running a cycle

CYCLE_ID="${1:-cycle_20260309_1702_9de32b}"

echo "=== Verifying Dashboard Data for Cycle: $CYCLE_ID ==="
echo ""

# Check if dashboard server is running
echo "1. Checking if dashboard server is running..."
if curl -s --max-time 2 http://localhost:8000/api/runs/ > /dev/null 2>&1; then
    echo "   ✅ Dashboard server is running"
else
    echo "   ❌ Dashboard server is NOT running"
    echo "   → Start it with: poetry run python dashboard/backend/run_server.py"
    echo ""
    echo "   Checking database directly instead..."
    poetry run python3 << 'PYTHON'
from src.data.database import get_session
from dashboard.backend.app.database import EventsLog, Run
from datetime import datetime, timedelta, timezone

session = get_session()

# Check events
events = session.query(EventsLog).filter(
    EventsLog.timestamp >= datetime.now(timezone.utc) - timedelta(minutes=10)
).order_by(EventsLog.timestamp.desc()).all()

print(f"\n   Found {len(events)} events in last 10 minutes:")
for e in events[:10]:
    print(f"     {e.timestamp.strftime('%H:%M:%S')} | {e.event_type:20s} | {e.source:15s} | {e.message[:50]}")

# Check runs
runs = session.query(Run).order_by(Run.started_at.desc()).limit(5).all()
print(f"\n   Found {len(runs)} runs:")
for r in runs:
    print(f"     {r.cycle_id} | {r.status:10s} | {r.started_at.strftime('%Y-%m-%d %H:%M:%S')}")

session.close()
PYTHON
    exit 0
fi

echo ""
echo "2. Checking events via API..."
EVENT_COUNT=$(curl -s "http://localhost:8000/api/events/?limit=20" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data))" 2>/dev/null || echo "0")
echo "   Found $EVENT_COUNT recent events"

if [ "$EVENT_COUNT" -gt 0 ]; then
    echo ""
    echo "   Latest events:"
    curl -s "http://localhost:8000/api/events/?limit=5" | python3 -m json.tool 2>/dev/null | grep -E "(event_type|source|message|timestamp)" | head -20
fi

echo ""
echo "3. Checking runs via API..."
RUN_COUNT=$(curl -s "http://localhost:8000/api/runs/" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data))" 2>/dev/null || echo "0")
echo "   Found $RUN_COUNT runs"

if [ "$RUN_COUNT" -gt 0 ]; then
    echo ""
    echo "   Latest runs:"
    curl -s "http://localhost:8000/api/runs/?limit=3" | python3 -m json.tool 2>/dev/null | head -40
fi

echo ""
echo "4. Checking for cycle-specific events..."
curl -s "http://localhost:8000/api/events/?event_type=run_started" | python3 -c "import sys, json; data=json.load(sys.stdin); matches=[e for e in data if '$CYCLE_ID' in str(e.get('metadata', {}))]; print(f'   Found {len(matches)} run_started events for this cycle')" 2>/dev/null || echo "   (Could not check)"

echo ""
echo "=== Summary ==="
echo "Events: $EVENT_COUNT"
echo "Runs: $RUN_COUNT"
echo ""
echo "If events=0, check:"
echo "  1. Dashboard server is running"
echo "  2. config/settings.yaml has dashboard.enabled: true"
echo "  3. Check log file: logs/investment_agent.log for debug messages"
