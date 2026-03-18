---
tags: [investment-agent, roadmap, planning, priorities]
status: active
last_updated: 2026-03-18
---

# Sophistication Roadmap

Prioritised backlog: 10 delivered, 22 in pipeline. Ordered by value × feasibility. Evidence-based — no technique adopted without literature review and clear expected impact.

## Design Principles

1. Measure before you build — collect live data first, only build what data justifies
2. Incremental, not revolutionary — each phase builds on previous, no big rewrites
3. POC compatibility — all enhancements integrate with existing pipeline
4. Evidence-based — no ML/RL without literature review
5. Personal quant experience first — insights and learning over institutional features

## Delivered (10)

| # | ID | Project | Notes |
|---|-----|---------|-------|
| 1 | US-1.1 | Performance Tracking | Sharpe, Sortino, drawdown, win rate by strategy, alpha |
| 2 | US-1.2 | Trade Outcome Tracker | BUY→SELL linkage, per-trade P&L, conviction linkage |
| 3 | US-1.3 | CLI Dashboard | `--dashboard`: portfolio, metrics, costs, positions |
| 4 | US-1.4 | Deploy POC to VPS | Docker, health check, first cycle logged |
| 5 | US-1.5 | Chat & Alerts | Slack + Email, 6 event types, fail-open, audit trail |
| 6 | US-1.7 | Dashboard & Visualisation | Full API + 8 pages, ZENOUZ.ai brand |
| 7 | US-1.8 | Dashboard VPS Deployment | Docker multi-stage, SPA fallback |
| 8 | US-3.4 | UOV Ranking & Queue | Cross-cycle EWMA, ranked BUY queue, swap suggestions |
| 9 | US-3.5 | Intelligent Order Management | ATR stops, trailing stops, limit dip-buy |
| 10 | US-5.1 | Backtesting Engine | Daily replay, paper broker, walk-forward, promotion report |

## Pipeline — Near Term (P0–P1)

| ID | Project | What's Needed | Priority |
|----|---------|---------------|----------|
| US-4.4 | Agentic Research | **Complete** — 5 tools, 3 members, 37 tests. Awaiting promotion to "Delivered" | P0 |
| US-4.5 | Proactive Macro News Intelligence | Scheduled macro scans, second-order reasoning | P1 |
| US-1.6 | Slack NL Trade Commands | Inbound: "Buy 10 AAPL" → full pipeline, Risk veto | P1 |
| US-1.9 | Conversational Trading Workflow | Multi-turn session chat, confirmation gate | P1 |
| US-2.1 | Conviction Calibration | Calibration curve, sized by calibrated confidence. Needs ~50 trades | P1 |
| US-2.2 | Dynamic Strategy Weighting | Rolling hit rate per sub-strategy, adaptive weights | P1 |
| US-7.1 | Dashboard Authentication | API key/token auth — **critical** before exposing beyond localhost | P1 |
| US-7.3 | Execution Quality & Slippage | VWAP/TWAP, slippage tracking — **pre-live prerequisite** | P1 |

## Pipeline — Medium Term (P2)

| ID | Project | Priority |
|----|---------|----------|
| US-3.1 | Risk-Parity Sizing | P1 |
| US-2.3 | Moderator Effectiveness | P2 |
| US-2.4 | Nemotron Integration Investigation | P2 |
| US-4.1 | Volume Signals (OBV) | P2 |
| US-5.2 | Parameter Sensitivity | P2 |
| US-3.2 | Regime Detection | P2 |
| US-3.3 | Correlation Screening | P2 |
| US-4.2 | Earnings Calendar | P2 |
| US-4.3 | Sector Rotation | P2 |

## Pipeline — Long Term (P3+)

| ID | Project | Gating |
|----|---------|--------|
| US-6.1 | ML Trade Scoring (XGBoost) | 500+ trades, literature review |
| US-6.2 | Journal Embeddings | "Have we seen this pattern before?" |
| US-6.3 | RL Investigation | Evidence-based decision gate |
| US-7.2 | Partial Fill Resubmission | Detect + resubmit unfilled |
| US-7.4 | Integration Test Coverage | End-to-end orchestrator test |

## What the POC Still Lacks

- Calibration of strategy weights and conviction using live + backtest evidence
- Portfolio-level optimisation (risk-parity sizing)
- Learning/adaptation (currently static parameters)

## Related Notes

- [[Project Overview]]
- [[Multi-LLM Pipeline Architecture]]
- [[Backtesting and Validation]]
