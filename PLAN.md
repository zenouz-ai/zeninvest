# Code Review Remediation Plan

## Overview

This plan addresses all bugs, test gaps, and documentation issues identified during the comprehensive code review session. Work is organized into 4 phases, each independently committable and deployable.

**Branch:** `claude/code-review-deployment-ByTXq`

---

## Phase 1: Configuration Completeness (CORS settings property)
**Scope:** Make the CORS fix fully configurable via settings.yaml

### 1.1 Add `dashboard_cors_origins` property to Settings class
- **File:** `src/utils/config.py`
- **Change:** Add property that reads `dashboard.cors_origins` from YAML
- **Pattern:** Follow existing property style (e.g., `dashboard_enabled`)

### 1.2 Add `cors_origins` key to settings.yaml
- **File:** `config/settings.yaml`
- **Change:** Add `cors_origins` list under `dashboard:` section
- **Default:** `["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:3000", "http://127.0.0.1:8000"]`

### 1.3 Add `cors_origins` to .env.example
- **File:** `config/.env.example`
- **Change:** Document that VPS deployments should override CORS origins

---

## Phase 2: Test Coverage for Untested Modules
**Scope:** Write dedicated tests for 3 modules with zero test coverage + backtesting I/O

### 2.1 Tests for `search_api_tracker.py` (~8 tests)
- **New file:** `tests/test_search_api_tracker.py`
- **Source:** `src/utils/search_api_tracker.py` (80 lines, 3 functions)
- **Tests to write:**
  - `test_get_monthly_count_empty_db` — returns 0 when no logs exist
  - `test_get_monthly_count_current_month` — counts only current month's entries
  - `test_get_monthly_count_ignores_previous_month` — entries from last month excluded
  - `test_check_budget_under_limit` — returns True when below configured limit
  - `test_check_budget_at_limit` — returns False when at or over limit
  - `test_check_budget_unknown_provider` — graceful handling of unconfigured provider
  - `test_log_call_creates_api_log` — persists to api_logs table
  - `test_log_call_with_all_fields` — verifies all fields are stored correctly

### 2.2 Tests for `daily_report.py` (~6 tests)
- **New file:** `tests/test_daily_report.py`
- **Source:** `src/agents/reporting/daily_report.py` (163 lines)
- **Tests to write:**
  - `test_generate_daily_report_no_data` — handles empty DB gracefully
  - `test_generate_daily_report_with_snapshot` — includes portfolio value
  - `test_generate_daily_report_with_trades` — lists today's trades
  - `test_get_latest_snapshot_returns_most_recent` — correct snapshot selection
  - `test_get_trades_filters_by_date` — only today's trades included
  - `test_build_daily_md_format` — validates markdown structure

### 2.3 Tests for `weekly_report.py` (~8 tests)
- **New file:** `tests/test_weekly_report.py`
- **Source:** `src/agents/reporting/weekly_report.py` (302 lines)
- **Tests to write:**
  - `test_generate_weekly_report_no_data` — handles empty DB gracefully
  - `test_generate_weekly_report_with_snapshots` — weekly P&L calculation
  - `test_get_week_trades_filters_correctly` — date range filtering
  - `test_get_moderation_stats_aggregation` — moderation verdict counts
  - `test_get_risk_events_counts_vetoes` — risk veto counting
  - `test_get_week_costs_by_provider` — cost breakdown aggregation
  - `test_build_weekly_md_format` — validates markdown structure
  - `test_weekly_report_includes_all_sections` — all sections present

### 2.4 Tests for `backtesting/io.py` (~5 tests)
- **New file:** `tests/test_backtesting_io.py`
- **Source:** `src/backtesting/io.py`
- **Tests to write:**
  - `test_load_bars_from_csv` — reads cached CSV correctly
  - `test_load_bars_missing_file_returns_empty` — handles missing data
  - `test_generate_synthetic_bars_deterministic` — same seed = same output
  - `test_generate_synthetic_bars_shape` — correct columns and row count
  - `test_check_no_lookahead_passes_clean_data` — validates no-lookahead check

---

## Phase 3: Documentation Updates
**Scope:** Update all affected docs to reflect the 5 fixes and new test coverage

### 3.1 Update `CLAUDE.md`
- Update cost degradation cascade description to clarify that NO_GEMINI is returned when only one moderator is over budget (regardless of which one), and NO_GPT4O only when both are over budget
- Add `dashboard_cors_origins` to the Configuration section
- Update test count after Phase 2

### 3.2 Update `docs/ARCHITECTURE.md`
- Add CORS configuration paragraph to Dashboard section
- Update cost degradation Mermaid diagram to reflect the corrected NO_GEMINI behavior
- Note session management improvement in orchestrator

### 3.3 Update `docs/DASHBOARD.md`
- Add Security section covering CORS policy
- Document `dashboard.cors_origins` configuration
- Note that production deployments must set explicit origins

### 3.4 Update `docs/DASHBOARD_DEPLOYMENT.md`
- Add CORS Configuration section with production setup instructions
- Document how to add VPS IP to `cors_origins` in settings.yaml
- Add nginx reverse proxy CORS header notes

### 3.5 Update `docs/DEPLOYMENT.md`
- Add CORS configuration to dashboard deployment section
- Document `dashboard_cors_origins` environment-specific setup

### 3.6 Update `docs/GOVERNANCE.md`
- Verify cost degradation cascade matches code (NO_GEMINI for single moderator failure)
- Update if the current description references the old NO_GPT4O behavior

### 3.7 Update `README.md`
- Update test count to reflect new tests added in Phase 2
- Add CORS note in dashboard section

### 3.8 Update `docs/LOCAL_SETUP.md`
- Add CORS note for local dashboard development
- Document that localhost origins are allowed by default

---

## Phase 4: Verification & Deployment
**Scope:** Final validation and push

### 4.1 Run full test suite
- `poetry run pytest -v` — all tests must pass
- Verify new test count matches README claim

### 4.2 Run type checking
- `poetry run mypy src/` — no new type errors

### 4.3 Final commit and push
- Commit all Phase 1-3 changes
- Push to `claude/code-review-deployment-ByTXq`

---

## Already Completed (Pre-Plan)

These 5 fixes are committed in `f73831e`:

| # | Fix | File |
|---|-----|------|
| 1 | Cost tracker: NO_GEMINI when only OpenAI is over budget | `src/utils/cost_tracker.py` |
| 2 | Session leak: try/finally for queued-ticker query | `src/orchestrator/main.py` |
| 3 | Gemini JSON repair: return safe default instead of raising | `src/agents/moderation/gemini_mod.py` |
| 4 | Failing test: mock get_settings for T212Client | `tests/test_execution.py` |
| 5 | CORS: configurable allow-list instead of wildcard | `dashboard/backend/app/main.py` |

---

## Success Criteria

- All tests pass (target: ~297 tests = 270 existing + ~27 new)
- No type errors from mypy
- All documentation references to CORS, degradation levels, and test counts are consistent
- CORS is configurable via settings.yaml for VPS deployment
- Zero untested reporting/utility modules
