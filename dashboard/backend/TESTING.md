# Testing the Dashboard Backend

## Full dashboard check (13 pages + full API)

Use this to confirm the full API and frontend are in place.

### 1. Config and DB

```bash
# From repo root
poetry install
poetry run alembic upgrade head

# Dashboard must be enabled (otherwise all /api/* return 503)
poetry run python -c "from src.utils.config import get_settings; s=get_settings(); print('dashboard.enabled:', s.dashboard_enabled)"
```

If `dashboard.enabled` is False, set `dashboard.enabled: true` (and optionally `dashboard.events_enabled: true`) in `config/settings.yaml`.

### 2. Start the backend

```bash
poetry run uvicorn dashboard.backend.app.main:app --host 127.0.0.1 --port 8000
```

Leave it running. In another terminal:

### 3. Hit all API endpoints

```bash
poetry run python dashboard/backend/test_endpoints.py
```

This checks: health, status (with state/paused), runs, universe, portfolio, orders, events, **decisions** (list + waterfall), **moderation**, **risk**, **opportunity** (config, scores, queue), **outcomes** (list, stats), **stop-loss** (current, adjustments), **research** (logs, summary), **performance** (metrics, history), **costs** (daily, monthly, degradation), **api-usage/daily**, **system/state**. Expect 200 or 404/503; connection errors mean the server is not running.

### 4. Open API docs (optional)

Open **http://localhost:8000/docs** and try any endpoint by hand.

### 5. Frontend: build and serve

```bash
cd dashboard/frontend
npm install
npm run build
```

Then either:

- **Option A — SPA via FastAPI:** From repo root, ensure backend is serving; open **http://localhost:8000**. FastAPI serves the built frontend from `dashboard/frontend/dist` when that folder exists.
- **Option B — Dev server (proxies to backend):** From `dashboard/frontend`, run `npm run dev` and open **http://localhost:3000**.

### 6. Verify all 13 pages

In the browser, confirm each route loads without errors:

| Page            | URL                    | What to check                                      |
|-----------------|------------------------|----------------------------------------------------|
| Overview        | `/`                    | Signed-out: public overview surface with full nav and safe summary cards; signed-in: operator dashboard home |
| Universe        | `/universe`            | Signed-out: first 10 sanitized instruments; signed-in: sortable table with pipeline waterfall, deep-link `/universe/AAPL`, URL params `?q=AAPL&sector=Technology` |
| Portfolio       | `/portfolio`           | Signed-out: normalized history + capped holdings, no actions; signed-in: positions with sparklines + Force Sell button, P&L with ▲/▼ arrows, profit-lock state, mobile card layout |
| Runs            | `/runs`                | Signed-out: last 5 sanitized runs; signed-in: timeline, run diff, dataset audits |
| World News      | `/world-news`          | Macro regime, timeline, headline archive; public mode omits operator-only portfolio bias |
| Roadmap         | `/roadmap`             | Project timeline, topic filter, Architecture tab |
| Opportunity     | `/opportunity`         | Signed-out: capped preview examples; signed-in: full UOV queue and scores table |
| Insights        | `/insights`            | Signed-out: sanitized market-guidance history; signed-in: full guidance + attribution review |
| Order Management| `/orders`              | Signed-out: preview-only explainer; signed-in: stops, health, execution quality, adjustments |
| Costs           | `/costs`               | Signed-out: aggregate totals only; signed-in: degradation badge, daily chart, monthly table |
| Chat            | `/chat`                | Signed-out: preview-only demo transcript; signed-in: full operator console |
| Evolution       | `/evolution`           | Signed-out: preview-only planner concept; signed-in: authenticated evolution planner |
| Learning        | `/learning`            | Operator-only: shadow learning runs list (`/api/learning/runs`), run detail + report URL, embedded insight PNGs when artifacts exist under `data/learning/` |

### 7. SSE activity feed

On Dashboard Home, the activity feed should show “Connected” and may show events. To test events, run a dry-run in another terminal: `poetry run python -m src.orchestrator.main --dry-run`.

---

## Quick Test Guide

### 1. Verify Installation

First, make sure dependencies are installed:

```bash
poetry install
```

### 2. Run Database Migration

Ensure the dashboard tables are created:

```bash
poetry run alembic upgrade head
```

### 3. Start the Server

**Option A: Using the run script**
```bash
poetry run python dashboard/backend/run_server.py
```

**Option B: Using uvicorn directly**
```bash
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Option C: Using Python module syntax**
```bash
cd dashboard/backend
poetry run python -m app.main
```

The server will start on `http://localhost:8000`

### 4. Test Endpoints

**Option A: Use the test script**
```bash
# In a new terminal (keep server running)
poetry run python dashboard/backend/test_endpoints.py
```

**Option B: Use curl**
```bash
# Health check
curl http://localhost:8000/health

# Get runs
curl http://localhost:8000/api/runs/

# Get universe
curl http://localhost:8000/api/universe/

# Get portfolio
curl http://localhost:8000/api/portfolio/

# Get orders
curl http://localhost:8000/api/orders/

# Get events
curl http://localhost:8000/api/events/
```

**Option C: Use the interactive API docs**
Open your browser and visit:
```
http://localhost:8000/docs
```

This provides a Swagger UI where you can test all endpoints interactively.

### 5. Test SSE Stream

In a terminal, connect to the SSE stream:

```bash
curl -N http://localhost:8000/api/events/stream
```

You should see keepalive messages every 30 seconds. When events are logged, they'll appear here.

### 6. Test Event Logger

In a Python shell or script:

```python
from dashboard.backend.app.services.event_logger import log_event

# Log a test event
log_event(
    event_type="test_event",
    source="manual_test",
    message="This is a test event",
    metadata={"test": True}
)
```

Then check the events endpoint:
```bash
curl http://localhost:8000/api/events/
```

## Troubleshooting

### "No such file or directory" error

If you get this error, check:

1. **Are you in the project root?**
   ```bash
   pwd
   # Should show: /path/to/Investment-agent
   ```

2. **Does the file exist?**
   ```bash
   ls -la dashboard/backend/run_server.py
   ```

3. **Try using absolute path from project root:**
   ```bash
   poetry run python -m dashboard.backend.run_server
   ```
   (Note: This requires `__main__.py` - see below)

### Alternative: Create a module entry point

If the direct script doesn't work, you can create a `__main__.py`:

```bash
# Create the file
cat > dashboard/backend/__main__.py << 'EOF'
from dashboard.backend.run_server import *
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "dashboard.backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
EOF

# Then run as module
poetry run python -m dashboard.backend
```

### Port already in use

If port 8000 is busy:

```bash
# Find what's using it
lsof -i :8000

# Or use a different port
poetry run python dashboard/backend/run_server.py --port 8001
```

### Database connection errors

Make sure the database exists:

```bash
ls -la data/investment_agent.db
```

If it doesn't exist, run migrations:

```bash
poetry run alembic upgrade head
```

## Expected Behavior

### Successful Server Start

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [XXXX] using WatchFiles
INFO:     Started server process [XXXX]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Successful API Call

A successful GET request should return:
- Status code: 200
- JSON response (may be empty array `[]` if no data exists yet)

### Successful SSE Connection

You should see:
```
data: {"type": "connected", "message": "SSE stream connected"}

: keepalive

: keepalive
...
```

## Next Steps

Once the backend is tested and working:

1. **Instrument the agent** - Add event logging calls throughout the orchestrator
2. **Build the frontend** - Create the React UI (Phase 3)
3. **Deploy** - Set up nginx and deployment scripts (Phase 4)
