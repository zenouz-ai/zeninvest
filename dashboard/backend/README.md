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

### 1. Install Dependencies and Migrate

```bash
poetry install
poetry run alembic upgrade head
```

### 2. Start the Server

```bash
# Recommended (module syntax):
poetry run python -m dashboard.backend

# Alternative (uvicorn directly):
poetry run uvicorn dashboard.backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# Alternative (script file):
poetry run python dashboard/backend/run_server.py
```

The API will be available at:
- **API**: http://localhost:8000
- **OpenAPI Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### 3. Test Endpoints

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/runs/
curl http://localhost:8000/api/universe/
curl http://localhost:8000/api/portfolio/
curl http://localhost:8000/api/orders/
curl http://localhost:8000/api/events/
```

### 4. Test SSE Stream

```bash
curl -N http://localhost:8000/api/events/stream
```

### Troubleshooting

- **ModuleNotFoundError**: Run `poetry install`
- **Port 8000 in use**: Use `--port 8001` with uvicorn
- **PYTHONPATH issues**: See [START_SERVER.md](START_SERVER.md) for detailed solutions

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
- `GET /api/portfolio/` — Current portfolio snapshot, including per-position profit-lock status and required/active lock prices
- `GET /api/portfolio/history` — Portfolio history (pagination, date filtering)

### Orders
- `GET /api/orders/` — Order history (pagination, filtering by ticker/action/status/date)
- `GET /api/orders/{id}` — Get specific order

### Stop Loss
- `GET /api/stop-loss/current` — Current live stop rows per ticker, merged from broker orders, stop adjustments, and positions without stops; includes profit-lock fields
- `GET /api/stop-loss/adjustments` — Stop-loss adjustment history

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

**universe_updated** metadata includes: `cycle_id`, `stocks_screened`, `num_candidates`, `total_available`, `large_pool`, `mid_pool`, `small_pool`, `large_cap_count`, `mid_cap_count`, `small_cap_count`, `sector_distribution`, `tickers`, `cooldown_hours`, `review_count`, `new_count`, `positions_count`, `cumul_screened`, `cumul_reviewed`, `cumul_orders`

**GET /api/dashboard/monthly-summary** returns: `runs_count`, `cost_gbp`, `llm_cost_gbp`, `api_cost_gbp`, `portfolio_start_gbp`, `portfolio_end_gbp`, `pnl_gbp`, `new_investigated_this_month`, `cumul_screened`, `cumul_investigated`, `cumul_uninvestigated`, `cumul_uninvestigated_enriched`, `cumul_uninvestigated_not_enriched`, `investigated_1_review`, `investigated_2_reviews`, `investigated_3plus_reviews`, `cumul_orders`

### runs
- `id` (PK)
- `cycle_id` (unique, indexed)
- `run_type` (scheduled|manual|slack_command)
- `started_at` (indexed)
- `completed_at`
- `status` (running|completed|failed)
- `summary_json` (JSON; commonly includes `stocks_screened`, `stocks_reviewed`, `decisions_made`, `num_trades`, `num_rejected`, `duration_seconds`)

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
