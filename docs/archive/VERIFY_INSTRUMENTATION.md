> **Archived 2026-03-29:** Content merged into dashboard/backend/LOCAL_TESTING_GUIDE.md "Quick Verification Checklist" section.

# Verify Dashboard Instrumentation

## Quick Check After Running a Cycle

### 1. Check Database Directly (Most Reliable)

```bash
poetry run python -c "
from src.data.database import get_session
from dashboard.backend.app.database import EventsLog, Run

s = get_session()
try:
    runs = s.query(Run).order_by(Run.started_at.desc()).limit(3).all()
    print(f'Runs: {len(runs)}')
    for r in runs:
        print(f'  {r.cycle_id}: {r.status}')
    
    events = s.query(EventsLog).order_by(EventsLog.timestamp.desc()).limit(10).all()
    print(f'\nEvents: {len(events)}')
    for e in events:
        print(f'  {e.event_type} from {e.source}')
finally:
    s.close()
"
```

### 2. Check via API (Requires Dashboard Server Running)

**First, start the dashboard server:**
```bash
# Terminal 1
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
poetry run python dashboard/backend/run_server.py
```

**Then check events:**
```bash
# Terminal 2
curl http://localhost:8000/api/events/ | python -m json.tool
curl http://localhost:8000/api/runs/ | python -m json.tool
```

### 3. Expected Events Per Cycle

When running `poetry run python -m src.orchestrator.main`, you should see:

| Event Type | Source | Count | When |
|------------|--------|-------|------|
| `run_started` | orchestrator | 1 | Cycle begins |
| `universe_updated` | screener | 1 | After screening |
| `decision_made` | strategy | ~4-15 | Each strategy decision |
| `decision_made` | moderation | ~3-5 | Each moderation result |
| `decision_made` | risk | ~3-5 | Each risk check |
| `run_completed` | orchestrator | 1 | Cycle finishes |

**Total: ~12-25 events per cycle**

### 4. Troubleshooting

**If no events appear:**

1. **Check dashboard is enabled:**
   ```bash
   poetry run python -c "from src.utils.config import get_settings; s=get_settings(); print('Enabled:', s.dashboard_enabled, 'Events:', s.dashboard_events_enabled)"
   ```

2. **Check event logger thread:**
   ```bash
   poetry run python -c "
   from dashboard.backend.app.services.event_logger import _logger_thread, _event_queue
   print(f'Thread: {_logger_thread.is_alive() if _logger_thread else \"Not started\"}')
   print(f'Queue: {_event_queue.qsize()} events')
   "
   ```

3. **Wait a few seconds** - events are processed asynchronously

4. **Check database directly** (most reliable):
   ```bash
   poetry run python -c "
   from src.data.database import get_session
   from dashboard.backend.app.database import EventsLog
   s = get_session()
   print(f'Total events: {s.query(EventsLog).count()}')
   s.close()
   "
   ```

**If curl hangs:**

- Dashboard server is not running
- Start it in a separate terminal first
- Or check database directly (doesn't require server)

### 5. Verify Latest Cycle

```bash
# Get latest cycle ID from your cycle output
CYCLE_ID="cycle_20260309_1645_605d89"

# Check events for that cycle
poetry run python -c "
from src.data.database import get_session
from dashboard.backend.app.database import EventsLog
import json

s = get_session()
try:
    events = s.query(EventsLog).all()
    cycle_events = [e for e in events if e.metadata_json and e.metadata_json.get('cycle_id') == '$CYCLE_ID']
    print(f'Events for {CYCLE_ID}: {len(cycle_events)}')
    for e in cycle_events:
        print(f'  {e.event_type} from {e.source}')
finally:
    s.close()
"
```
