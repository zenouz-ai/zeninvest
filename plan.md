# UX Audit Phase 3 — Implementation Plan

**Goal:** Resolve remaining 9 findings from the audit, completing the full 28/28. Phase 3 items are polish, differentiation, and enhancements. Note: 3C (Performance Widget) was already delivered in Phase 1.

## Remaining Open Findings

| ID | Finding | Severity | Bucket |
|----|---------|----------|--------|
| RE-1 | Tables not responsive on mobile | Major | 3D |
| IA-6 | 8 top-level nav items excessive | Enhancement | 3 |
| VD-4 | Typography hierarchy is flat | Minor | 3 |
| ES-2 | No skeleton loading screens | Enhancement | 3 |
| RE-2 | No mobile-optimised priority view | Enhancement | 3D |
| WF-5 | No deep-link from notification to decision | Enhancement | 3E |

**Also from the audit's Phase 3 proposals (not findings, but value-add):**
- 3A: Position Sparklines
- 3B: Decision Pipeline Waterfall

**Net: 1 Major + 2 Minor-equivalent + 4 Enhancement = 7 findings + 2 bonus features**

---

## Steps

### Step 1: Mobile-Responsive Tables (RE-1, RE-2)
**Files:** `dashboard/frontend/src/pages/Portfolio.tsx`, `dashboard/frontend/src/pages/Universe.tsx`, `dashboard/frontend/src/pages/OrderManagement.tsx`, `dashboard/frontend/src/pages/Dashboard.tsx`

- Add horizontal scroll wrapper (`overflow-x-auto`) to all tables (most already have it — verify)
- On viewports <768px, hide lower-priority columns (sector, quantity on Portfolio; industry, market_cap on Universe) using Tailwind responsive `hidden sm:table-cell`
- Create a mobile priority view for Portfolio: below 640px, render positions as stacked cards instead of a table row (ticker + P&L + value, Force Sell button). Use CSS media query or a `useMediaQuery` hook
- Dashboard home positions already use a card-like layout — no change needed

### Step 2: Nav Consolidation (IA-6)
**Files:** `dashboard/frontend/src/App.tsx`

- Group 8 nav items into logical clusters using a dropdown or visual separator:
  - Primary: Dashboard, Universe, Portfolio (always visible)
  - Secondary (collapsed into "More" dropdown on desktop, all shown on mobile): Runs, Opportunity, Orders, Costs, Roadmap
- Implement with a simple dropdown (no external dependency), toggled by a "More" button in the desktop nav
- Mobile hamburger menu shows all items flat (current behaviour preserved)

### Step 3: Typography Hierarchy (VD-4)
**Files:** `dashboard/frontend/tailwind.config.js`, various page files

- Define a clear type scale in Tailwind config using Outfit font:
  - Page title: `text-2xl font-bold` (already used by PageBrandHeader)
  - Section heading: `text-lg font-semibold` (already used)
  - Card label: `text-sm font-medium text-terminal-text-dim`
  - Body: `text-sm`
  - Caption/meta: `text-xs text-terminal-text-dim`
- Audit all pages and ensure consistent application — no new classes needed, just consistency
- Add subtle letter-spacing to section headings for ZENOUZ brand feel

### Step 4: Skeleton Loading Screens (ES-2)
**Files:** new `dashboard/frontend/src/components/Skeleton.tsx`, `Dashboard.tsx`, `Portfolio.tsx`, `Universe.tsx`

- Create a `<Skeleton>` component: pulsing placeholder rectangles (Tailwind `animate-pulse bg-terminal-border/30 rounded`)
- Variants: `SkeletonCard` (card-shaped), `SkeletonTable` (header + N rows), `SkeletonText` (single line)
- Replace "Loading..." text in `useAsyncData`-powered sections with skeleton placeholders
- Apply to Dashboard (4 top cards, positions, activity), Portfolio (summary cards, table), Universe (table)

### Step 5: Deep-Linking & URL State (WF-5)
**Files:** `dashboard/frontend/src/pages/Universe.tsx`, `dashboard/frontend/src/pages/Portfolio.tsx`, `dashboard/frontend/src/App.tsx`

- Persist Universe filters (search, sector, sort column/direction) in URL query params using `useSearchParams` from react-router-dom
- Support direct ticker detail links: `/universe/AAPL_US_EQ` opens the Universe page with that ticker expanded
- Add a new route: `<Route path="/universe/:ticker" element={<Universe />} />`
- Portfolio: persist any active filters in URL params
- This enables Slack notifications to include clickable dashboard links in future

### Step 6: Position Sparklines (3A — bonus)
**Files:** new `dashboard/frontend/src/components/Sparkline.tsx`, `Portfolio.tsx`, `Dashboard.tsx`

- Create a lightweight SVG sparkline component (no new dependency — just a `<path>` from 7 data points)
- Data: use the existing portfolio history snapshots or a new `/api/portfolio/position-history/{ticker}` endpoint (if backend supports it). If not available, skip and use a placeholder
- Show inline in Portfolio table and Dashboard positions snapshot
- Tiny chart: ~60px wide, 20px tall, single stroke line

### Step 7: Decision Pipeline Waterfall (3B — bonus)
**Files:** new `dashboard/frontend/src/components/PipelineWaterfall.tsx`, `Universe.tsx` (detail panel)

- Replace the stacked expandable LLM blocks in Universe detail with a horizontal pipeline flow
- 4 stages: Strategy → Moderation → Risk → Execution
- Each stage is a compact card showing: action/verdict, key metric (conviction, score, rules)
- Click to expand full reasoning (same content as current LLMOutputPanel)
- Colour-coded: green (pass/approve), red (fail/reject/veto), grey (skipped/not invoked)
- Falls back to current LLMOutputPanel layout if data is missing

### Step 8: Build verification + docs update
- Run `tsc --noEmit` and `vite build`
- Update `docs/UX_AUDIT.md` — mark all 28 findings as fixed, update score from 6.5 to target 9+/10
- Update `docs/DASHBOARD.md` with Phase 3 section
- Update `docs/SOPHISTICATION_ROADMAP.md` (US-1.7.3)
- Commit and push

---

## Estimated Changes
- ~8 files modified, 3-4 new component files
- No new npm dependencies (sparklines are pure SVG, skeletons are Tailwind)
- 1 new route (`/universe/:ticker`)
- Backend: no changes needed (all data already available)
