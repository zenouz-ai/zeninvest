# Main Branch — Updated Impact Review and Action Plan

> Re-verified against current codebase. Last update: 2026-03-16.

## Verification Summary

| Original Plan Item | Current State | Action |
|--------------------|---------------|--------|
| 1. Research router NameError | **No bug** — code is correct (q_base, cache_hits used properly) | None |
| 2. test_endpoints pytest collection | **Fixed** — uses `check_endpoint`, pytest collects 0 items | None |
| 3. Research router unit tests | **Present** — `test_research_router.py` with 3 tests | None |
| 4. Research endpoints in test_endpoints | **Present** — `/api/research/logs`, `/api/research/summary` in list | None |
| 5. Pydantic ConfigDict | **Fixed** — schemas use `model_config = ConfigDict(from_attributes=True)` | None |
| 6. README test count | **Stale** — says 232, actual 232 pass + 1 fail = 233 in tests/ | Update after fixing failing test |
| 7. TESTING.md research | **Present** — research endpoints documented | None |

---

## New Issues (Post-Plan Changes)

### 1. Failing Test: `test_orchestrator_emits_instruction_and_summary`

**File:** `tests/test_notifications_integration.py`

**Error:** `sqlalchemy.exc.InvalidRequestError: This session is in 'prepared' state; no further SQL can be emitted within this transaction.`

**Root cause:** The test uses `patch_all_get_session` which returns the **same** `db_session` for every `get_session()` call. Multiple orchestrator components share this session; a prior operation (e.g. state_machine, cost_tracker) can leave the session in an invalid transaction state before `_build_company_profiles` runs.

**Fix options:**
- **A (recommended):** Mock `_build_company_profiles` in the test to return `[]`, isolating the test to notification behavior and avoiding the session issue.
- **B:** Change the patch to use a session **factory** so each `get_session()` returns a new session from the same engine (matching production behavior).

---

### 2. README Test Count

**Current:** README says "232 tests passing".

**Reality:** Default `pytest` (tests/ only): 232 pass, 1 fail. After fixing the failing test: 233 in tests/. With dashboard/backend: 237 total.

**Action:** Fix the failing test first, then update README to "237 tests passing" (or "233" if only counting tests/ per pyproject testpaths).

---

### 3. CLAUDE.md Notebooks

**Current:** Project Layout lists `diagnostics.ipynb`, `brave_api_smoke.py`, `brave_tavily_comparison.py`, `enrichment_benchmark.py`.

**Missing:** `research_api_decision_framework.ipynb`, `enriched_instruments.ipynb` are not in CLAUDE.md's Project Layout (README does list research_api_decision_framework).

**Action:** Add `research_api_decision_framework.ipynb` and `enriched_instruments.ipynb` to CLAUDE.md notebooks section.

---

## Still Out of Scope (Future Work)

| Item | Status |
|------|--------|
| Dashboard Research page (frontend) | Phase D backend exists; frontend not built |
| Slack research insights | Notifications service has no research formatter |
| Gemini Risk tool-use loop | Gemini uses single-turn; tool-use TBD |

---

## Updated Todo List (Execution Order)

| # | Task | Effort | Priority |
|---|------|--------|----------|
| 1 | Fix `test_orchestrator_emits_instruction_and_summary` (mock `_build_company_profiles` or fix session factory) | 30 min | P0 |
| 2 | Update README test count to 237 (after test fix) | 2 min | P1 |
| 3 | Add `research_api_decision_framework.ipynb` and `enriched_instruments.ipynb` to CLAUDE.md Project Layout | 5 min | P2 |
| 4 | Run full test suite (`pytest tests/ dashboard/backend/`) — verify 237 pass | 5 min | P1 |
| 5 | Run `poetry run python dashboard/backend/test_endpoints.py` (with server) — verify 28/28 | 2 min | P2 |

---

## Items No Longer Needed

- Research router bug fix — code is correct.
- test_endpoints rename — already done.
- Research router tests — already exist.
- Research endpoints in test_endpoints — already present.
- Pydantic migration — already done.

---

## Test Commands

```bash
# Default (tests/ only)
poetry run pytest -v

# Full suite including dashboard
poetry run pytest tests/ dashboard/backend/ -v

# Integration: endpoint script (requires server on :8000)
poetry run python dashboard/backend/test_endpoints.py
```

---

## Document Impact

| Document | Update |
|----------|--------|
| README.md | Test count → 237 after fix |
| CLAUDE.md | Add research_api_decision_framework.ipynb, enriched_instruments.ipynb to notebooks |
| This file | Living plan; update when issues resolved |
