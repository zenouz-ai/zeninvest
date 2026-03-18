# Phase 1 Implementation Plan: Dashboard UX Critical Path

## Context
Implements the 3 Phase 1 items from `docs/UX_AUDIT.md` plus one minor fix. All backend endpoints already exist — this is purely frontend work.

---

## Step 1: Fix hamburger menu not closing on navigation (RE-4)
**Files:** `dashboard/frontend/src/App.tsx`

- Pass `onClick={() => setMobileMenuOpen(false)}` to `<NavLinks>` component
- In `NavLinks`, wrap each `<NavLink>` so clicking it calls `onClick` prop
- Minimal change, good warm-up

---

## Step 2: Wire missing API clients (prerequisite)
**Files:** `dashboard/frontend/src/api/client.ts`

- Add `pause()` and `resume()` to `systemApi` (POST `/api/system/pause`, `/api/system/resume`)
- These endpoints already exist in the backend but aren't exposed in the frontend client
- Also add `performanceApi` type for the metrics response (currently `any`)

---

## Step 3: Build AlertBanner component (IA-3, VD-3)
**Files:** `dashboard/frontend/src/components/AlertBanner.tsx` (new)

Create a persistent alert aggregation banner that sits below the navbar on every page. It fetches from multiple lightweight endpoints and aggregates alerts:

**Alert sources (each checked independently):**
1. **System state** — CAUTIOUS (amber) or HALTED (red) → from `statusApi.get()`
2. **SSE disconnected** — (amber) → from `useSSE` hook's `isConnected`
3. **Cost degradation** — not FULL → (amber for NO_GEMINI/NO_GPT4O, red for NO_STRATEGY/HALTED) → from `costsApi.getDegradation()`
4. **Losing positions** — any position with pnl_pct < -5% → (amber) → from `portfolioApi.current()`
5. **Failed orders** — any recent order with status=failed → (red) → from `ordersApi.list({limit:5, status:'failed'})`

**Design:**
- Full-width bar below nav, above page content
- Background: `bg-loss/10 border-loss/30` for red alerts, `bg-warning/10 border-warning/30` for amber
- If multiple alerts, show count badge + first alert text, expandable to show all
- Dismiss per-alert (session-only, `useState`)
- Hidden when no alerts
- Auto-refresh every 30s (same interval as Dashboard)
- Each alert source fetches independently — if one fails, others still show

**Integration:** Add `<AlertBanner />` in `App.tsx` between `</nav>` and `<main>`.

---

## Step 4: Restructure Dashboard home page (IA-1, IA-2, WF-3, IA-4, IA-5, VD-2)
**Files:** `dashboard/frontend/src/pages/Dashboard.tsx`

Replace the current layout with an always-visible 2-column design. Key changes:

### 4a: Replace Promise.all with independent section loading
Each section gets its own `useState` for loading/error/data. If portfolio fails, the rest still loads. Pattern:

```tsx
function useAsyncData<T>(fetcher: () => Promise<T>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // ... fetch on mount + interval, independent error handling
}
```

Create this as a reusable hook in `dashboard/frontend/src/hooks/useAsyncData.ts`.

### 4b: Top bar — reduce from 5 cards to 4, merge duplicates
- **Card 1: System Health** — state badge + paused indicator + pause/resume toggle button + SSE dot (tiny, not a full card)
- **Card 2: Next/Last Cycle** — countdown + last run time/status + cost in one card (merge old cards 1, 2, 5)
- **Card 3: Portfolio** — total value + P&L (keep as-is)
- **Card 4: Performance** — Sharpe (30d) + win rate from `performanceApi.getMetrics()` (new, replaces SSE card)

### 4c: Last Cycle Summary card (always visible, not collapsed)
Below the top bar, a full-width card:
```
Last Cycle: scheduled_20260318_120000 · 12:00 UTC · completed
28 reviewed · 3 BUY · 1 SELL · 2 HOLD · 2 rejected · Cost: £0.08
```
Derived from `latestRun.summary_json` fields. Always visible — no expand/collapse.

### 4d: Two-column layout below summary
**Left column (wider, ~60%):**
- **Positions snapshot** — top 5 positions sorted by `|pnl_gbp|`, showing ticker, P&L (£ and %), small inline bar. "View all → Portfolio" link. Fetched from `portfolioApi.current()`.
- **Recent activity** — last 10 SSE events, always visible (not collapsed). Scrollable. Same rendering as current Activity Feed but always open.

**Right column (~40%):**
- **Monthly stats** — compact version of current "This month" card (runs, cost, P&L)
- **Cumulative stats** — compact version (screened, investigated, uninvestigated)
- **Quick actions** — Dry Run, Live Run, Reset Peak buttons (moved from top bar area to a dedicated card)

### 4e: Move collapsed sections to bottom
Keep "Latest trades & LLM reasons" and "Run summaries" as expandable sections at the bottom, but they're now secondary — the primary content above is always visible.

### 4f: PAUSED state gets distinct badge colour
Add `neutral` (blue/grey) badge colour for paused state instead of overriding ACTIVE green with different text.

---

## Step 5: Add pause/resume toggle to Dashboard
**Files:** `dashboard/frontend/src/pages/Dashboard.tsx`

- Add toggle button next to state badge: "Pause" when active, "Resume" when paused
- Uses `systemApi.pause()` / `systemApi.resume()` (wired in Step 2)
- Confirmation modal for pause (similar to Live Run confirm)
- On success, update local state and refetch status

---

## Step 6: Add aria-expanded to collapsible sections
**Files:** `dashboard/frontend/src/pages/Dashboard.tsx`

- Add `aria-expanded={activityFeedExpanded}` (and equivalent) to all toggle buttons
- Quick accessibility fix while we're editing the file

---

## Step 7: Update documentation
**Files to update:**
- `docs/UX_AUDIT.md` — mark Phase 1 items as implemented
- `docs/DASHBOARD.md` — document new AlertBanner, restructured home layout, pause/resume UI
- `docs/SOPHISTICATION_ROADMAP.md` — move Phase 1 dashboard UX items to delivered
- `CLAUDE.md` — update Dashboard section to reflect new components and layout
- `README.md` — update dashboard description if needed

---

## Build Order & Verification
1. Step 1 (hamburger fix) → verify mobile nav closes
2. Step 2 (API clients) → no UI change, just wiring
3. Step 3 (AlertBanner) → verify banner appears/hides based on state
4. Steps 4-6 (Dashboard restructure) → verify new layout, independent loading, pause/resume
5. Step 7 (docs) → review all doc updates

Each step gets its own commit. Docs updated in Step 7 after all code is stable.

## Files Created
- `dashboard/frontend/src/components/AlertBanner.tsx` (new)
- `dashboard/frontend/src/hooks/useAsyncData.ts` (new)

## Files Modified
- `dashboard/frontend/src/App.tsx`
- `dashboard/frontend/src/api/client.ts`
- `dashboard/frontend/src/pages/Dashboard.tsx`
- `docs/UX_AUDIT.md`
- `docs/DASHBOARD.md`
- `docs/SOPHISTICATION_ROADMAP.md`
- `CLAUDE.md`
- `README.md`
