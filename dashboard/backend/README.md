# Dashboard Backend (Phase 1)

## Status: ✅ Complete and Ready for Testing

The dashboard backend foundation is complete. This includes:

- ✅ FastAPI application with CORS support
- ✅ Database models (`EventsLog`, `Run`) with Alembic migration
- ✅ REST API endpoints for runs, universe, portfolio, orders, and events
- ✅ Server-Sent Events (SSE) stream for real-time activity feed
- ✅ Non-blocking event logger service
- ✅ Configuration integration (`dashboard.enabled`, `dashboard.events_enabled`)

## Quick Start

### 1. Run Database Migration

```bash
poetry run alembic upgrade head
```

This creates the `events_log` and `runs` tables in the existing database.

### 2. Start the Server

```bash
poetry run python dashboard/backend/run_server.py
```

The API will be available at:
- **API**: http://localhost:8000
- **OpenAPI Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### 3. Test Endpoints

```bash
# Test all endpoints
poetry run python dashboard/backend/test_endpoints.py

# Or use curl
curl http://localhost:8000/health
curl http://localhost:8000/api/runs/
curl http://localhost:8000/api/universe/
curl http://localhost:8000/api/portfolio/
curl http://localhost:8000/api/orders/
curl http://localhost:8000/api/events/
```

### 4. Test SSE Stream

```bash
# In one terminal, start the server
poetry run python dashboard/backend/run_server.py

# In another terminal, connect to SSE stream
curl -N http://localhost:8000/api/events/stream
```

## API Endpoints

### Runs
- `GET /api/runs/` — List runs (pagination, filtering by type/date)
- `GET /api/runs/{id}` — Get specific run
- `GET /api/runs/cycle/{cycle_id}` — Get run by cycle_id
- `POST /api/runs/` — Create new run (called by orchestrator)

### Universe
- `GET /api/universe/` — List instruments (pagination, filtering by sector)
- `GET /api/universe/{ticker}` — Get instrument details with latest committee reasoning

### Portfolio
- `GET /api/portfolio/` — Current portfolio snapshot
- `GET /api/portfolio/history` — Portfolio history (pagination, date filtering)

### Orders
- `GET /api/orders/` — Order history (pagination, filtering by ticker/action/status/date)
- `GET /api/orders/{id}` — Get specific order

### Events
- `GET /api/events/` — Event log history (pagination, filtering by type/source/date)
- `GET /api/events/stream` — SSE stream for real-time events

## Event Logger Service

The event logger service (`dashboard.backend.app.services.event_logger`) provides a non-blocking, fail-open way for agent modules to emit events:

```python
from dashboard.backend.app.services.event_logger import log_event

# Log an event (non-blocking, fail-open)
log_event(
    event_type="run_started",
    source="scheduler",
    message="Cycle started at 08:00 UTC",
    metadata={"cycle_id": "2026-03-09T08:00:00Z", "run_type": "scheduled"}
)
```

The logger runs in a background thread and will never block the agent pipeline.

## Configuration

Add to `config/settings.yaml`:

```yaml
dashboard:
  enabled: true
  events_enabled: true
```

Both settings default to `true` if not specified.

## Database Schema

### events_log
- `id` (PK)
- `timestamp` (indexed)
- `event_type` (indexed)
- `source`
- `message`
- `metadata_json` (JSON)

**universe_updated** metadata includes: `num_candidates`, `total_available`, `large_pool`, `mid_pool`, `small_pool`, `large_cap_count`, `mid_cap_count`, `small_cap_count`, `sector_distribution`, `tickers`, `cooldown_hours`, `review_count`, `new_count`, `positions_count`, `cumul_screened`, `cumul_reviewed`, `cumul_orders`

### runs
- `id` (PK)
- `cycle_id` (unique, indexed)
- `run_type` (scheduled|manual|slack_command)
- `started_at` (indexed)
- `completed_at`
- `status` (running|completed|failed)
- `summary_json` (JSON)

## Next Steps (Phase 2)

1. **Instrument the Agent**: Add event logging calls throughout the orchestrator pipeline
2. **Frontend**: Build React frontend (see `docs/DASHBOARD.md`)
3. **Deployment**: Set up nginx reverse proxy and deployment scripts (see Prompt 4)

## Testing

The backend is ready for testing. You can:

1. Start the server and verify all endpoints respond
2. Test SSE stream connection
3. Manually insert test events to verify the event log
4. Test with real agent data once instrumentation is added

## Notes

- The backend reuses the existing agent database (`data/investment_agent.db`)
- All endpoints respect `dashboard.enabled` and return 503 if disabled
- SSE stream respects `dashboard.events_enabled`
- Event logger is fail-open: errors are logged but never propagated
