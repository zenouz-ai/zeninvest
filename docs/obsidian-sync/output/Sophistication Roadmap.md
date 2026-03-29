---
tags: [investment-agent, roadmap, planning, priorities]
status: active
last_updated: 2026-03-29
---

# Sophistication Roadmap

Prioritised backlog: 36 delivered, 15 in pipeline (71% progress). Ordered by value x feasibility. Evidence-based — no technique adopted without literature review and clear expected impact.

## Design Principles

1. Measure before you build — collect live data first, only build what data justifies
2. Incremental, not revolutionary — each phase builds on previous, no big rewrites
3. POC compatibility — all enhancements integrate with existing pipeline
4. Evidence-based — no ML/RL without literature review
5. Personal quant experience first — insights and learning over institutional features

## Delivered (36)

| # | ID | Project | Notes |
|---|-----|---------|-------|
| 1 | US-1.1 | Performance Tracking | Sharpe, Sortino, drawdown, win rate by strategy, alpha |
| 2 | US-1.2 | Trade Outcome Tracker | BUY→SELL linkage, per-trade P&L, conviction linkage |
| 3 | US-1.3 | CLI Dashboard | `--dashboard`: portfolio, metrics, costs, positions |
| 4 | US-1.4 | Deploy POC to VPS | Docker, health check, first cycle logged |
| 5 | US-1.5 | Chat & Alerts | Slack + Email, 6 event types, fail-open, audit trail |
| 6 | US-1.6 | Slack NL Trade Commands | Review, direct BUY/SELL, strategy-triggered, cancel; force override |
| 7 | US-1.7 | Dashboard & Visualisation | Full API + 11-page authenticated surface, ZENOUZ.ai brand |
| 8 | US-1.7.1–3 | Dashboard UX Phases 1–3 | AlertBanner, Force Sell, visual design system, Syne font, glass-dark panels |
| 9 | US-1.8 | Dashboard VPS Deployment | Docker multi-stage, SPA fallback |
| 10 | US-1.9 | Conversational Trading Workflow | Shared Slack/dashboard sessions, confirm/reject gating, audited ledgers |
| 11 | US-1.10 | Evolution Planner Phase 1 | Authenticated planner, clarification loop, validation matrix, risk classification |
| 12 | US-2.5 | Market Guidance Layer | Guidance snapshots, sector scores, screening tilt, per-cycle influence audit |
| 13 | US-2.6 | Strategy Episode Attribution | Git-backed episodes, cycle fingerprints, authenticated review |
| 14 | US-3.1 | Risk-Parity Sizing | Inverse-vol BUY overlay, vol floor, target-vol scaler |
| 15 | US-3.3 | Correlation-Aware Screening | Duplicate exposure flagging before BUY |
| 16 | US-3.4 | UOV Ranking & Queue | Cross-cycle EWMA, ranked BUY queue, swap suggestions |
| 17 | US-3.5 | Intelligent Order Management | ATR stops, trailing stops, limit dip-buy |
| 18 | US-3.6 | Active Swing Rotation | +15% take-profit SELLs, small-position cleanup |
| 19 | US-4.1 | Volume Signals | OBV + 20-day volume ratio in momentum/mean-reversion scoring |
| 20 | US-4.2 | Earnings Calendar | Earnings-date awareness across strategy/moderation/risk |
| 21 | US-4.4 | Agentic Research | 5 tools, 3 members, shared pipeline budget, 37 tests |
| 22 | US-4.5 | Proactive Macro Intelligence | Scheduled macro scans, regime derivation, action plan, 25 tests |
| 23 | US-1.7.4 | World News Dashboard Tab | Persistent headline archive, macro regime display, category filters |
| 24 | US-5.1 | Backtesting Engine | Daily replay, paper broker, walk-forward, promotion report |
| 25 | US-7.0 | Production Audit & Safety | 34 findings fixed (3C+6H+12M+13L) |
| 26 | US-7.0a | Agent Logic Audit | 27 findings, all Critical+High fixed, 36 tests |
| 27 | US-7.0b | Formal Verification | 18 findings, crash safety, state machine correctness, 18 tests |
| 28 | US-7.1 | Dashboard Authentication | Session-based auth, secure cookies, public/private route split |
| 29 | US-7.2 | Partial Fill Resubmission | Conservative BUY-only fill recovery |
| 30 | US-7.3 | Execution Quality & Slippage | Market-order telemetry, slippage rollups, threshold alerts |
| 31 | US-7.4 | Integration Test Coverage | End-to-end orchestrator harness, state machine tests |
| 32 | US-7.5 | Quick Hardening Slice | HALTED auto-recovery, off-hours annotations, peak inflation, DB CHECK |
| 33 | US-7.6 | VPS Runtime Stability | Single-instance locks, bounded execution, service isolation |
| 34 | US-7.7 | Dashboard HTTPS Domain | Canonical `zeninvest.zenouz.ai` via Cloudflare + nginx |
| 35 | US-7.8 | Safe Public Demo Dashboard | Sanitized public read models, preview-only private tabs |
| 36 | US-8.1 | Open-Source Launch Prep | In progress — MIT LICENSE, CONTRIBUTING, CI |

## Pipeline — Active Now

| ID | Project | What's Needed | Priority |
|----|---------|---------------|----------|
| US-8.1 | Open-Source Launch Prep | MIT LICENSE, CONTRIBUTING, CI (pytest + mypy) | P0 |
| US-1.11 | Branch-Based Evolution Runner | Isolated branch workspace, scoped edits, review-ready PRs | P1 |

## Pipeline — Data-Gated

| ID | Project | Gating |
|----|---------|--------|
| US-2.1 | Conviction Calibration | Needs ~50 trades |
| US-2.2 | Dynamic Strategy Weighting | Needs rolling hit rate data |
| US-2.3 | Moderator Effectiveness | Needs trade-outcome volume |

## Pipeline — Later / Optional

| ID | Project | Notes |
|----|---------|-------|
| US-1.12–1.14 | Evolution Phases 2–4 | Policy-gated promotion, auto-promotion, system-initiated improvements |
| US-2.4 | Nemotron Investigation | Cost/latency comparison |
| US-3.2 | Regime Detection | Continuous regime score |
| US-4.3 | Sector Rotation | GICS ETF momentum |
| US-5.2 | Parameter Sensitivity | Heat maps, robust ranges |
| US-6.1–6.3 | ML/Embeddings/RL | 500+ trades gate, literature review |

## What the POC Still Lacks

- Calibration of strategy weights and conviction using enough live + backtest evidence
- Learning/adaptation beyond the currently delivered deterministic sizing and signal stack
- Live-account posture change (execution quality telemetry now delivered; calibration data remains the gate)

## Related Notes

- [[Project Overview]]
- [[Multi-LLM Pipeline Architecture]]
- [[Backtesting and Validation]]
