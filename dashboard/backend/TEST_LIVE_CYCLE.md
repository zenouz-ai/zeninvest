# Testing Live Cycle with Dashboard

## Prerequisites

1. **Dashboard server running** (in one terminal):
   ```bash
   export PYTHONPATH="${PYTHONPATH}:$(pwd)"
   poetry run python dashboard/backend/run_server.py
   ```

2. **Database migrated**:
   ```bash
   poetry run alembic upgrade head
   ```

3. **Environment configured**:
   - `.env` file with Trading 212 Practice API keys
   - `config/settings.yaml` with `dashboard.enabled: true` and `dashboard.events_enabled: true`

## Running a Live Cycle

### Option 1: Single Live Cycle

```bash
# Run a live cycle (will place real orders on Practice account)
poetry run python -m src.orchestrator.main
```

### Option 2: Monitor Events in Real-Time

**Terminal 1 - Dashboard Server:**
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
poetry run python dashboard/backend/run_server.py
```

**Terminal 2 - SSE Stream (watch events live):**
```bash
curl -N http://localhost:8000/api/events/stream
```

**Terminal 3 - Run Cycle:**
```bash
poetry run python -m src.orchestrator.main
```

You'll see events appear in Terminal 2 as they happen!

### Option 3: Check Events After Cycle

```bash
# Run cycle
poetry run python -m src.orchestrator.main

# Then check events
curl http://localhost:8000/api/events/ | python -m json.tool | head -100

# Check runs
curl http://localhost:8000/api/runs/ | python -m json.tool

# Check latest run details
curl http://localhost:8000/api/runs/cycle/{cycle_id} | python -m json.tool
```

## What to Expect

### Events You'll See:

1. **run_started** - When cycle begins
2. **universe_updated** - After screening candidates
3. **decision_made** (strategy) - For each stock evaluated
4. **decision_made** (moderation) - Moderation panel results
5. **decision_made** (risk) - Risk manager verdicts
6. **order_placed** - Before order execution
7. **order_executed** - After successful execution
8. **notification_sent** - When Slack/Email alerts sent
9. **run_completed** - When cycle finishes

### Timeline:

- **0-30s**: Data fetching, universe screening
- **30-60s**: Strategy synthesis (Claude)
- **60-90s**: Moderation panel (GPT-4o + Gemini)
- **90-120s**: Risk checks, order execution
- **120s+**: Journal, notifications, completion

## Safety Notes

✅ **Safe**: Trading 212 Practice account uses virtual money  
✅ **No risk**: No real funds involved  
✅ **Reversible**: You can manually close positions in T212 app  
⚠️ **Note**: Orders will be placed on Practice account (visible in T212 app)

## Troubleshooting

### No events appearing?

1. Check dashboard is enabled:
   ```bash
   poetry run python -c "from src.utils.config import get_settings; s=get_settings(); print(s.dashboard_enabled, s.dashboard_events_enabled)"
   ```

2. Check dashboard server logs for errors

3. Verify database has dashboard tables:
   ```bash
   poetry run python -c "from src.data.database import get_session; from dashboard.backend.app.database import EventsLog; s=get_session(); print('Events count:', s.query(EventsLog).count()); s.close()"
   ```

### Events appear but incomplete?

- Some events may be skipped if dashboard module unavailable (fail-open)
- Check agent logs for any import errors
- Verify `dashboard` package is in Python path

## Next Steps After Testing

1. **View in browser**: Open http://localhost:8000/docs to see all events
2. **Backfill**: Run backfill script to migrate historical data
3. **Phase 3**: Build frontend to visualize these events beautifully
