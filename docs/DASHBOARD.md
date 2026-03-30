---
title: Dashboard System
tags: [dashboard, frontend, api]
status: active
last_updated: 2026-03-29
user_stories: [US-1.7]
related: [ARCHITECTURE.md, DEPLOYMENT.md]
---

# Dashboard System

> A real-time operational dashboard for the investment agent that provides full visibility into scheduled and manual runs, stock universe management, committee decisions, portfolio performance, and trading activity. Designed to be extensible for ML features (prediction models, backtesting, anomaly detection) in future phases.

## Purpose

The dashboard is the primary visualisation and monitoring surface for the investment agent. It enables:

- **Real-time visibility** into scheduled and manual cycles, decisions, and order execution
- **Committee transparency** — full pipeline reasoning from strategy through moderation and risk
- **Portfolio management** — current holdings, P&L attribution, sector allocation
- **Opportunity tracking** — UOV scoring, queue state, promotion history
- **Order auditing** — stop-loss adjustments, trailing stops, limit orders, execution trail
- **Order auditing** — stop-loss adjustments, trailing stops, tiered profit-lock metadata, limit orders, execution trail
- **Cost monitoring** — LLM spend tracking, degradation state, API usage
- **Performance analysis** — win rates, Sharpe/Sortino, trade outcomes, attribution by committee member
- **Research transparency** (Phase D) — per-member research activity via `GET /api/research/logs`, `GET /api/research/ticker/{ticker}`, `GET /api/research/summary`; cache hit rates; `research_call` events in SSE stream; Universe table `Research` column and expandable research trail per ticker
- **Software evolution planning** — authenticated operator-only change intake, clarification loop, validation matrix, repo context, and audit trail via `GET/POST /api/evolution/*`

---

## Current Status

### Implementation Timeline (updated 2026-03-29)

| Component | Status | Notes |
|-----------|--------|-------|
| **FastAPI Backend** | Complete | REST for runs, status (incl. system state), universe, portfolio, orders, events; decisions, moderation, risk, opportunity, outcomes, stop-loss, performance, costs, api-usage, research (logs, summary); system (state, trigger, pause, resume); chat-session scaffolding; Evolution Planner routes under `/api/evolution/*`; SSE stream. Core monitoring endpoints read from agent SQLite, while the evolution workflow uses a separate planner domain/audit trail. |
| **Database Models** | Complete | `events_log` + `runs` tables with Alembic migration; backend queries existing agent tables only |
| **Event Logger** | Complete | Non-blocking, fail-open, background thread + queue |
| **Agent Instrumentation** | Complete | Scheduler + orchestrator emit events throughout pipeline |
| **React Frontend** | Complete | **12 pages:** Dashboard Home (`ZenInvest Agent`, system state badge ACTIVE/CAUTIOUS/HALTED, paused), Universe, Run History, Portfolio, Opportunity Pipeline, Insights, Order Management, Chat (`/chat`, with `/commands` retained as a backward-compatible alias: chat-first operator console with session rail, live thread, agent activity rail, evidence panels, proposal rail, and a secondary Legacy Slack Audit tab), World News, Costs, Roadmap & Architecture, and Evolution. Design: ZENOUZ.ai visual system with dark `#06060a`, cyan/violet/emerald accents, atmospheric grid/orbs, glass panels, and branded pills. UX improvements (2026-03-13): active nav state, mobile hamburger menu, loading spinner, error handling with retry, button consistency, sticky table headers, card shadow, focus styles. Branding update (2026-03-24): company/product hierarchy standardised as `ZENOUZ.ai` / `ZenInvest` / `ZenInvest Agent`; shared page header across all tabs now uses a right-aligned hybrid bold Z mark inside a subtle glass panel. Public-surface update (2026-03-29): signed-out visitors can see the full product navigation, but every anonymous page is intentionally either a sanitized live projection (Overview, Universe, Portfolio, Runs, Opportunity, Insights guidance, Costs, World News, Roadmap) or a disabled preview surface (Order Management, Chat, Evolution, Strategy Attribution review). Hardening follow-through (2026-03-27): AlertBanner now surfaces HALTED auto-recovery progress and peak-inflation warnings when active, Order Management shows off-hours order warning notes, and roadmap data reflects `US-7.7` and `US-7.5` as delivered. Execution-quality follow-through (2026-03-29): Order Management now includes an Execution Quality card, grouped slippage stats, open partial-fill visibility, market-order decision/fill/slippage columns, and an alert banner warning when recent average slippage breaches threshold. Agentic chat beta update (2026-03-27/28): `/chat` now exposes planner-led workflow transparency, citations, related tickers, committee views, session-scoped step/cost visibility, and a Legacy Slack Audit tab that clearly states it is not the full conversation archive and auto-refreshes while open. See `docs/DASHBOARD_DESIGN_REVIEW.md` and `docs/ZEN_EVOLUTION_ENGINE.md`. |

Strategy attribution operations note (2026-03-30): a daily scheduler job now scans recent git history and auto-publishes/auto-confirms new strategy episodes (02:00 UTC). Dashboard Home's Strategy Attribution panel renders these active episodes directly and links through to the Insights page for detail.
| **Config** | Complete | `dashboard.enabled`, `dashboard.events_enabled` in settings.yaml |

### Phase 1.5 Analytics Lite (delivered)

- Decision Explorer v1: expandable Universe rows with committee reasoning (strategy, moderation, risk) and full LLM outputs (strategy full text + raw JSON, all moderators' reasoning, risk reasoning and rules)
- Run-to-run diff: compare positions between two runs (new, closed, size changes)
- Top-bar: next run countdown, P&L summary

### UX Phase 1 — Critical Path (delivered 2026-03-18)

Based on `docs/UX_AUDIT.md`, resolved 10 of 28 findings (2 Critical, 5 Major, 3 Minor):

- **AlertBanner** (`AlertBanner.tsx`): persistent alert aggregation bar below navbar on all pages. Checks 6 sources independently: system state, SSE down (warning only after ~10s continuous disconnect to avoid false positives on load/reconnect), cost degradation, losing positions (>5%), unresolved failed orders from `/api/orders/health`, and execution-quality threshold breaches from `/api/orders/execution-quality`. Severity-coded (red critical, amber warning), dismissible, auto-refresh 30s.
- **Dashboard home restructure**: replaced collapsed sections with always-visible layout. Two-column grid: positions + activity (left), cumulative stats + cost breakdown (right). Last cycle summary always visible above the fold.
- **Independent section loading** (`useAsyncData` hook): each dashboard section fetches and error-handles independently — one failing endpoint no longer takes down the whole page.
- **Positions on home page**: top 5 positions by |P&L| shown on Dashboard with inline bar chart, linking to Portfolio page.
- **Performance card**: replaces SSE status card with Sharpe (30d), win rate, max drawdown, trade count from `/api/performance/metrics`.
- **Pause/Resume toggle**: wired `systemApi.pause()` / `resume()` to Dashboard UI with confirmation modal.
- **SSE lifted to App level**: SSE connection shared between AlertBanner and Dashboard via props. The client uses **`fetch()` + `ReadableStream`** (not `EventSource`) with session credentials included; reconnect uses exponential backoff.
- **PAUSED badge colour**: distinct cyan badge instead of reusing ACTIVE green.
- **aria-expanded** on all collapsible sections, **aria-live** on activity feed.
- **Mobile nav fix**: hamburger menu closes on link click.

### UX Phase 2 — Major Improvements (delivered 2026-03-18)

Resolved 9 more findings (6 Major, 3 Minor) from `docs/UX_AUDIT.md`:

- **Force Sell** (`Portfolio.tsx`): "Force Sell" button on each position row, wired to `POST /api/system/force-sell/{ticker}` (new backend endpoint). Confirmation modal with focus trap, success/error toast. The Portfolio page itself is now public read-only when signed out; Force Sell only appears for authenticated operators.
- **Data freshness** (`useAsyncData` extended, `FreshnessIndicator.tsx`): `lastUpdatedAt` and `isStale` fields. "Updated Xs ago" shown below Dashboard cards. When a fetch fails, old data is preserved with "(stale)" label instead of being wiped.
- **Keyboard-accessible tables** (`Universe.tsx`, `Dashboard.tsx`): expandable rows get `tabIndex={0}`, `role="button"`, `onKeyDown` (Enter/Space). Universe column headers get `aria-sort`.
- **Focus trap** (`useFocusTrap.ts`): all modals (Live Run, Reset Peak, Pause, Force Sell) trap Tab/Shift+Tab, Escape closes.
- **Colour accessibility** (`PnlDisplay.tsx`): `PnlCurrency` and `PnlValue` components render directional arrows (▲/▼) alongside colour, with `aria-label` for screen readers. Applied to Dashboard + Portfolio.
- **Chart colour alignment**: Portfolio line chart and pie chart now use design tokens (#00d4ff accent, #30363d grid, #8b949e axis). Costs chart API colour aligned to #ff4466 (loss token). Tooltip backgrounds aligned.
- **Pie tooltip readability fix** (`Portfolio.tsx`, 2026-03-19): Sector Allocation hover tooltip now forces high-contrast styling (dark surface, cyan border, explicit light item text + cyan label text) and value formatter (`£` with decimals) to avoid black-on-dark clashes on slices like Energy.

### UX Phase 3 — Final Polish + Bonus Features (delivered 2026-03-19)

Resolved final 9 findings + 2 bonus features, completing all 28/28 UX audit items:

- **Mobile-responsive tables** (`Portfolio.tsx`, `Universe.tsx`): Card layout on mobile (`sm:hidden`), hidden secondary columns on tablet via `meta.responsive` on TanStack column defs (RE-1, RE-2).
- **Nav consolidation** (`App.tsx`): Primary 5 destinations on desktop for authenticated operators (`Dashboard`, `Universe`, `Portfolio`, `Runs`, `Roadmap`) + `More` dropdown for 6 authenticated secondary pages (`Opportunity`, `Order Mgmt`, `Research`, `Evolution`, `World News`, `Costs`). Signed-out visitors now also see the full product navigation, with each page rendered as either sanitized live data or a preview-only surface. Click-outside + `aria-expanded` (IA-6).
- **Typography hierarchy**: `tracking-wide` on all section h2 headings, explicit `text-base` on modal h3s, consistent type scale across the authenticated page surface (VD-4).
- **World News page** (`WorldNews.tsx`): `/world-news` — macro regime card (hero), regime timeline, expandable headline feed grouped by date with category filters (fed/rates/trade/earnings/inflation/jobs/gdp/market), action plan section (sector implications, risks, opportunities), sector snapshot. Dashboard Home compact macro bar with regime badge + headline count + link. The page now has a public read-only mode backed by `/api/public/macro/*`, while operator-only macro audit endpoints stay private under `/api/macro/*`.
- **Skeleton loading screens** (`Skeleton.tsx`): `DashboardSkeleton`, `TableSkeleton`, `SkeletonCard` with pulsing placeholders. Replaces `LoadingSpinner` on all pages (ES-2).
- **Deep-linking & URL state** (`Universe.tsx`): `/universe/:ticker` route auto-expands matched row. `?q=` and `?sector=` search params synced to URL via `useSearchParams` (WF-5).
- **Position sparklines** (`Sparkline.tsx`, `Portfolio.tsx`): Inline SVG sparkline per position showing P&L % trend across portfolio history snapshots. Directional colouring (green up, red down). Desktop + mobile (3A bonus).
- **Decision pipeline waterfall** (`PipelineWaterfall.tsx`, `LLMOutputBlocks.tsx`): Horizontal Strategy → Moderation → Risk → Execution flow with colour-coded stage nodes (pass/block/skip/pending). Shown at top of every LLM Output Panel (3B bonus).

### Visual Design System — US-1.7.3 (delivered 2026-03-22)

Formalised the ZENOUZ.ai visual language from `dashboard/frontend/dashboard-style-guide.md`:

- **Syne font** added (`index.html`) — headings and KPI values globally use Syne; body stays Outfit; tickers use JetBrains Mono
- **Full CSS token system** (`index.css`): `--color-bg/surface/surface-strong/surface-soft`, `--color-text/text-muted/text-dim`, `--color-border/border-strong`, soft accent fills (`--color-violet-soft/cyan-soft/emerald-soft`), shadow system (`--shadow-panel/glow/glow-strong/card-hover`), radius tokens (`--radius-xs` 0.75rem → `--radius-lg` 2rem), transition tokens (`--transition-fast/base`)
- **Brand gradient** updated to violet→cyan→emerald (previously cyan→emerald only)
- **Glass-dark `.card`** treatment: `radial-gradient` highlight at top + dark fill + 1.5rem radius + `--shadow-panel`; hover lifts to `--shadow-card-hover`
- **`.dashboard-panel`** hero variant: atmospheric cyan/violet glow, 2rem radius, stronger border
- **`.btn-primary`** now uses gradient fill + `--shadow-glow`; dark text for contrast
- **Pill classes** (`.pill`, `.pill-cyan/emerald/violet/loss/warning/dim`) — base for `StatusPill`
- **72px violet atmospheric grid** — replaces 24px white grid; fades at edges
- **Tailwind extensions**: `font-heading` (Syne), `borderRadius.panel` (1.5rem) / `hero` (2rem), `boxShadow.panel/glow/glow-strong/card-hover`, `animate-fade-up` keyframe
- **App shell** (`App.tsx`): sticky blurred nav (`backdrop-blur: 16px`, `rgba(6,6,10,0.80)`), `border-terminal-border-strong`, pill active state (`bg-cyan/10 text-cyan border-cyan/25`) replacing `border-b-2` underline
- **`prefers-reduced-motion`** respected globally

**Four new shared primitives** (drop-in replacements for ad-hoc card/badge/heading markup):

| Component | Props | Notes |
|-----------|-------|-------|
| `Panel` | `children`, `hero?`, `className?` | Glass-dark surface (1.5rem radius) or hero (atmospheric glow, 2rem) |
| `MetricCard` | `label`, `value`, `subtitle?`, `delta?`, `deltaColor?` | Syne bold value, mono label, optional delta chip |
| `StatusPill` | `label`, `variant?`, `dot?` | `live/active/draft/alert/warning/dim` variants |
| `SectionHeader` | `eyebrow?`, `title`, `subtitle?` | Syne title + mono uppercase eyebrow |

Next: continue migrating the 12-page surface to use these primitives in place of ad-hoc markup.

### Deployment (delivered)

See `docs/DEPLOYMENT.md` §13 — the dashboard app stays internal-only on the Compose network while nginx serves the canonical HTTPS domain `https://zeninvest.zenouz.ai`. Activity feed (SSE) uses relative URL. CORS origins are configurable via `dashboard.cors_origins` in `config/settings.yaml`. Authentication is session-based for operator routes, with explicit anonymous read-only routes under `/api/public/*`.

### Stabilisation (done)

All test failures fixed, frontend-backend type alignment complete, API URLs corrected, trigger endpoint implemented. See [Known Issues and Fixes](#known-issues-and-fixes) below.

---

## Architecture

### Overview Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              React Frontend (Vite) — 12 pages                                                   │
│  ┌─────────┬─────────┬─────────┬───────────┬───────────┬──────────┬─────────┬────────┬────────┬────────┬─────────┬──────────┐ │
│  │ Home    │ Universe│ Run Hist│ Portfolio │ Opportunity│ Insights │ Order   │ Commands│ World  │ Costs  │ Roadmap │ Evolution │ │
│  │ (state) │         │         │           │ Pipeline  │          │ Mgmt    │         │ News   │        │ & Arch  │ Planner   │ │
│  └─────────┴─────────┴─────────┴───────────┴───────────┴──────────┴─────────┴────────┴────────┴────────┴─────────┴──────────┘ │
│       Recharts / TanStack Table / ZENOUZ.ai brand (dark #06060a, violet→cyan→emerald)    │
└──────────────────┬──────────────────────────────────────────────────────────┘
                    │ REST + Server-Sent Events (SSE)
┌──────────────────┴──────────────────────────────────┐
│            FastAPI Backend (Python)             │
│  ┌────────────┬──────────────┬─────────────────┐ │
│  │  REST API  │  SSE Stream  │  Background     │ │
│  │  Endpoints │  Real-time   │  Event Logger   │ │
│  └────────────┴──────────────┴─────────────────┘ │
│        SQLite (Agent DB + evolution planner tables) │
└──────────────────┬──────────────────────────────┘
                    │ reads from
┌──────────────────┴──────────────────────────────┐
│         Existing Investment Agent Core           │
│  Scheduler → Committee → Orders → Notifications  │
└─────────────────────────────────────────────────┘
```

### Tech Stack

| Layer     | Choice                   | Rationale                                                  |
|-----------|--------------------------|-------------------------------------------------------------|
| Frontend  | React + Vite + Tailwind  | Fast dev, component ecosystem, pairs with Recharts/D3. Hooks: `useSSE` (real-time events), `useAsyncData` (independent section loading with auto-refresh) |
| Backend   | FastAPI                  | Already Python stack, async-native, auto-generated API docs |
| Database  | SQLite (current) → Postgres (future) | Zero config for VPS, upgrade path when needed |
| Real-time | Server-Sent Events (SSE) | Simpler than WebSockets for one-way push updates            |
| Hosting   | Same Hetzner VPS         | Co-located with agent, nginx reverse proxy                  |

---

## Frontend Pages

### Page 1: Dashboard Home (Operations Hub)

**Alert banner (persistent, all pages):**
- AlertBanner component renders below navbar on every page
- Aggregates 5 alert sources independently: system state (CAUTIOUS/HALTED), SSE disconnect (after sustained outage), cost degradation, losing positions (>5% loss), unresolved failed orders (`/api/orders/health`)
- Severity-coded: red (critical), amber (warning). Dismissible per-alert, auto-refresh 30s

**Control bar:**
- System state badge: ACTIVE (green) / CAUTIOUS (amber) / HALTED (red) / PAUSED (cyan — distinct colour). When CAUTIOUS, "Reset Peak" button appears.
- SSE indicator: small coloured dot (green = stream open, amber = connecting/reconnecting, red = disconnected) — no longer a full KPI card
- Pause/Resume toggle button with confirmation modal for Pause
- Dry Run + Live Run buttons (Live requires confirmation)

**Top metrics bar (4 cards, merged from previous 5):**
- Card 1 — Cycle Timing: next countdown + last run time/status/cost (merged from 3 old cards)
- Card 2 — Portfolio Value: total + P&L + position count + cash
- Card 3 — Performance (30d): Sharpe, win rate, max drawdown, trade count (from `/api/performance/metrics`)
- Card 4 — This Month: runs, cost, P&L, new investigations (compact summary)

**Last cycle summary (always visible):**
- Full-width card showing cycle_id, timestamp, status, stocks screened, stocks reviewed, trades, rejections, duration
- When present in `summary_json.counts`, the home card also surfaces richer operator counts such as broker orders submitted, queued buys, and skipped buys
- Never collapsed — primary "what just happened" signal

**Two-column layout:**
- Left (wider): Positions snapshot (top 5 by |P&L| with inline bar chart, "View all" link to Portfolio) + Recent Activity (always-visible SSE feed, last 100 events, `aria-live="polite"`)
- Right (320px): Cumulative stats (screened, investigated, uninvestigated, orders) + Cost breakdown (LLM/API/total with expandable daily table)

**Secondary sections (expandable):**
- Latest trades & LLM reasons: filterable table with expandable LLM output per row
- Run summaries (notification-style): full decisions and orders per cycle

**Data loading:**
- Each section loads independently via `useAsyncData` hook — one failing endpoint shows a section-level error + retry, not a full-page error
- 30s auto-refresh per section

### Page 2: Stock Universe Explorer

**Main table (from `instruments`):**
- Sortable columns: click any header to sort by that column (ticker, name, sector, industry, market cap, last screened, status, investigated, reviews, holding, sold, UOV ewma)
- Columns: ticker, name, sector, industry, market_cap tier, last_screened_at, data_available
- Colour-coded labels based on latest committee verdict (from most recent `strategy_decisions` + `risk_decisions`)
- Screening cooldown indicator (greyed out if within 72h window)
- `Sold` column: total number of shares sold per ticker based on executed **and dry-run** SELL orders, with the backend exposing a live vs dry-run split so the UI can highlight when Sold > 0 is driven entirely by hypothetical dry-run cycles.
- `Research` column: shows research activity as `latest cycle · total`. Example: `0 latest · 3 total` means the ticker has historical research on record, but the most recent strategy cycle did not use research for that ticker.

**Ticker detail panel (expand/drill-down):**
- Latest committee trail: Strategy decision → Moderation scores → Risk verdict → UOV score
- Execution summary: latest recorded BUY/SELL order activity for the ticker across all cycles (quantity, status, timestamp). This is intentionally broader than the latest strategy cycle so reviewers can see current order state even when the latest decision was HOLD or QUEUED.
- Historical decisions: timeline of all past evaluations for this ticker
- Research trail (Phase D, implemented): what each member searched for this ticker, key findings, cache hits, latency, cost — displayed in expandable `Agentic Research` block within the committee reasoning panel
- Scope semantics: expanded committee reasoning is scoped to the **latest strategy cycle** only. If the latest action is `HOLD` or `QUEUED`, moderation and risk are intentionally shown as `Not invoked` because the orchestrator short-circuits before those stages for non-actionable decisions.
- Company profile: business summary, sector, industry (from `instruments`)

**Filters:**
- Sector, market cap tier, label (buy/sell/hold/watch/queued), date range
- "Show only queued" — tickers in `opportunity_queue`
- "Show only active positions" — cross-reference with portfolio

### Page 3: Run History & Decision Explorer

**Timeline view:**
- Calendar/timeline of all cycles (from `runs`) — scheduled vs manual, duration, status
- One Run per cycle: scheduled cycles use a single Run (scheduler creates with `scheduled_YYYYMMDD_HHMMSS`, orchestrator updates on completion; no duplicate cycle_ vs scheduled_ entries)
- Visual indicator for cycles that triggered trades vs no-action cycles
- Click to expand a run

**Run detail view:**
- Stocks screened in this run (from `universe_updated` metadata when available)
- Stocks reviewed in this run (from `strategy_decisions` where cycle matches)
- For each stock: full pipeline waterfall

```
Strategy (Claude) → conviction 0.8, action BUY
  └─ Moderation (GPT-4o) → skeptic score 0.6, approved
  └─ Moderation (Gemini) → risk score 0.7, approved
  └─ Risk Manager → PASSED (no rules triggered)
  └─ UOV → uov_final 1.4, rank #2
  └─ Execution → market BUY 10 shares @ $187.42
  └─ Stop Loss → set at $178.05 (5% below entry)
```

- Research activity summary (Phase D): queries made, cache hits, cost
- Rejected stocks: which stage blocked and why; `rejected_by_action` breakdown (BUY, HOLD, QUEUED); for HOLD/QUEUED, moderation_consensus and risk_verdict show "not invoked"

**Run comparison:**
- Select two runs side by side
- Visual diff: which tickers changed verdict between runs and why

### Page 4: Portfolio & Performance

**Summary cards:** Cash Balance, Investments (`invested_gbp`), Positions count, Last Updated.

**Current positions (from `portfolio_snapshots.positions_json`; normalised from T212 `instrument.ticker` / `walletImpact`):**
- Table: ticker, sector, quantity, value (GBP), P&L (GBP), P&L % — **sortable** on desktop (click header; toggles asc/desc; numeric columns default to descending on first click). Mobile: “Sort by” dropdown (same ordering). Trend and Actions columns are not sort keys.
- Sector allocation pie chart (from position values; zero-value sectors filtered)
- Sector allocation tooltip uses explicit high-contrast text/background and GBP value formatting for dark-theme readability
- Portfolio value history line chart (chronological: oldest left, newest right; rightmost point = latest snapshot). The chart is anchored to the timestamp of the first recorded order, not the earliest portfolio snapshot. If no snapshot exists exactly at that first-order timestamp, the UI prepends a synthetic `£10,000` inception point there so the chart starts from the intended baseline. **Y-axis:** default *tight* scale (slightly below/above visible min–max); optional *wide context* (~£2k minimum span, legacy); optional *custom* min/max £ with Apply. **X-range:** Recharts brush under a full-series navigator — drag handles or band to focus dates; main chart and tight Y-axis follow the selected window; *Reset date range* restores the full range from the first-order anchor onward.

**Historical performance (from `performance_metrics`):**
- Portfolio value over time (line chart, daily)
- Rolling Sharpe ratio, Sortino ratio
- Drawdown chart with state transitions marked (CAUTIOUS/HALTED thresholds)
- Win rate by strategy type (momentum/mean_reversion/factor)
- Alpha vs benchmark (if tracked)

**Trade outcomes (from `trade_outcomes`):**
- Closed trade table: ticker, entry date/price, exit date/price, P&L, holding period, conviction at entry, moderator scores
- Scatter plot: conviction vs actual return (does higher conviction = better returns?)
- Performance attribution: which committee member's signals correlated with best/worst trades

### Page 5: UOV & Opportunity Pipeline

**Current opportunity queue (from `opportunity_queue`):**
- Columns: Ticker, UOV (z), UOV (EWMA), Queued cycles, **When queued** (created_at), **Why queued** (awaiting promotion / capacity gated / below immediate), **Action** (BUY), **When action taken** (promotion/expiry logic)
- Queue config (TTL, thresholds) from GET /api/opportunity/config/

**UOV score evolution (from `opportunity_score_snapshots`):**
- Per-ticker UOV components over time: raw, z-score, final, EWMA
- Heatmap: all tickers × last N cycles, coloured by UOV score
- Identify patterns: which tickers are trending up in UOV (building conviction across cycles)

### Page 6: Order Management & Stop Loss Audit

**Recent orders (from `orders`):**
- Table of all recent orders: time, ticker, action, quantity, order type, status (filled/pending/dry_run/failed)
- Market orders (BUY/SELL/REDUCE) and stop orders in one view
- Failed rows expose error details directly in the table (drill-down with full error message and broker order ID when available)
- Off-hours market/limit/stop orders can carry a `warning_note` explaining that the order was placed outside the regular US market session and may remain pending until the market opens
- Order-value floor behavior is visible in execution outcomes: BUY/REDUCE/limit/stop below £500 are skipped (for MARKET BUYs, floor check uses target trade value to avoid rounding dips), while explicit market SELL can still execute for full exits
- REDUCE decisions that would leave a residual position below £500 appear as executed SELL actions in the orders stream
- Status reflects reconciled T212 broker truth when live (FILLED→filled, PARTIALLY_FILLED→pending while a live remainder still exists, NEW→pending, REJECTED→failed, CANCELLED→cancelled)
- `pending` has two common meanings in this table:
  - market order accepted but not yet executed (`type=MARKET`, typically `status=NEW`, common outside market hours)
  - working protective stop (`type=STOP`, remains `NEW` until stop price is hit or order is cancelled/replaced)
- Local DB statuses are reconciled at the start of each non-dry-run cycle and refresh run via `sync_orders_with_t212()`, which updates market-order fill telemetry and keeps partial fills pending until the live remainder disappears.
- Dashboard health endpoint (`/api/orders/health`) also reconciles stale local pending stop orders against live T212 pending orders and reports local/live/stale counts. **Unresolved failed orders** are those with `status=failed` that still lack a later **filled** or **cancelled** row for the same `(ticker, action, order_type)`; a later **`dry_run` row does not** clear the alert (dry run does not fix a live broker failure).
- **Route ordering:** `GET /api/orders/health` must be declared *before* `GET /api/orders/{order_id}` in the orders router. If the parameterized route is registered first, requests to `/health` match `{order_id}` and FastAPI returns **422** (cannot coerce `"health"` to `int`).
- Status/system payloads also expose `halted_recovery_streak`, `halted_auto_recovery_target`, and `peak_inflation_warning_note` so the dashboard can surface hardening-state warnings without adding a separate alert subsystem.

**Current stop-loss levels (from `orders` + `stop_loss_adjustments`):**
- Current stop-loss levels for all positions with distance from current price
- Trailing stop tracking: high-water mark, current trail level, visualised on a mini price chart
- Limit dip-buy orders: pending limits with entry target vs current price

**Adjustment history:**
- Table: timestamp, ticker, adjustment_type (reassess/trail/limit), old_value, new_value, reason
- Chart: stop-loss level evolution vs price for a selected position

### Page 7: Research & Operator Audit

**Chat-first conversational console:**
- Shared session rail for dashboard-originated chat and Slack-originated threads continued in the browser
- Live thread view with mode chips (`Quick`, `Research`, `Committee`, `Trade`), explicit confirm/reject controls, recent action ledger, and conversational research trace
- Dashboard replies continue the same session and mirror back into Slack when the session originated in Slack
- Session spend card surfaces chat-triggered LLM and paid research cost so operator conversations can be measured independently from scheduled-cycle cost
- New **Agent Activity** rail shows safe workflow steps in real time: planning, ticker resolution, market-data fetch, grounded research, specialist calls, answer building, trade-preview drafting, and confirmation wait states
- Latest assistant turn exposes evidence panels for citations, related tickers, bull/bear/risk views, and suggested next actions instead of forcing operators to infer the system's work from a plain text block
- Degraded or partially resolved turns now render explicit warning cards instead of empty placeholder replies; empty evidence panels are hidden when no underlying evidence exists
- Slack thread commands are normalized before routing, so bullet/list-prefixed operator commands continue into `/commands` as deterministic previews instead of malformed research turns
- Plain `compare X and Y` prompts no longer auto-run peer scans; related tickers only appear when the operator explicitly asks for peers, adjacent names, or stronger alternatives
- Compare turns now support 2-3 explicit names, and `compare Amazon and Alphabet, then buy £20 of the stronger one` shows the comparison plus a pending preview for the selected winner instead of executing directly

**Secondary legacy audit:**
- `Legacy Slack Audit` tab remains backed by `GET /api/commands/` with ticker/action/status filters, stats cards, expandable rows, and a 30-second auto-refresh while the tab is open
- The tab now explicitly tells operators it is **not** the full conversation archive; the complete cross-channel session history lives in the conversational session rail instead
- Each row preserves the operator intent, confirmation state, force-override usage, cycle linkage, order linkage, and human-readable response message

**Operational value:**
- Confirms whether a manual request was blocked by moderation, vetoed by risk, waiting on confirmation, accepted by Trading 212, or failed downstream
- Keeps conversational/operator workflow evidence separate from autonomous scheduled-cycle evidence while retaining the older one-shot Slack command ledger

### Page 8: World News & Macro Regime

**Macro intelligence surface:**
- Dedicated `/world-news` page for `MacroState`, `MacroSignalLog`, and `MacroHeadline` data
- Hero regime card with confidence, top signals, and structured action-plan summary
- Expandable headline archive grouped by day with category filters (fed, rates, trade, earnings, inflation, jobs, gdp, market)
- Sector implications, opportunity/risk framing, and timeline view for macro-state changes

**Home-page tie-in:**
- Dashboard Home compact macro bar links back to the full World News view
- Makes the portfolio-level macro posture visible without opening the detailed page

### Page 9: Cost & API Monitoring

**Cost split: API vs LLM (daily and monthly):**
- Dashboard Home "This month" card: Runs, Cost (API/LLM split), Portfolio (start→end), P&L, New tickers investigated; collapsible daily cost table for last 7 days.
- Dashboard Home "Cumulative" card (separate): Screened, Investigated (with breakdown: 1×, 2×, 3+ reviews), Uninvestigated (with breakdown: enriched vs not enriched), Orders — lifetime stats.
- Costs page: daily chart stacks API (Brave/Tavily) + Agentic Research + LLM (Anthropic, OpenAI, Google); monthly table has API, Research, LLM, and per-provider columns
- API cost is estimated from `api_logs` call counts × published rates (Brave, Tavily); LLM cost from `cost_logs`; Research cost from `research_logs.cost_usd` (converted USD→GBP)
- Conversational session detail also exposes a session-scoped cost summary by aggregating `cost_logs.chat_session_id` and `research_logs.chat_session_id`, so `/commands` can show what a specific operator conversation consumed

**LLM costs (from `cost_logs`):**
- Daily spend by provider (Anthropic, OpenAI, Google) — bar/area chart
- Monthly cumulative vs £50 cap — progress bar
- Degradation history: when did the system drop from FULL to NO_GEMINI, etc.
- Cost per trade: total LLM cost ÷ trades executed

**API usage (from `api_logs`):**
- Calls per provider per day (T212, Finnhub, AV, brave_search, brave_answers, tavily)
- Error rates and latency percentiles
- Rate limit proximity warnings

**Research costs (Phase D, implemented — from `research_logs`):**
- Separate "Agentic Research" band in daily stacked area chart (purple #c084fc)
- "Research" column in monthly cumulative table
- Dedicated "Agentic Research Cost Breakdown" card: total calls, total cost (USD), cache hit rate, avg latency
- Breakdown by member (Strategy/Skeptic/Risk), by tool (web_search, news_search, etc.), by provider (Brave/Tavily/SEC)
- Data sourced from `/api/research/summary` (cost aggregation by member/tool/provider) and `/api/costs/daily` + `/api/costs/monthly` (research_cost_gbp field)

### Page 10: Roadmap & Architecture

**Tabbed layout:** `[Timeline | Roadmap | Architecture]` (default: Timeline; legacy `tab=gantt` URLs still open Timeline)

**Timeline tab:**
- Custom hybrid roadmap board: one section per work stream, with consistent card sizes for readability
- Columns: `Delivered`, `Pipeline`, `Future` (3-column layout for active clarity; Pipeline = committed work, Future = deferred backlog)
- Delivered stories show factual completion dates; planned stories show compact `1 day` / `2 days` timeboxes
- No Mermaid or fake date-width bars for future work

**Roadmap tab:**
- Project evolution from day 0 (2026-02-22) to now; days-in-development counter
- Summary cards: 29 delivered · 21 pipeline · ~58% complete
- Topic filter: All, Foundation, Calibration, Portfolio & Risk, Signals, Validation, Hardening, ML / Advanced, Open-Source / Community
- Larger milestone cards grouped by topic with clearer badges for status, priority, effort, and delivery/planning window
- Architecture components surfaced as chips for each story

**Architecture tab:**
- Custom staged system map with a top-level control plane and four readable execution stages:
  `Inputs & providers` → `Context & research` → `Decision committee` → `Execution & visibility`
- Larger cards explain the real runtime components, linked user stories, and responsibilities
- Links to `docs/ARCHITECTURE.md` and `docs/SOPHISTICATION_ROADMAP.md` served via `GET /api/docs/ARCHITECTURE` and `GET /api/docs/SOPHISTICATION_ROADMAP`

**Docs links:** In-app modal fetches and displays ARCHITECTURE.md and SOPHISTICATION_ROADMAP.md (avoids new-tab issues).

**URL:** `/roadmap`; optional `?tab=gantt`, `?tab=roadmap`, `?tab=architecture` for direct linking.

### Page 11: Evolution Planner

**Purpose:**
- Separate, authenticated operator workflow for policy-constrained software evolution (`US-1.10 Evolution Planner Phase 1`, with `US-1.11`–`US-1.14` remaining in pipeline)
- Accepts natural-language change requests and turns them into a structured plan, risk class, validation matrix, repo context, and auditable run history

**Current Phase 1 behavior:**
- Planner-only mode; no branch writes, no code edits, no deployment authority
- Clarification loop allows the operator to refine scope without losing audit history
- Build and deploy approvals are intentionally blocked and recorded as policy-gated attempts

**Displayed operator artifacts:**
- Conversation turns and latest scoped objective
- Touched areas, excluded areas, assumptions, and clarification questions
- Validation matrix selected from inferred scope
- Repo-context snapshots: key docs, likely code areas, roadmap references, and repo constraints
- Planning runs, artifacts, approvals, and later deployment records when later phases arrive

### Research Transparency (Integrated into Universe and Costs)

**Per-cycle research summary:**
- Total searches by member, cache hit rate, total cost
- Key findings that influenced decisions (tagged in `research_logs`)

**Per-ticker research trail:**
- Timeline: what each member searched for this ticker, what they found
- Research influence: did the research change the decision? (compare pre-research conviction if tracked)

**Research diversity metrics:**
- Query overlap between members (should be low — they have different mandates)
- Which member's research most often changed outcomes

---

## API Endpoints

The backend exposes the following endpoints. Most monitoring routes query the agent's existing SQLite tables directly; the Evolution Planner adds a separate workflow/audit domain for policy-constrained change planning.

### Activity & Runs

Runs fetched via `GET /api/runs/` or run-feed are **auto-reconciled**: any run stuck in "running" for >15 min with `strategy_decisions` is marked "completed" before returning. See `docs/DEPLOYMENT.md` §9.5.

```
GET /api/runs/                      # All runs, paginated, filterable by type/date
GET /api/runs/{run_id}              # Single run details
GET /api/runs/{run_id}/decisions    # Decisions for a specific run
POST /api/runs/trigger              # Trigger dry-run cycle
POST /api/runs/trigger-live         # Trigger live cycle (executes real trades)
POST /api/system/trigger-cycle      # Alias for dry-run trigger
```

Manual trigger protection: when a cycle is already active, the trigger endpoints now return `409` instead of spawning overlapping background work.

### Universe

```
GET /api/universe/                  # All instruments, paginated, filterable
GET /api/universe/{ticker}          # Single ticker details with latest decisions
```

### Portfolio

```
GET /api/portfolio/                 # Current portfolio snapshot
GET /api/portfolio/history          # Historical snapshots for charting
GET /api/portfolio/history-start    # Anchor timestamp for portfolio history chart
GET /api/public/portfolio           # Public read-only portfolio snapshot
GET /api/public/portfolio/history   # Public read-only portfolio history
GET /api/public/portfolio/history-start # Public read-only chart anchor timestamp
```

### Public Macro / World News

```
GET /api/public/macro/state         # Public read-only latest macro regime
GET /api/public/macro/state/history # Public read-only regime timeline
GET /api/public/macro/headlines     # Public read-only headline archive
GET /api/public/macro/summary       # Public read-only macro summary
```

### Orders

```
GET /api/orders/                    # All orders, paginated, filterable by status/date
```

### Committee Decisions

```
GET /api/decisions/                 # All decisions, paginated, filterable by ticker/cycle/action
GET /api/decisions/{cycle_id}       # All decisions for a specific cycle
GET /api/decisions/ticker/{ticker}  # Decision history for a ticker
```

### Moderation

```
GET /api/moderation/{cycle_id}      # Moderation logs for a cycle
GET /api/moderation/ticker/{ticker} # Moderation history for a ticker
```

### Risk

```
GET /api/risk/{cycle_id}            # Risk decisions for a cycle
```

### UOV & Opportunity

```
GET /api/opportunity/scores/        # Latest UOV scores, paginated
GET /api/opportunity/scores/{cycle_id} # Scores for a specific cycle
GET /api/opportunity/config/        # Queue TTL, thresholds (for display)
GET /api/opportunity/queue/         # Current opportunity queue
GET /api/opportunity/history/{ticker} # UOV score history for a ticker
```

### Trade Outcomes

```
GET /api/outcomes/                  # Closed trade outcomes, paginated
GET /api/outcomes/stats             # Aggregate stats (win rate, avg P&L, etc.)
```

### Stop Loss & Order Management

```
GET /api/stop-loss/current          # Current stop-loss levels for all positions
GET /api/stop-loss/adjustments      # Adjustment history, paginated
```

### Performance

```
GET /api/performance/metrics        # Latest performance metrics
GET /api/performance/history        # Historical metrics for charting
```

### Costs

```
GET /api/costs/daily                # Daily cost breakdown by provider
GET /api/costs/monthly              # Monthly cumulative
GET /api/costs/degradation          # Degradation state history
```

### Commands

```
GET /api/commands/                  # Slack trade command audit log
GET /api/commands/stats             # Aggregate command stats by status/action
```

### API Usage

```
GET /api/api-usage/daily            # API call counts and error rates
```

### Research (Phase D — implemented)

```
GET /api/research/logs              # Paginated logs (filter by cycle_id, member, ticker)
GET /api/research/ticker/{ticker}   # Research history for a ticker (all cycles)
GET /api/research/summary           # Aggregate stats: total calls, cache hit rate, by_member
```

Research data is also embedded in the `GET /api/universe/{ticker}` response inside `last_decision.research`, providing per-cycle research calls inline with strategy/moderation/risk data.

### System Control

```
GET /api/system/state               # Current system state (ACTIVE/CAUTIOUS/HALTED), paused flag
POST /api/system/pause              # Pause trading
POST /api/system/resume             # Resume trading
POST /api/system/reset-peak         # Reset peak to current, clear CAUTIOUS if incorrect
```

### Documentation (served as Markdown)

```
GET /api/docs/ARCHITECTURE          # docs/ARCHITECTURE.md
GET /api/docs/SOPHISTICATION_ROADMAP # docs/SOPHISTICATION_ROADMAP.md
GET /api/docs/ZEN_EVOLUTION_ENGINE  # docs/ZEN_EVOLUTION_ENGINE.md
```

### Conversational Trading

```
GET /api/chat/sessions              # List chat sessions
POST /api/chat/sessions             # Create chat session
GET /api/chat/sessions/{id}         # Session detail
GET /api/chat/sessions/{id}/turns   # Paginated turn history
GET /api/chat/sessions/{id}/actions # Action ledger
GET /api/chat/sessions/{id}/spend   # Session cost summary
POST /api/chat/sessions/{id}/turns  # Submit turn and get refreshed session
POST /api/chat/sessions/{id}/actions/{action_id}/confirm  # Confirm pending action (requires expected_version; 409 on stale action)
POST /api/chat/sessions/{id}/actions/{action_id}/reject   # Reject pending action (requires expected_version; 409 on stale action)
POST /api/chat/sessions/{id}/end    # End session
DELETE /api/chat/sessions/{id}      # Archive session
```

### Evolution Planner

```
GET /api/evolution/requests                     # List evolution requests
POST /api/evolution/requests                    # Create request from natural language
GET /api/evolution/requests/{id}                # Full request detail
GET /api/evolution/requests/{id}/plan           # Latest structured plan
POST /api/evolution/requests/{id}/messages      # Add clarification and replan
GET /api/evolution/requests/{id}/runs           # Planning run audit trail
GET /api/evolution/requests/{id}/artifacts      # Validation/repo-context artifacts
POST /api/evolution/requests/{id}/approve-build # Intentionally blocked in Phase 1, recorded as audit event
POST /api/evolution/requests/{id}/approve-deploy # Intentionally blocked in Phase 1, recorded as audit event
GET /api/evolution/requests/{id}/deployments    # Future deployment records (empty in Phase 1)
```

### Real-time Events

```
GET /api/events/stream              # Server-Sent Events (SSE) stream of activity
```

---

## Data Model

**Design approach:** Query the agent's existing SQLite database directly for monitoring/operations data, while storing the Evolution Planner's workflow state in dedicated tables in the same database file. Dashboard backend connects to the same `src/data/database.py` SQLite file used by the orchestrator.

### Core Table Mapping

| Dashboard View | Agent Table(s) | Notes |
|---|---|---|
| Activity Feed | `events_log` | Already populated by event logger ✅ |
| Run History | `runs` + `events_log` | Run metadata + per-run events ✅ |
| Stock Universe | `instruments` | Sector, industry, market_cap, business_summary, last_screened_at, data_available |
| Committee Decisions | `strategy_decisions` + `moderation_logs` + `risk_decisions` | Full pipeline trail per ticker per cycle |
| Portfolio | `portfolio_snapshots` + `orders` | Snapshots for history, orders for current state. `positions_json` stores **normalized** positions (ticker, quantity, value_gbp, pnl_gbp, pnl_pct) — orchestrator converts from T212 `instrument.ticker`, uses `walletImpact` when present, and falls back to account-level GBP scaling (`account_summary.investments.currentValue`) when per-position wallet fields are absent. Dashboard router supports both normalized and legacy T212 format for backward compatibility. |
| P&L / Trade Outcomes | `trade_outcomes` | Links BUY→SELL with P&L, conviction, moderator scores |
| UOV Scoring | `opportunity_score_snapshots` + `opportunity_queue` | Per-cycle UOV components, queue state |
| Order Management | `orders` + `stop_loss_adjustments` | Stop-loss audit trail, trailing stops, limit orders |
| Performance | `performance_metrics` | Sharpe, Sortino, drawdown, win rates, alpha |
| Cost Tracking | `cost_logs` | Per-provider per-call costs, degradation state |
| Notifications | `notification_logs` | Sent/failed/skipped/deduped attempts |
| API Usage | `api_logs` | External API call audit (T212, Finnhub, AV, brave_search, brave_answers, tavily) |
| Research (Phase D) | `research_logs` | Per-member research queries, cache hits, findings |
| Backtesting | `backtests/results/` (filesystem) | Walk-forward reports, promotion results |

### New Tables (Dashboard Only)

| Table | Purpose | Schema |
|-------|---------|--------|
| `events_log` | Real-time activity stream | `id`, `timestamp`, `event_type`, `source`, `message`, `metadata_json` |
| `runs` | Run metadata | `id`, `type` (scheduled\|manual), `started_at`, `completed_at`, `status`, `summary_json` |
| `evolution_requests` | Evolution Planner request header | Operator request text, status, objective, risk class, latest plan version, audit timestamps |
| `evolution_messages` | Clarification and conversation trail | Per-request operator/system turns |
| `evolution_plans` | Structured plan versions | Change spec, repo context, implementation steps, validation matrix, risk policy, phase capabilities |
| `evolution_runs` | Planning/build/deploy run records | Run kind, status, worker label, timestamps |
| `evolution_artifacts` | Persisted planner outputs | Validation matrices, repo-context snapshots, summaries, future build artifacts |
| `evolution_approvals` | Build/deploy approval audit trail | Approval type, status, requester, decider, notes, timestamps |
| `evolution_deployments` | Future deployment history | Environment, status, artifact, rollback metadata |

---

## Design Tokens

### Colour Palette (ZENOUZ.ai Brand)

See `/branding/BRAND.md` for the full brand guide.

| Token | Hex | Usage |
|-------|-----|-------|
| **Background** | `#06060a` | Main canvas (--bg-primary) |
| **Card** | `#0c0c14` | Card/panel surfaces (--bg-card) |
| **Elevated** | `#12121c` | Elevated surfaces (--bg-elevated) |
| **Positive** | `#00ffa3` | Positive P&L, bullish signals, emerald (--positive) |
| **Negative** | `#ff4466` | Negative P&L, bearish signals (--negative) |
| **Accent/Cyan** | `#00d4ff` | Key metrics, active states, links (--accent) |
| **Violet** | `#6332ff` | Secondary accent, hover states, category distinction |
| **Warning** | `#f7c948` | CAUTIOUS state, warnings (--warning) |

### Typography

- **Numbers/codes**: JetBrains Mono (400–500) — all data, timestamps, tickers
- **Hero headings**: Syne (600–700) — dashboard page titles, hero metrics
- **Section headings**: Outfit (500–700) — section titles, card headings
- **Body**: Outfit (300–400) — labels, descriptions, body text
- **Data labels/tags**: JetBrains Mono, 9–11px, uppercase, letter-spacing 2–4px

### Visual Style

- ZENOUZ.ai branded: Graph Theory Z logo + "ZENOUZ.ai" wordmark in nav
- Product hierarchy: company `ZENOUZ.ai`, product `ZenInvest`, authenticated dashboard home `ZenInvest Agent`
- Browser/app title format: `ZENOUZ.ai - ZenInvest`
- Shared per-page branded header: hybrid Concept 1+2 bold Z presented in a subtle glass panel, consistently across all tabs
- Dark background (#06060a) with subtle grid texture for depth
- Cyan→emerald gradient for active states, chart accents, progress indicators
- All numbers in monospace (JetBrains Mono)
- Dashboard aesthetic: modern financial intelligence platform

---

## Implementation Prompts

These are the Claude Code prompts used to build the dashboard. Revised prompts from PLAN_PATCH supersede the originals.

### Prompt 1: Extend Backend

```
Read Claude.md and README.md.

The dashboard backend exists at dashboard/backend/ with FastAPI, SSE events,
and basic routers for runs, universe, portfolio, orders, and events.

Extend the backend to expose the full agent data model for the frontend.
The frontend will query the agent's existing SQLite tables directly — do NOT
create duplicate tables.

Add the following routers:

1. routers/decisions.py — query strategy_decisions, moderation_logs,
   risk_decisions tables. Support filtering by cycle_id, ticker, action,
   date range. Include a "pipeline waterfall" endpoint that joins all three
   for a given ticker + cycle.

2. routers/opportunity.py — query opportunity_score_snapshots and
   opportunity_queue. Support UOV score history per ticker.

3. routers/outcomes.py — query trade_outcomes. Include aggregate stats
   endpoint (win rate, avg P&L, avg holding period, best/worst trades).

4. routers/stop_loss.py — query stop_loss_adjustments. Include current
   levels for all positions (join with orders table).

5. routers/performance.py — query performance_metrics. Support historical
   series for charting.

6. routers/costs.py — query cost_logs. Daily/monthly breakdowns by provider.
   Include degradation state from system_state table.

7. routers/system.py — GET system state, POST trigger cycle, POST pause,
   POST resume. These should call the existing orchestrator CLI logic
   programmatically (not shell out to subprocess).

All endpoints should support pagination (offset/limit), date range filtering,
and return Pydantic response models. Add proper OpenAPI descriptions.

The backend should connect to the agent's SQLite database (same file), NOT a
separate dashboard database. Use read-only sessions for query endpoints.

Update Claude.md and README.md.
```

### Prompt 2: Frontend MVP

```
Read Claude.md and README.md.

Create the React frontend for the investment agent dashboard at
dashboard/frontend/.

Design direction: ZENOUZ.ai brand (see /branding/BRAND.md). Dark theme with
Graph Theory Z logo. Outfit font for body/headings, JetBrains Mono for data.
Colour palette: dark background (#06060a), emerald (#00ffa3) for gains,
red (#ff4466) for losses, cyan (#00d4ff) for accent/active, violet (#6332ff)
for secondary accent. Cyan→emerald gradient for key metrics and active states.
Subtle grid texture on background for depth.

Build these pages:

1. Dashboard Home — system state badge, metrics bar (portfolio value,
   daily P&L, cost burn, degradation level), real-time activity feed via
   SSE, quick portfolio summary cards.

2. Stock Universe — searchable/sortable table from /api/universe with
   committee verdict labels, screening cooldown indicator. Click to
   expand ticker detail with full pipeline waterfall (strategy →
   moderation → risk → UOV → execution).

3. Run History — timeline of all cycles, click to drill into decisions,
   rejected stocks with rejection stage. Run comparison view.

4. Portfolio & Performance — positions table with P&L, sector allocation
   chart, historical portfolio value line chart, rolling Sharpe/drawdown,
   trade outcomes scatter (conviction vs return).

5. Opportunity Pipeline — UOV scores table, opportunity queue, UOV
   evolution heatmap per ticker over last N cycles.

6. Order Management — stop-loss levels, trailing stop visualisation,
   adjustment history timeline.

7. Costs — daily/monthly cost charts by provider, degradation history,
   API usage stats.

Use Recharts for charts, TanStack Table for data tables. Implement
loading states, error handling, responsive sidebar navigation.

Connect to FastAPI backend. Serve via Vite in dev, FastAPI static
files in production.

Update Claude.md and README.md.
```

### Prompt 3: Deployment

Setup deployment for the dashboard on the existing Hetzner VPS:

1. Create a docker-compose.yml that runs:
   - The FastAPI dashboard backend on port 8000
   - The Vite frontend build served by FastAPI

2. Configure nginx as a reverse proxy:
   - /api/* → FastAPI backend
   - /* → React frontend static files
   - /events/stream → SSE with proper proxy buffering disabled

3. ✅ Session-based operator authentication. Anonymous read-only content lives under `/api/public/*`; operator routes require backend login and a signed `HttpOnly` cookie. The SPA routes unauthenticated users to a sign-in screen and treats protected API `401/403` responses as a signed-out state.

4. Create a deploy.sh script that builds the frontend, copies to the backend static dir, and restarts services

5. Ensure the dashboard database file is in a persistent location with backup considerations (reuse agent SQLite path)

Update Claude.md and README.md with deployment instructions. Ensure the dashboard reads from the same SQLite file as the agent (symlink or shared path in Docker volume).

---

## Feature Roadmap

### Phase 1 — Core Dashboard (MVP)

- **Activity Feed**: Live log of all scheduled and manual run events (cycle start/end, stocks scanned, decisions made, orders placed)
- **Stock Universe View**: Table showing current universe with labels, sector, last review date, committee verdict, and signal summary
- **Run History**: Timeline/calendar view of all past runs with drill-down into each run's decisions
- **Portfolio Snapshot**: Current holdings, P&L, allocation by sector

**Status:** ✅ Complete

### Phase 2 — Analytics & Insights

- **Decision Explorer**: For each stock, show the full committee reasoning (Claude strategy, GPT-4o skeptic, Gemini risk score) across time
- **Performance Attribution**: Which committee member's signals led to best/worst trades
- **Sector Heatmap**: Visual sector performance overlay with your holdings highlighted
- **News & Sentiment Timeline**: Market news events mapped against your trading decisions

**Status:** ✅ Complete (Phase 1.5 Analytics Lite delivered)

### Phase 3 — ML & Advanced Features

- **Prediction Confidence Dashboard**: Display model confidence scores per stock, track prediction accuracy over time
- **Backtesting Module**: Run historical simulations with different committee configurations
- **Anomaly Detection**: Flag unusual portfolio risk concentrations or abnormal price movements
- **Custom Alerts Builder**: User-defined alert rules (e.g. "notify me if any position drops 5% intraday")

**Status:** 🔄 Backlog

### Phase 4 — Interactive Control

- **Manual Override Panel**: Trigger a manual review cycle from the dashboard
- **Strategy Tuning**: Adjust committee weights, risk thresholds, and sector preferences via UI
- **Slack Integration Mirror**: See Slack conversation history with the agent, send commands from dashboard

**Status:** 🔄 Backlog (overlaps with US-1.6)

### Phase D — Research Activity (Agentic Research, US-4.4)

When [Agentic Research](AGENTIC_RESEARCH.md) reaches full rollout: **Research Activity** panel showing per-cycle research summary (searches, cache hit rate, cost), per-ticker research trail, and research influence tracking. See `docs/AGENTIC_RESEARCH.md`.

**Status:** ✅ Delivered — Research trail embedded in Universe expanded rows (Agentic Research block: member, tool, query, results, cache hit, latency, cost). `Research` column in Universe table. `GET /api/research/ticker/{ticker}` endpoint for historical research per ticker.

---

## Known Issues and Fixes

All items listed here are **DONE** as of 2026-03-10.

### Test Failures (Dashboard Table Initialisation)

**Root cause:** Dashboard tables (`events_log`, `runs`) live in `dashboard.backend.app.database.Base` (separate from `src.data.models.Base`). The orchestrator/scheduler now insert into these tables via `log_event()`, but test fixtures only create agent tables → `OperationalError: no such table: events_log`.

**Failing tests fixed:**

| File | Test | Status |
|------|------|--------|
| `tests/test_notifications_integration.py` | `test_orchestrator_paused_emits_cycle_summary` | ✅ FIXED |
| `tests/test_notifications_integration.py` | `test_orchestrator_emits_instruction_and_summary` | ✅ FIXED |
| `tests/test_notifications_integration.py` | `test_execute_trade_emits_execution_notification` | ✅ FIXED |
| `tests/test_notifications_integration.py` | `test_scheduler_exception_emits_critical` | ✅ FIXED |
| `tests/test_execution.py` | `test_get_position_returns_empty_dict_on_404` | ✅ FIXED |

**Fix pattern:**

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

### Frontend-Backend Type Mismatches

**Fixed:** PortfolioSnapshot, Position, Order, and Run schemas updated to match actual backend Pydantic models.

| Schema | Changes |
|--------|---------|
| PortfolioSnapshot | Renamed `snapshot_date` → `timestamp`, `total_value` → `total_value_gbp`, `cash_balance` → `cash_gbp`, `positions_json` → `positions` (array), added `invested_gbp`, `pnl_gbp`, `pnl_pct`, `num_positions` |
| Position | Renamed `value` → `value_gbp`, `pnl` → `pnl_gbp`, added `sector` |
| Order | Added `timestamp`, `order_type`, `value_gbp`, `strategy`, `conviction` |
| Run | Added `dry_run` to allowed `run_type` values |

**Status:** ✅ All frontend types aligned; `npm run build` passes without TypeScript errors

### API Client URL Mismatches

**Fixed:**
- `/api/portfolio/` endpoint corrected (was `/api/portfolio/current`)
- `getByCycleId` endpoint URL corrected

**Status:** ✅ All API routes verified

### POST /api/runs/trigger Implementation

**Implemented:** Background daemon thread that runs `Orchestrator(dry_run=True).run_cycle()`. Returns `{"message": "Dry-run cycle triggered in background", "status": "started"}`.

**POST /api/runs/trigger-live:** Same pattern but `Orchestrator(dry_run=False)` — executes real trades. Dashboard Home has Dry Run and Live Run buttons; Live Run shows a confirmation dialog.

**Status:** ✅ Endpoints functional and tested

### Verification Results

- `poetry run pytest -v` — 721 tests collected; current backend verification is green ✅
- `cd dashboard/frontend && npm run build` — no TypeScript errors ✅
- `cd dashboard/frontend && npm test` — Vitest (SSE parser utilities) ✅
- `poetry run python -m src.orchestrator.main --dry-run` — produces stocks ✅
- Dashboard backend starts and endpoints return correct shapes ✅

---

## Design Notes

### Why Server-Sent Events (SSE) over WebSockets

The data flow is primarily server → client (push updates). SSE is simpler, works over HTTP/2, and plays nicely with nginx. WebSockets can be added later if two-way communication is needed.

### Authenticated SSE

Native browser **`EventSource` cannot reliably carry the operator session behavior we need across deployments**, so the dashboard frontend opens **`GET /api/events/stream`** with **`fetch()`**, includes credentials, parses `text/event-stream` incrementally, and reconnects with backoff. A protected-route `401/403` on the stream flips the SPA into signed-out mode (no reconnect spam). Nginx: keep `X-Accel-Buffering: no` on the stream response (already set in the FastAPI router).

### Why SQLite First

The VPS has 4GB RAM. SQLite is zero-overhead and perfectly adequate for single-user dashboard reads + agent writes. Upgrade path to Postgres when/if needed for concurrent writes or advanced queries.

### ML Extensibility

The `metadata_json` fields on events and any new tables are intentional — they allow storing arbitrary model outputs, feature vectors, or prediction scores without schema changes. This makes the dashboard future-proof for Phase 3 (ML features) and Phase D (Agentic Research).

### Ticker Format Convention

**API and database:** Use T212 format (`SYMBOL_COUNTRY_EQ`, e.g. `AAPL_US_EQ`, `BP._UK_EQ`) everywhere in the backend and in event metadata.

**Frontend:** May display a "clean" symbol (e.g. AAPL) for readability; conversion only in the UI layer. See CLAUDE.md "Ticker Format Gotcha".

### Non-blocking Event Logging

Dashboard event logging must **never** block or slow the pipeline. Use async or a background thread/queue; on failure, log and drop. Config flags `dashboard_enabled` and `dashboard_events_enabled` allow turning off event emission without code changes.

---

## Related Notes

- **CLAUDE.md** — Architecture rules, database models, configuration
- **README.md** — Quick commands including dashboard deployment
- **docs/DEPLOYMENT.md** §13 — Dashboard deployment checklist, Docker setup, VPS access
- **docs/ARCHITECTURE.md** — Data flow, pipeline stages, component interactions
- **docs/SOPHISTICATION_ROADMAP.md** — Feature backlog, user stories (US-1.7, US-1.8)
- **docs/GOVERNANCE.md** — Audit trail, control actions, kill switches
- **docs/AGENTIC_RESEARCH.md** — Research activity (Phase D dashboard) and implementation details
