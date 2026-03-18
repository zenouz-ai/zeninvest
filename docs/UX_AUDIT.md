# UX Audit: ZENOUZ.ai Investment Agent Dashboard

**Date:** 2026-03-18
**Auditor:** Senior UX Designer (Financial Dashboard Specialist)
**Scope:** Full frontend under `dashboard/frontend/src/` — 8 pages, 6 reusable components, API layer, design system
**Current Rating:** 6.5 / 10

---

## Executive Summary

The ZENOUZ.ai dashboard is a competent first-generation monitoring interface for an autonomous trading agent. It demonstrates strong brand identity (dark terminal aesthetic, cyan-emerald gradient), correct library choices (Recharts, TanStack Table, D3), and meaningful data depth — especially the LLM reasoning drill-down which is a genuine differentiator for AI-agent transparency.

However, the dashboard currently operates as a **data catalogue** rather than a **decision-support tool**. Information is organised by data type (universe, portfolio, orders) rather than by the user's real-time monitoring workflow. The primary user — someone who checks the agent every few hours, needs to quickly assess "is everything OK?", and occasionally intervenes — must visit 3-4 pages and scroll through collapsed sections to form a complete picture.

The findings below are prioritised by impact on the primary monitoring workflow.

---

## 1. Information Architecture

### 1.1 Current vs. Optimal Information Hierarchy

| Priority | What the user needs first | Current location | Clicks/scrolls to reach |
|----------|--------------------------|------------------|------------------------|
| 1 | **System health at a glance** (state + anomalies) | Dashboard top bar — state badge + 5 cards | 0 (good) |
| 2 | **Open positions P&L** (which are winning/losing?) | Portfolio page, table at bottom | 2 clicks + scroll |
| 3 | **Latest decisions & reasoning** | Dashboard "Latest trades" (collapsed) | 1 click to expand + scroll |
| 4 | **Upcoming actions** (queued, pending orders) | Opportunity page + Order Mgmt page | 2-3 clicks |
| 5 | **Cost & budget status** | Costs page | 1 click |
| 6 | **Historical performance trend** | Portfolio page chart | 1 click |

**Finding: Time to insight is 2-4 clicks from landing to understanding system health + positions + decisions.**

| ID | Finding | Severity |
|----|---------|----------|
| IA-1 | **Dashboard home buries actionable information behind collapsed sections.** Activity Feed, Latest Trades, and Run Summaries all default to collapsed. The user must expand 3 sections to see what happened. The most decision-critical content (what did the agent just do?) requires the most interaction. | **Critical** |
| IA-2 | **Portfolio positions are on a separate page.** For an agent monitor, open positions with current P&L are top-3 information. They should be visible on the home page without navigation. Bloomberg, TradingView, and every portfolio tracker show positions on the primary view. | **Major** |
| IA-3 | **No unified "attention required" signal.** There is no aggregated indicator for: positions losing >X%, pending orders stuck, agent state degraded, budget nearing limits, or SSE disconnected. Each requires visiting a different page. | **Critical** |
| IA-4 | **SSE status card occupies prime real estate.** One of 5 top-bar cards shows SSE connection status — a technical diagnostic detail that matters only when broken. This card should be a small indicator in the nav bar, not a KPI card equivalent to Portfolio Value. | **Minor** |
| IA-5 | **"Latest Run" card duplicates "Last Run" card.** Cards 2 and 5 in the top bar show overlapping information (last run time/status vs. last run trades/rejections). These should be a single card with the trade count as a secondary line. | **Minor** |
| IA-6 | **Navigation has 8 top-level items.** For a single-user monitoring tool, this is excessive. Roadmap is internal/dev content that does not belong alongside operational pages. Costs and Order Management could be secondary tabs within a parent view. | **Enhancement** |

### 1.2 Data Density Assessment

The dashboard errs on the side of **too sparse** in the primary views and **too dense** in the drill-downs:

- **Dashboard home**: 5 small cards with 1-2 data points each, then large empty collapsed sections. The information-to-whitespace ratio is low for a financial dashboard.
- **Universe table**: 14 columns in a horizontally scrollable table. Several (Industry, Status, Research) are secondary and could be hidden by default or shown on hover/expand.
- **LLM Output Panel**: Deep, nested expandable blocks with raw JSON toggles. Excellent for investigation, but the initial summary could be denser — a single-line verdict per committee member.

---

## 2. User Workflow Alignment

### 2.1 Primary User Profile

The user is a quantitative professional who:
1. Checks the dashboard 3-6 times daily (around cycle times)
2. Needs to confirm the agent is operating correctly
3. Reviews specific decisions when positions move unexpectedly
4. Intervenes rarely (pause, force-sell, reset peak)
5. Calibrates strategy by reviewing decision quality over time

### 2.2 Top 5 User Tasks — Evaluation

| # | Task | Current support | Rating |
|---|------|----------------|--------|
| 1 | **"Is the agent OK?"** — Quick health check | State badge visible immediately. But no anomaly aggregation: user must mentally check state + SSE + last run status + cost degradation + pending orders across multiple pages. | 5/10 |
| 2 | **"What did it just do?"** — Review last cycle | Must expand "Latest trades" section, scroll, click individual rows. No cycle-level summary card that says "Cycle 14:00 — 3 BUYs, 1 SELL, 2 rejected by risk, cost £0.12". | 4/10 |
| 3 | **"How are my positions?"** — Check P&L | Must navigate to Portfolio page. No position heatmap or P&L sparklines visible from home. | 3/10 |
| 4 | **"Why did it buy/sell X?"** — Decision drill-down | Excellent. LLMOutputPanel with Strategy/Moderation/Risk/Research blocks. Expandable, raw JSON available. Best-in-class for agent transparency. | 9/10 |
| 5 | **"I need to intervene"** — Pause, force-sell, reset peak | Dry Run and Live Run buttons on home. Reset Peak conditional on CAUTIOUS. But force-sell requires CLI (`--force-sell AAPL_US_EQ`); not available in dashboard. Pause/Resume not in UI either. | 4/10 |

### 2.3 Missing Dashboard Actions

| Action | Currently available | Should be |
|--------|-------------------|-----------|
| Trigger dry run | Dashboard button | OK |
| Trigger live run | Dashboard button (with confirm) | OK |
| Reset peak | Dashboard button (CAUTIOUS only) | OK |
| Pause/Resume agent | CLI only | Dashboard toggle |
| Force-sell position | CLI only | Dashboard button per position |
| Override stop-loss | CLI only | Dashboard inline edit |
| Exclude ticker from universe | Not available | Dashboard action on Universe row |

| ID | Finding | Severity |
|----|---------|----------|
| WF-1 | **No pause/resume control in dashboard.** The agent shows `paused` state in the badge but provides no UI to toggle it. User must SSH to server and run CLI command. | **Major** |
| WF-2 | **No force-sell from portfolio view.** When a position is losing badly, the user must leave the dashboard, SSH to the server, and run a CLI command. In a trading context, this delay is unacceptable. | **Major** |
| WF-3 | **No cycle-level summary card on home.** The "Run summaries" section exists but is collapsed and shows a list. There should be an always-visible card for the most recent cycle with key metrics: decisions made, orders executed, cost, duration. | **Major** |
| WF-4 | **No data freshness indicators.** The 30-second polling interval is not communicated to the user. There is no "Last refreshed: 12s ago" timestamp. When data is stale (API down, SSE disconnected), the user sees old data with no warning. | **Major** |
| WF-5 | **No deep-link from notification to decision.** Slack alerts reference tickers but the dashboard has no URL scheme like `/universe?ticker=AAPL` or `/decision/123` to link directly from a notification to the relevant detail. | **Enhancement** |

---

## 3. Visual Design & Data Visualisation

### 3.1 Library Assessment

| Library | Use case | Verdict |
|---------|----------|---------|
| **Recharts** | Line charts, area charts, pie charts, bar charts | **Appropriate.** Declarative, React-native, good for the data volumes here (<1000 points). For future needs (tick-level data, overlays), consider upgrading to Lightweight Charts or visx. |
| **TanStack Table** | Universe table (1000 rows, 14 columns, sort, filter, expand) | **Appropriate.** Headless, flexible, handles the row count. Missing: column visibility toggles, pagination, and virtualization for scale. |
| **D3** | Universe bubble chart | **Appropriate** for the force-directed layout. Consider replacing with a treemap for sector allocation — more space-efficient and easier to read at a glance. |
| **Mermaid** | Architecture diagram | **Appropriate** for static diagrams on the Roadmap page. |

### 3.2 Colour & Visual Hierarchy

| ID | Finding | Severity |
|----|---------|----------|
| VD-1 | **Chart colours don't match the design system.** Portfolio line chart uses `#4a9eff` (not in the palette) and tooltip uses `#141414` / `#2a2a2a` (not the design tokens `--bg-card` / `--border`). Pie chart colours are correct. This creates visual inconsistency between chart surfaces and card surfaces. | **Minor** |
| VD-2 | **State badges lack sufficient differentiation.** ACTIVE (green), CAUTIOUS (yellow), HALTED (red) use background fills. But the `PAUSED` state overrides the text without changing colour — a paused system in ACTIVE state shows the same green badge with different text. PAUSED should have its own distinct colour (e.g., the existing `--neutral` blue-grey). | **Major** |
| VD-3 | **No visual severity levels for events.** The Activity Feed uses emoji icons per event type but colours are subtle (dim text vs. gain/accent). Critical events (order failed, state transition to HALTED) should use red backgrounds or borders — not just a different text colour that blends into the feed. | **Major** |
| VD-4 | **Typography hierarchy is flat.** Most data uses `text-sm` or `text-xs` with `font-mono`. There is little variation in font weight or size within cards to establish hierarchy between labels and values. Values should be visually dominant (larger, bolder) with labels subordinate. | **Minor** |
| VD-5 | **Gain/loss colours may be indistinguishable for colour-blind users.** `#00ffa3` (green) and `#ff4466` (red) are a red-green pair. ~8% of males have red-green colour blindness. Need supplementary indicators (arrows, +/- prefixes, or pattern fills). The code does use `+`/`-` prefixes in some places (Portfolio P&L) but not consistently. | **Major** |

### 3.3 Edge States

| State | Handling | Quality |
|-------|----------|---------|
| **Loading** | Full-page spinner (`LoadingSpinner` with `role="status"`, `aria-label`) | Adequate. No skeleton screens — the page is blank until all 8 API calls resolve. |
| **Error** | Error message + Retry button | Adequate. Error boundary at app root catches render errors. |
| **Empty** | Per-section messages ("No events yet", "No orders", "No positions") | Adequate but inconsistent. Some use `EmptyState` component, others use inline `<p>` tags. |
| **Stale data** | No handling. 30s polling silently continues; no visual indicator of last-successful-fetch or API failure. | **Poor.** |
| **Partial failure** | Not handled. If one of 8 parallel API calls fails, the entire dashboard shows an error. | **Poor.** |

| ID | Finding | Severity |
|----|---------|----------|
| ES-1 | **All-or-nothing loading.** Dashboard fetches 8 endpoints in `Promise.all`. If any single endpoint fails, the entire page shows an error. Each section should load independently with its own loading/error state. | **Major** |
| ES-2 | **No skeleton loading.** Users see a blank page with a spinner until all data arrives. Skeleton screens (grey shimmer cards/rows in the shape of the final content) reduce perceived load time and prevent layout shift. | **Enhancement** |
| ES-3 | **No stale-data warning.** If the backend goes down after initial load, the UI continues showing the last-fetched data with no indication it may be minutes old. A "Data may be stale" banner should appear when polling fails. | **Major** |

---

## 4. Responsiveness & Accessibility

### 4.1 Mobile Experience

| ID | Finding | Severity |
|----|---------|----------|
| RE-1 | **Tables are horizontally scrollable, not responsive.** The Universe table (14 columns) and order tables require extensive horizontal scrolling on mobile. On a phone, the user sees ~2 columns at a time. Mobile should show a card-based layout with key fields (ticker, action, P&L) and tap-to-expand for details. | **Major** |
| RE-2 | **No mobile-optimised priority view.** A mobile user checking the agent on their phone needs: (1) system state, (2) portfolio P&L total, (3) any alerts. The current mobile view shows the same layout as desktop, just narrower. A dedicated mobile "glance" view would serve this use case. | **Enhancement** |
| RE-3 | **Modals don't trap focus.** The Live Run confirmation modal and Reset Peak modal use `onClick` on the backdrop to close, but don't trap keyboard focus inside the modal. A user tabbing through can focus elements behind the modal overlay. | **Minor** |
| RE-4 | **Hamburger menu doesn't close on navigation.** When a user taps a nav link in the mobile menu, the menu stays open (no `setMobileMenuOpen(false)` on link click). | **Minor** |

### 4.2 Accessibility

| ID | Finding | Severity |
|----|---------|----------|
| A11Y-1 | **Table rows use `onClick` for expansion but aren't keyboard-accessible.** `<tr>` elements are not focusable and don't respond to Enter/Space. Keyboard users cannot expand Universe rows or Latest Trades rows. Use `tabIndex={0}` and `onKeyDown` handlers, or use `<button>` wrappers. | **Major** |
| A11Y-2 | **No `aria-live` region for real-time updates.** SSE events arrive and update the Activity Feed silently. Screen reader users receive no announcement of new events. Add `aria-live="polite"` to the event feed container. | **Minor** |
| A11Y-3 | **Colour-only P&L differentiation.** As noted in VD-5, gain/loss is communicated primarily through colour. Add `aria-label` attributes: `aria-label="Profit: +£42.50"` or `aria-label="Loss: -£12.30"`. | **Major** |
| A11Y-4 | **Sort buttons in table headers lack `aria-sort`.** TanStack Table headers with sort buttons don't communicate current sort state to screen readers. Add `aria-sort="ascending"` / `"descending"` / `"none"` to `<th>` elements. | **Minor** |
| A11Y-5 | **Expand/collapse sections lack `aria-expanded`.** The collapsible sections on Dashboard (Activity Feed, Latest Trades, Run Summaries, Daily Costs) use `<button>` but don't set `aria-expanded`. | **Minor** |

---

## 5. Gap Analysis vs. Best-in-Class

### 5.1 Top 5 Missing Features / Patterns

| # | Gap | What best-in-class does | Impact |
|---|-----|------------------------|--------|
| 1 | **No alert/anomaly aggregation panel** | Bloomberg Terminal: "Top Stories" panel with severity-ranked alerts. TradingView: notification bell with count badge. Datadog: unified alert bar at top of every page. | The user has no single place to see "things that need attention". Alerts are scattered across pages and event feeds. |
| 2 | **No position-level sparklines or mini-charts** | Robinhood/Wealthfront: inline P&L sparkline per position. Portfolio trackers: 7-day price trend next to each holding. | Users cannot see position trajectory without navigating to an external charting tool. |
| 3 | **No decision timeline / audit trail view** | Palantir Foundry: timeline view of agent actions with linked evidence. MLOps dashboards: experiment timeline with parameter diff. | The "Run summaries" section is close but doesn't visualise the pipeline waterfall (Strategy → Moderation → Risk → Execution) as a flow. |
| 4 | **No configurable alerts or thresholds** | Grafana: user-defined alert rules. PagerDuty integration patterns. Custom P&L alert thresholds. | The agent sends fixed Slack alerts. The user cannot configure "alert me if any position drops >5% in a day" or "alert me if cost degradation reaches NO_STRATEGY" from the UI. |
| 5 | **No performance analytics on home page** | Hedge fund dashboards: Sharpe ratio, win rate, alpha badge on the main view. Portfolio analytics: daily/weekly/monthly return comparison. | Performance metrics exist in the DB (`PerformanceMetric` model) and the CLI (`--performance`) but are not surfaced in the dashboard. |

### 5.2 Additional Gaps (Lower Priority)

| Gap | Notes |
|-----|-------|
| No keyboard shortcut system | `?` for help, `g p` for portfolio, `g u` for universe — common in pro tools |
| No data export (CSV/PDF) | User cannot download positions, orders, or decisions for offline analysis |
| No dark/light theme toggle | Only dark mode available; may cause readability issues in bright environments |
| No multi-timeframe comparison | Cannot compare this week vs. last week, this month vs. last month |
| No WebSocket for real-time prices | Portfolio values update only on API poll; no live price stream |

---

## 6. Prioritised Improvement Roadmap

### Phase 1: Critical Path (Estimated: High Impact, Low Effort)

#### 1A. Alert Aggregation Banner
Place a persistent, colour-coded banner below the nav bar on every page:
```
+------------------------------------------------------------------+
| [!] 2 alerts: Position TSLA down -8.2% · Cost degradation: NO_GEMINI |
+------------------------------------------------------------------+
```
- Severity levels: red (critical), amber (warning), blue (info)
- Pulls from: position P&L thresholds, cost degradation status, agent state, pending order failures, SSE disconnect
- Dismiss per-alert with "x"; auto-clear when resolved

#### 1B. Dashboard Home Restructure
Replace collapsed sections with an always-visible 2-column layout:

```
+---------------------------+---------------------------+
| SYSTEM HEALTH             | LAST CYCLE SUMMARY        |
| State: ACTIVE             | Cycle 14:00 UTC           |
| Next run: 2h 15m          | 28 tickers screened       |
| SSE: [green dot]          | 3 BUY, 1 SELL, 2 HOLD    |
| Budget: 62% remaining     | 2 rejected by risk        |
| Degradation: FULL         | Cost: £0.08               |
+---------------------------+---------------------------+
| POSITIONS (top 5 by |P&L|)                            |
| AAPL  +£124.50  +3.2%  ████████                      |
| TSLA  -£45.20   -2.1%  ████                          |
| NVDA  +£89.00   +5.1%  ██████████                    |
| AMZN  +£12.30   +0.4%  █                             |
| META  -£8.50    -0.3%  █                             |
|                          [View all → Portfolio]        |
+-------------------------------------------------------+
| RECENT ACTIVITY (live stream, last 10)                |
| 14:02  BUY AAPL  3 shares  filled                    |
| 14:01  SELL NEM   5 shares  filled                   |
| 14:00  Cycle started                                  |
+-------------------------------------------------------+
```

#### 1C. Partial Loading with Error Isolation
Replace `Promise.all` with independent `useEffect` hooks per section. Each section has its own loading/error/success state. One failing endpoint doesn't take down the whole page.

### Phase 2: Major Improvements (Estimated: High Impact, Medium Effort)

#### 2A. Pause/Resume + Force-Sell Controls
- Add Pause/Resume toggle button next to the state badge on Dashboard home
- Add "Force Sell" action button to each row in the Portfolio positions table (with confirmation modal)
- Wire to existing backend endpoints (`/api/system/pause`, `/api/system/resume`, `/api/orders/force-sell`)

#### 2B. Data Freshness Layer
- Show "Last updated: Xs ago" below each card/section
- When polling fails, show amber "Data may be stale" banner
- SSE indicator: small coloured dot in nav bar (green=connected, red=disconnected), not a full KPI card

#### 2C. Keyboard-Accessible Tables
- Add `tabIndex={0}`, `role="button"`, `onKeyDown` (Enter/Space) to expandable rows
- Add `aria-sort` to sortable column headers
- Add `aria-expanded` to all collapsible sections

#### 2D. Colour Accessibility
- Add directional arrows (up/down triangles) alongside gain/loss colours
- Ensure all gain/loss values have `+`/`-` prefix consistently
- Add `aria-label` with descriptive text to P&L elements
- Test palette with a colour-blindness simulator; consider adding a high-contrast mode

### Phase 3: Polish & Differentiation (Estimated: Medium Impact, Higher Effort)

#### 3A. Position Sparklines
Add 7-day price sparkline to each portfolio row using a lightweight inline chart (Recharts `<Sparkline>` or custom SVG path). Shows trajectory at a glance without navigating to an external charting tool.

#### 3B. Decision Pipeline Waterfall
On the Universe detail panel, replace the stacked expandable blocks with a horizontal pipeline flow:
```
Strategy → Moderation → Risk → Execution
  BUY       APPROVE      PASS    FILLED
  conv: 8   GPT:OK       0 rules  3 shares
            Gem:OK
```
Each stage is a card; click to expand reasoning. Failed stages show red; skipped stages show grey.

#### 3C. Performance Widget on Home
Add a compact performance card on the Dashboard home:
```
+---------------------------+
| PERFORMANCE (30d rolling) |
| Return: +2.4%             |
| Sharpe: 1.12              |
| Win rate: 64%             |
| Max DD: -3.1%             |
+---------------------------+
```
Data from the existing `PerformanceMetric` model.

#### 3D. Mobile Optimised View
Detect viewport <768px and render a simplified layout:
- Top: State badge + portfolio total + P&L
- Middle: Scrollable position cards (ticker, P&L, sparkline)
- Bottom: Last 5 activity events
- Footer: Dry Run / Live Run buttons
No tables on mobile. Card-based layout only.

#### 3E. Deep-Linking & URL State
- Persist filters in URL query params (`/universe?sector=Technology&search=AAPL`)
- Support direct links to ticker details (`/universe/AAPL_US_EQ`)
- Enable Slack notifications to include clickable dashboard links

---

## 7. Scoring

### Current State: 6.5 / 10

**Strengths (+):**
- Strong brand identity and visual consistency (dark terminal aesthetic)
- Excellent decision transparency (LLM Output Panel is best-in-class for AI agent UX)
- Correct technology choices (Recharts, TanStack Table, Tailwind, SSE)
- Real-time event stream (SSE) with proper reconnection logic
- Good error handling at the page level (error + retry pattern)
- Confirmation modals for destructive actions (Live Run, Reset Peak)
- Responsive nav with mobile hamburger menu

**Weaknesses (-):**
- Information architecture optimised for data browsing, not for agent monitoring
- Critical content hidden behind collapsed sections
- No alert aggregation or anomaly detection layer
- Positions not visible from home page
- Missing operational controls (pause, force-sell)
- All-or-nothing loading pattern
- Accessibility gaps in keyboard navigation and colour-only indicators
- No stale-data warnings
- Mobile experience is desktop-in-small, not mobile-optimised

### What a 10/10 Looks Like

A 10/10 autonomous agent monitoring dashboard would:

1. **Answer "is everything OK?" in <2 seconds** with a glanceable health score / traffic light that aggregates system state, position risk, budget status, and connectivity
2. **Surface anomalies proactively** with a persistent alert bar that ranks issues by severity and links directly to the relevant detail
3. **Show positions with context on the home page** — not just P&L numbers, but sparklines, stop-loss proximity, sector exposure bars, and days-held indicators
4. **Provide a "last cycle" narrative** — a human-readable 2-sentence summary: "The agent reviewed 28 stocks, bought AAPL and NVDA, sold NEM. Risk blocked 2 BUYs due to sector concentration."
5. **Enable intervention without leaving the browser** — pause/resume, force-sell, adjust stop-losses, exclude tickers, all with confirmation modals and audit logging
6. **Be keyboard-navigable end-to-end** with shortcuts for power users (`?` for help, `j/k` for row navigation, `e` to expand)
7. **Communicate data freshness everywhere** — every number has a "last updated" timestamp; stale data is visually degraded (greyed out)
8. **Adapt to mobile** with a purpose-built "glance" view that answers the top 3 questions in 10 seconds
9. **Support deep-linking** so Slack/email alerts link directly to the relevant decision or position
10. **Include performance analytics** (Sharpe, win rate, alpha) on the home page as first-class metrics alongside P&L

---

## Appendix: Findings Summary Table

| ID | Finding | Severity | Phase | Status |
|----|---------|----------|-------|--------|
| IA-1 | Dashboard home buries actionable info in collapsed sections | Critical | 1B | **Fixed** — Activity feed + positions always visible |
| IA-2 | Portfolio positions on separate page | Major | 1B | **Fixed** — Top 5 positions on home page |
| IA-3 | No unified "attention required" signal | Critical | 1A | **Fixed** — AlertBanner component |
| IA-4 | SSE status card in prime real estate | Minor | 1B | **Fixed** — Replaced with small dot indicator |
| IA-5 | "Latest Run" / "Last Run" card duplication | Minor | 1B | **Fixed** — Merged into single Cycle card |
| IA-6 | 8 top-level nav items excessive | Enhancement | 3 | Open |
| WF-1 | No pause/resume in dashboard | Major | 2A | **Fixed** — Pause/Resume toggle on home |
| WF-2 | No force-sell from portfolio view | Major | 2A | **Fixed** — Force Sell button per position row |
| WF-3 | No cycle-level summary card | Major | 1B | **Fixed** — Always-visible cycle summary |
| WF-4 | No data freshness indicators | Major | 2B | **Fixed** — FreshnessIndicator + stale-data preservation |
| WF-5 | No deep-link from notification to decision | Enhancement | 3E | Open |
| VD-1 | Chart colours don't match design system | Minor | 2 | **Fixed** — All charts use design tokens |
| VD-2 | State badges lack PAUSED differentiation | Major | 1B | **Fixed** — PAUSED gets cyan badge |
| VD-3 | No visual severity for critical events | Major | 1A | **Fixed** — AlertBanner with severity colours |
| VD-4 | Typography hierarchy is flat | Minor | 3 | Open |
| VD-5 | Gain/loss colours not colour-blind safe | Major | 2D | **Fixed** — Directional arrows (▲/▼) + aria-labels |
| ES-1 | All-or-nothing loading (Promise.all) | Major | 1C | **Fixed** — useAsyncData per section |
| ES-2 | No skeleton loading screens | Enhancement | 3 | Open |
| ES-3 | No stale-data warning | Major | 2B | **Fixed** — useAsyncData preserves stale data + isStale flag |
| RE-1 | Tables not responsive on mobile | Major | 3D | Open |
| RE-2 | No mobile-optimised priority view | Enhancement | 3D | Open |
| RE-3 | Modals don't trap keyboard focus | Minor | 2C | **Fixed** — useFocusTrap hook on all modals |
| RE-4 | Hamburger menu stays open on navigation | Minor | 1 | **Fixed** |
| A11Y-1 | Table rows not keyboard-accessible | Major | 2C | **Fixed** — tabIndex, role="button", onKeyDown |
| A11Y-2 | No aria-live for SSE events | Minor | 2C | **Fixed** — aria-live on activity feed |
| A11Y-3 | Colour-only P&L differentiation | Major | 2D | **Fixed** — PnlDisplay components with arrows + aria-labels |
| A11Y-4 | Sort buttons lack aria-sort | Minor | 2C | **Fixed** — aria-sort on Universe table headers |
| A11Y-5 | Collapsible sections lack aria-expanded | Minor | 2C | **Fixed** |

**Totals:** 2 Critical, 14 Major, 8 Minor, 4 Enhancement
**Phase 1 resolved:** 2 Critical, 5 Major, 3 Minor = 10 fixed
**Phase 2 resolved:** 6 Major, 3 Minor = 9 fixed
**Overall: 19 of 28 findings fixed** (2/2 Critical, 11/14 Major, 6/8 Minor)

---

*Phase 1 fixes: 2026-03-18. Phase 2 fixes: 2026-03-18. Remaining 9 findings are Phase 3 (enhancements + polish).*
