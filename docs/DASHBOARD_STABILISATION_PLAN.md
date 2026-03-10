# Dashboard Stabilisation Plan

**Status:** Done (2026-03-10)
**Created:** 2026-03-10
**Branch:** `claude/dashboard-stabilisation` (merge to main)
**Prerequisite:** Dry-run state mutation fix (committed)
**Next:** US-1.8 Dashboard VPS Deployment — delivered; see `docs/DASHBOARD_VPS_DEPLOYMENT_PLAN.md`

---

## Overview

Dashboard Phase 1 backend + frontend are ~95% complete. This plan addresses the remaining issues before the dashboard can be considered production-ready.

**Issues found during review:**
1. 5 pre-existing test failures caused by dashboard table initialisation gap
2. Frontend-backend type mismatches that would crash the UI at runtime
3. API client URL mismatches
4. Placeholder endpoint (`POST /api/runs/trigger`)

---

## Step 1: Fix 5 pre-existing test failures — DONE

**Root cause:** Dashboard tables (`events_log`, `runs`) live in `dashboard.backend.app.database.Base` (separate from `src.data.models.Base`). The orchestrator/scheduler now insert into these tables via `log_event()`, but test fixtures only create agent tables → `OperationalError: no such table: events_log`.

**Failing tests:**
| File | Test | Error |
|------|------|-------|
| `tests/test_notifications_integration.py` | `test_orchestrator_paused_emits_cycle_summary` | `no such table: events_log` |
| `tests/test_notifications_integration.py` | `test_orchestrator_emits_instruction_and_summary` | `no such table: events_log` |
| `tests/test_notifications_integration.py` | `test_execute_trade_emits_execution_notification` | `no such table: events_log` |
| `tests/test_notifications_integration.py` | `test_scheduler_exception_emits_critical` | `no such table: events_log` |
| `tests/test_execution.py` | `test_get_position_returns_empty_dict_on_404` | `no such table: events_log` |

**Fix pattern** (already working in `tests/test_dry_run_state.py`):
```python
try:
    from dashboard.backend.app.database import Base as DashboardBase
except ImportError:
    DashboardBase = None

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", ...)
    Base.metadata.create_all(engine)
    if DashboardBase is not None:
        DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

For `test_notifications_integration.py`, also need an autouse `patch_all_get_session` fixture patching `get_session` in all modules that import it (orchestrator, state_machine, event_logger, etc.).

---

## Step 2: Fix frontend-backend type mismatches — DONE

The frontend TypeScript types were written speculatively and don't match the actual backend Pydantic schemas. The **backend schemas are correct** (they match the DB models). Fix: update frontend to match backend.

### PortfolioSnapshot

| Frontend (current, wrong) | Backend (correct) |
|---------------------------|-------------------|
| `snapshot_date: string` | `timestamp: datetime` |
| `total_value: number` | `total_value_gbp: float` |
| `cash_balance: number` | `cash_gbp: float` |
| `positions_json: Record<string, {...}>` | `positions: list[PositionSchema]` |
| Missing | `invested_gbp`, `pnl_gbp`, `pnl_pct`, `num_positions` |

### Position

| Frontend (current, wrong) | Backend (correct) |
|---------------------------|-------------------|
| `value: number` | `value_gbp: float` |
| `pnl: number` | `pnl_gbp: float` |
| `avg_price`, `current_price` | Not in backend schema |
| Missing | `sector: string | null` |

### Order

| Frontend (current, wrong) | Backend (correct) |
|---------------------------|-------------------|
| `filled_at`, `cycle_id`, `dry_run` | Not in backend schema |
| Missing | `timestamp`, `order_type`, `value_gbp`, `strategy`, `conviction` |

### Run

- `RunCreateSchema.run_type` pattern rejects `dry_run` — add it.

### Files to update

| File | Changes |
|------|---------|
| `dashboard/frontend/src/types/index.ts` | Rewrite `PortfolioSnapshot`, add `Position`, rewrite `Order` |
| `dashboard/frontend/src/pages/Portfolio.tsx` | Fix all field refs, use `positions` array not `positions_json`, use £ not $, show sector in pie chart |
| `dashboard/frontend/src/pages/Dashboard.tsx` | Fix portfolio field refs, use £ |
| `dashboard/frontend/src/api/client.ts` | Fix portfolio URL (`/api/portfolio/` not `/api/portfolio/current`), fix `getByCycleId` endpoint |
| `dashboard/backend/app/schemas.py` | Add `dry_run` to `RunCreateSchema` pattern |

---

## Step 3: Implement `POST /api/runs/trigger` — DONE

Implemented with background daemon thread that runs `Orchestrator(dry_run=True).run_cycle()`. Returns `{"message": "Dry-run cycle triggered in background", "status": "started"}`.

---

## Verification

1. `poetry run pytest -v` — all 207 tests pass (0 failures)
2. `cd dashboard/frontend && npm run build` — no TypeScript errors
3. `poetry run python -m src.orchestrator.main --dry-run` — produces stocks
4. Dashboard backend starts and endpoints return correct shapes

---

## Note: Scheduler exception handling

Investigated `src/scheduler/scheduler.py` for a suspected `UnboundLocalError` with exception variable `e`. **Finding: no bug** — all references to `e` are properly scoped within their `except Exception as e:` blocks (lines 62, 111, 116, 154). The nested handlers are correctly structured.
