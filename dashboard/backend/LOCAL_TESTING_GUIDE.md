# Local Testing Guide - Phase 2 Verification

This guide walks you through testing the dashboard instrumentation on your local machine.

## Prerequisites

1. ✅ Dashboard backend is installed (`poetry install` completed)
2. ✅ Database migrations are up to date (`poetry run alembic upgrade head`)
3. ✅ `.env` file exists with API keys (for dry-run testing)

## Step 1: Start the Dashboard Server

Open a **new terminal window** (keep it running):

```bash
cd /path/to/Investment-agent
poetry run python dashboard/backend/run_server.py
```

You should see:
```
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Keep this terminal open** - the server needs to stay running.

## Step 2: Verify Server is Running

In a **new terminal window**, test the API:

```bash
curl http://localhost:8000/api/runs/ | python3 -m json.tool
curl http://localhost:8000/api/events/ | python3 -m json.tool
```

You should see empty arrays `[]` if no cycles have run yet, or existing data if you've run cycles before.

## Step 3: Run a Dry-Run Cycle

In the **same terminal** (or a new one), run a dry-run cycle:

```bash
cd /path/to/Investment-agent
poetry run python -m src.orchestrator.main --dry-run
```

**Watch for:**
- Debug messages like `Created Run record for cycle ...` or `Failed to create Run record`
- Any errors related to dashboard logging (should be minimal due to fail-open design)
- Cycle completion message

## Step 4: Check Events Were Logged

After the cycle completes, check the events API:

```bash
curl http://localhost:8000/api/events/ | python3 -m json.tool | head -100
```

You should see events like:
- `run_started` (source: orchestrator)
- `run_completed` (source: orchestrator)
- `decision_made` (source: strategy/moderation/risk)
- `universe_updated` (source: screener) - if universe screening ran
- `order_placed` / `order_executed` (source: execution) - if any orders were placed

## Step 5: Check Run Records

Check if Run records were created:

```bash
curl http://localhost:8000/api/runs/ | python3 -m json.tool
```

You should see at least one run record with:
- `cycle_id`: e.g., `cycle_20260309_1645_xxxxxx`
- `run_type`: `dry_run`
- `status`: `completed` or `failed`
- `started_at` and `completed_at` timestamps

## Step 6: Verify Database Directly (Optional)

If you want to check the database directly:

```bash
poetry run python3 -c "
from src.data.database import get_session
from dashboard.backend.app.database import EventsLog, Run
from datetime import datetime, timedelta, timezone

session = get_session()

# Check recent events
events = session.query(EventsLog).filter(
    EventsLog.timestamp >= datetime.now(timezone.utc) - timedelta(hours=1)
).order_by(EventsLog.timestamp.desc()).limit(10).all()

print(f'Recent events ({len(events)}):')
for e in events:
    print(f'  {e.timestamp} | {e.event_type:20s} | {e.source:15s} | {e.message[:60]}')

# Check recent runs
runs = session.query(Run).order_by(Run.started_at.desc()).limit(5).all()
print(f'\nRecent runs ({len(runs)}):')
for r in runs:
    print(f'  {r.cycle_id} | {r.status:10s} | {r.started_at}')

session.close()
"
```

## Troubleshooting

### Dashboard server won't start

**Error:** `ModuleNotFoundError: No module named 'dashboard'`

**Fix:**
```bash
# Ensure you're in the project root
cd /path/to/Investment-agent

# Verify dashboard package is installed
poetry run python -c "import dashboard; print('OK')"

# If that fails, reinstall dependencies
poetry install
```

### No events appearing after cycle

**Check:**
1. Is the dashboard server running? (`curl http://localhost:8000/api/events/` should not hang)
2. Check cycle logs for `Created Run record` or `Failed to create Run record` messages
3. Verify `dashboard.enabled` and `dashboard.events_enabled` are `true` in `config/settings.yaml`

**Debug:**
```bash
# Check if events are in the database
poetry run python3 -c "
from src.data.database import get_session
from dashboard.backend.app.database import EventsLog
session = get_session()
count = session.query(EventsLog).count()
print(f'Total events in database: {count}')
session.close()
"
```

### Run records not being created

**Check debug logs:**
- Look for `Failed to create Run record (fail-open): ...` messages in cycle output
- The debug logging we added will show the exception if Run creation fails

**Note:** Run records are optional metadata. Events contain all the information needed, so missing Run records don't break functionality.

## Expected Results

After completing all steps, you should have:

✅ Dashboard server running on `http://localhost:8000`  
✅ At least one `run_started` event in `/api/events/`  
✅ At least one `run_completed` event in `/api/events/`  
✅ At least one Run record in `/api/runs/` (if Run creation succeeded)  
✅ Additional events (`decision_made`, `universe_updated`, etc.) depending on cycle activity  

## Next Steps

Once verification is complete:
1. Commit the debug logging improvements
2. Consider running a live cycle (without `--dry-run`) to test with real data
3. Move on to Phase 3: Frontend development
