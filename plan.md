# UX Audit Phase 2 — Implementation Plan

**Goal:** Resolve the remaining 9 Major findings and 2 Minor findings from Phase 2 buckets (2A–2D), bringing the dashboard from 10/28 → 21/28 findings resolved.

## Remaining Open Phase 2 Findings

| ID | Finding | Severity | Bucket |
|----|---------|----------|--------|
| WF-2 | No force-sell from portfolio view | Major | 2A |
| WF-4 | No data freshness indicators | Major | 2B |
| ES-3 | No stale-data warning | Major | 2B |
| VD-1 | Chart colours don't match design system | Minor | 2 |
| VD-5 | Gain/loss colours not colour-blind safe | Major | 2D |
| A11Y-1 | Table rows not keyboard-accessible | Major | 2C |
| A11Y-3 | Colour-only P&L differentiation | Major | 2D |
| A11Y-4 | Sort buttons lack aria-sort | Minor | 2C |
| RE-3 | Modals don't trap keyboard focus | Minor | 2C |

**Net impact: 6 Major + 3 Minor = 9 findings**

---

## Steps

### Step 1: Force-Sell from Portfolio (WF-2)
**Files:** `dashboard/frontend/src/pages/Portfolio.tsx`, `dashboard/frontend/src/api/client.ts`

- Add a "Force Sell" button to each position row in the Portfolio table
- Wire to `POST /api/system/force-sell` (existing backend endpoint)
- Add `systemApi.forceSell(ticker)` to the API client
- Confirmation modal before execution (same pattern as Live Run modal)
- Show success/error toast after execution
- Disable button when system is paused

### Step 2: Data Freshness Indicators (WF-4, ES-3)
**Files:** `dashboard/frontend/src/hooks/useAsyncData.ts`, `dashboard/frontend/src/pages/Dashboard.tsx`, `dashboard/frontend/src/components/AlertBanner.tsx`

- Extend `useAsyncData` to track `lastUpdatedAt: Date | null` (set on each successful fetch)
- Create a `<FreshnessIndicator>` component: "Updated Xs ago" below cards, amber "Data may be stale" when lastUpdated > 2× refresh interval
- Show freshness on the 4 Dashboard top cards and on Portfolio/Universe
- AlertBanner: add stale-data check — if any section hasn't refreshed in >90s, surface a warning alert
- When a fetch fails, keep displaying the old data with a "(stale)" badge rather than wiping it

### Step 3: Keyboard-Accessible Tables (A11Y-1, A11Y-4, RE-3)
**Files:** `dashboard/frontend/src/pages/Universe.tsx`, `dashboard/frontend/src/pages/Portfolio.tsx`, `dashboard/frontend/src/pages/OrderManagement.tsx`, `dashboard/frontend/src/pages/RunHistory.tsx`

- Add `tabIndex={0}`, `role="button"`, and `onKeyDown` (Enter/Space triggers expand) to all expandable table rows
- Add `aria-sort="ascending" | "descending" | "none"` to sortable column headers
- Add keyboard trap to confirmation modals: focus first element on open, Tab cycles within modal, Escape closes. Use a small `useFocusTrap` hook (no new dependency)

### Step 4: Colour Accessibility (VD-5, A11Y-3)
**Files:** `dashboard/frontend/src/pages/Dashboard.tsx`, `dashboard/frontend/src/pages/Portfolio.tsx`, `dashboard/frontend/src/components/AlertBanner.tsx`, plus any file showing P&L

- Add directional arrows: up triangle (▲) for gains, down triangle (▼) for losses, alongside the colour
- Ensure all P&L values consistently show `+`/`-` prefix (audit all pages)
- Add `aria-label` with descriptive text to P&L elements (e.g. "Profit: plus 124 pounds 50")
- Already partially done in Phase 1 Dashboard — extend to Portfolio, Opportunity, Order Management pages

### Step 5: Chart Colour Alignment (VD-1)
**Files:** `dashboard/frontend/src/pages/Costs.tsx`, `dashboard/frontend/tailwind.config.js`

- Audit all Recharts chart instances (Costs page daily chart, any others)
- Replace hardcoded hex colours with design token references (gain: #00ffa3, loss: #ff4466, accent: #00d4ff, neutral: #6332ff)
- Ensure chart tooltips, grid lines, and legends use terminal-text-dim for consistency

### Step 6: Build verification + docs update
- Run `tsc --noEmit` and `vite build` to verify
- Update `docs/UX_AUDIT.md` findings table (mark 9 more as Fixed)
- Update `docs/DASHBOARD.md` with Phase 2 section
- Update `CLAUDE.md` if any new patterns introduced
- Commit and push

---

## Estimated Changes
- ~6 files modified, 1–2 new files (FreshnessIndicator, useFocusTrap)
- No backend changes required (all endpoints exist)
- No new dependencies
