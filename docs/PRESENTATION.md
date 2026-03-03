# Investment Agent — Project Presentation

## Slide 1: Title

**Autonomous Investment Agent**
Multi-LLM Strategy Pipeline with Trading 212 Integration

*An AI-powered investment system using Claude, GPT-4o, and Gemini
to autonomously analyze markets and execute trades.*

---

## Slide 2: Problem Statement

**Challenge:** Individual investors face information overload, emotional bias, and limited time to analyze markets systematically.

**Opportunity:** LLMs can process vast amounts of data, maintain consistency, and operate 24/7 — but a single model carries concentration risk.

**Solution:** A multi-LLM investment committee with hard safety guardrails, operating autonomously on a 12-hour cycle.

---

## Slide 3: System Architecture

```
                         ORCHESTRATOR
                    (Every 12h, Mon-Fri)
                             |
    +--------+--------+----------+----------+---------+---------+
    |        |        |          |          |         |         |
  DATA    UNIVERSE STRATEGY  MODERATION   RISK    EXECUTE   JOURNAL
 yfinance  Sector   Momentum  GPT-4o     Hard    Market     Per-trade
 Finnhub   balanced Mean Rev. Gemini     Rules   orders     markdown
 Alpha V.  Cap-tier Factor    Consensus  VETO    Stop-loss  reports
 Per-ticker 72h cool Claude   Challenges power   REDUCE
 news      -down    Synthesis assessment         Dedup
```

**Key Design Principle:** Defense-in-depth. Every trade must pass through strategy, moderation, AND risk — any layer can veto.

---

## Slide 4: Data Pipeline

| Source | Data | Rate Limit | Cost |
|--------|------|-----------|------|
| Yahoo Finance | OHLCV, fundamentals, earnings | Unlimited | Free |
| Finnhub | Analyst recommendations, insider sentiment | 60 req/min | Free |
| Alpha Vantage | AI-powered news sentiment (**per-ticker extraction**) | 25 req/day | Free |

**Per-Ticker News:** Alpha Vantage articles are parsed via `extract_per_ticker_news()` to build per-stock summaries with sentiment scores, bullish/bearish counts, and top headlines. Claude sees which news belongs to which stock.

**Technical Indicators Computed:**
RSI(14), MACD(12,26,9), Bollinger Bands(20,2), 50-day MA, Relative Strength vs S&P 500

**Fundamental Metrics:**
P/E, P/B, ROE, profit margins, D/E ratio, earnings growth, earnings momentum (QoQ)

---

## Slide 5: Three-Strategy Approach

| Strategy | Weight | Logic | Buy Signal |
|----------|--------|-------|------------|
| **Momentum** | 35% | Trend following | Above 50MA + RSI 50-70 + MACD bullish + RS > 1.0 |
| **Mean Reversion** | 30% | Buy oversold | RSI < 30 + below lower BB + sound fundamentals |
| **Factor/Quality** | 35% | Composite scoring | Value(30%) + Quality(30%) + Momentum(40%) |

**Claude Sonnet** synthesizes all three + per-ticker news + analyst data into final decisions with:
- Ticker, action (BUY/SELL/REDUCE/HOLD), allocation %, conviction score (0-100)
- Catalysts, risks, exit conditions, stop-loss %, expected holding period
- Market assessment thesis (passed to moderators for challenge)

---

## Slide 6: Multi-LLM Investment Committee

```
+------------------+     +------------------+     +------------------+
|  CLAUDE SONNET   |     |     GPT-4o       |     |  GEMINI FLASH    |
|  (Strategist)    |     |  (Skeptic)       |     | (Risk Assessor)  |
|                  |     |                  |     |                  |
| Proposes trades  |     | Challenges       |     | Scores growth,   |
| with conviction  |     | assumptions,     |     | risk, confidence |
| and rationale    |     | flags biases     |     | (1-10 each)      |
+--------+---------+     +--------+---------+     +--------+---------+
         |                         |                        |
         +----------+--------------+------------------------+
                    |
            CONSENSUS ENGINE
         3/3 agree -> APPROVED
         2/3 agree -> CAUTION
         2/3 disagree -> BLOCKED
```

**Why Multi-LLM?** Reduces single-model bias, catches blind spots, provides diverse perspectives on risk.

**New:** Moderators now receive Claude's `market_assessment` thesis and are explicitly prompted to challenge it, plus per-ticker news for each stock under review.

---

## Slide 7: Risk Management (Hard Rules)

**Hard rules with absolute VETO power — never overridden by LLMs:**

| Rule | Limit | Action |
|------|-------|--------|
| Max single stock | 15% | Resize or reject |
| Max sector | 35% | Resize or reject |
| Max correlation | 0.7 avg | Reject |
| Cautious drawdown | 5% | Reduce position sizes to 8% |
| Halt drawdown | 15% | **Liquidate ALL positions** |
| VIX high/extreme | 25/35 | Cap positions at 8%/5% |
| Daily loss halt | 2% | No new buys for 24h |
| Cash floor | 10% | Reject if insufficient |
| Min positions | 5 | Reject SELL/REDUCE if below |

**State Machine:** ACTIVE → CAUTIOUS → HALTED (automatic escalation, manual recovery)

---

## Slide 8: Cost Management

**Daily Budgets:**
- Anthropic (Claude Sonnet): £1.00/day
- OpenAI (GPT-4o): £0.75/day
- Google (Gemini Flash): £0.50/day
- **Monthly cap: £50.00**

**Graceful Degradation:**
```
FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED
```

**Estimated cost per cycle:** ~£0.03-0.05
**Cycles per day:** 2 (07:00 + 19:00 UTC)
**Monthly estimate:** ~£2-3 (well within budget)

---

## Slide 9: Execution & Journaling

**Trading 212 Integration:**
- Practice/Demo API (safe for testing)
- **Market orders:** BUY, SELL, REDUCE (partial sell) with calculated quantities
- **Stop-loss orders:** Automatically placed after BUY using Claude's `stop_loss_pct` (GTC)
- 5-minute deduplication window
- Rate limit monitoring

**Per-Trade Journal (Markdown):**
Every executed trade generates a comprehensive report including:
- Decision summary with conviction score and reasoning
- Company profile: industry, market cap, business description
- Market context (regime, VIX, S&P trend)
- Strategy rationale with catalysts and risks
- Moderation panel review (all 3 verdicts)
- Risk agent decision (rules checked, triggered)
- Technical and fundamental snapshots
- Post-trade portfolio state

**Rejected Stock Tracking:**
Stocks considered but not traded are recorded with the stage that blocked them (strategy HOLD, moderation BLOCKED, risk REJECT), including company metadata, conviction, and rejection reason — enabling future analysis of missed opportunities.

---

## Slide 10: Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Dependencies | Poetry |
| Database | SQLite (WAL mode) + SQLAlchemy + Alembic |
| Scheduling | APScheduler with persistent job store |
| HTTP | httpx with retry logic (tenacity) |
| Market Data | yfinance, Finnhub, Alpha Vantage |
| Technical Analysis | `ta` library |
| LLM SDKs | anthropic, openai, google-genai |
| Logging | Rich |
| CLI | Click |
| Containerization | Docker + Docker Compose |
| Testing | pytest (128 tests) |

---

## Slide 11: Testing & Quality

**128 unit tests covering:**
- Risk manager: 43 tests (all rules + state transitions + REDUCE check)
- Strategy engine: 17 tests (momentum, mean reversion, factor, prompts, synthesis)
- Moderation: 21 tests (consensus logic, panel integration, context formatting)
- Execution: 14 tests (order management, dedup, portfolio state)
- Cost tracker: 16 tests (budgets, degradation, logging)
- Screening + seed universe: 10 tests (cooldown, seed fallback, data availability filtering)
- Opportunity scoring + optimizer: 5 tests (UOV scoring, queue lifecycle, swap suggestions)

**Diagnostics Notebook:**
- 20-section Jupyter notebook testing each component independently
- Run before every deployment to verify all APIs and agents

---

## Slide 12: Audit Trail

**Everything is logged to SQLite:**

| Table | Purpose |
|-------|---------|
| `strategy_decisions` | Every Claude decision with reasoning, catalysts, risks |
| `moderation_logs` | Every moderator verdict with scores (BLOCKED decisions preserved) |
| `risk_decisions` | Every risk check with triggered rules (REJECTED decisions preserved) |
| `opportunity_score_snapshots` | Per-cycle UOV score components and final/ewma values |
| `opportunity_queue` | Active queued BUY opportunities with queued cycle count |
| `orders` | Every order (executed, dry-run, failed) |
| `cost_logs` | Every LLM API call with token counts |
| `api_logs` | Every external API call with latency |
| `instruments` | Company profiles: sector, industry, market_cap, business_summary |

**Cycle output includes executed trades, rejected stocks, opportunity ranking, queued candidates, and swap suggestions** for post-cycle analysis and controlled BUY prioritisation.
| `portfolio_snapshots` | Portfolio state after each cycle |
| `system_state` | State machine transitions |

---

## Slide 13: Deployment

**Local:** `poetry run python -m src.scheduler.scheduler`

**Docker:**
```bash
docker compose up -d
docker compose logs -f investment-agent
```

**VPS (Production):**
- Ubuntu 22.04, 2GB RAM, 1 vCPU
- Docker deployment with volume mounts
- systemd service with auto-restart
- Daily SQLite backups
- Log rotation

---

## Slide 14: Key Design Decisions

1. **Multi-LLM over Single LLM** — Reduces model-specific biases
2. **Hard rules over LLM risk assessment** — Deterministic safety bounds
3. **SQLite over PostgreSQL** — Simple, reliable, zero-config for single-instance
4. **Practice API first** — Safe development and testing before real capital
5. **Graceful degradation over hard failure** — System continues with reduced capability
6. **Per-trade journaling** — Complete audit trail for learning and accountability
7. **12-hour cycles over real-time** — Reduces costs, avoids overtrading
8. **Conviction thresholds** — Higher bar when fewer moderators available
9. **Universe screening over position-only analysis** — Discovers new opportunities via sector-balanced, cap-tiered sampling (70% large, 20% mid, 10% small) with 72-hour screening cooldown to ensure broad coverage
10. **Automatic stop-loss over manual protection** — GTC stop orders placed after every BUY using Claude's downside estimate
11. **Per-ticker news over combined dump** — Claude sees which articles belong to which stock, eliminating generic "no specific news" outputs

---

## Slide 15: Learnings

**What Worked:**
- Multi-LLM consensus significantly reduces bad trades
- Hard risk rules prevent catastrophic losses
- Cost tracking from day one prevents budget surprises
- Dry-run mode is invaluable for testing

**Challenges:**
- LLM JSON output is unreliable — needed JSON repair logic for Gemini
- Free API tiers are limiting — Alpha Vantage 25/day requires strategic batching
- yfinance deprecated endpoints (quarterly_earnings) — needed migration to income statements
- Finnhub premium endpoints (news, price targets) return 403 on free tier

---

## Slide 16: Future Roadmap

**Recently Completed:**
- ~~Universe screening~~ → Sector-balanced, cap-tiered candidate discovery
- ~~Screening cooldown~~ → 72-hour cooldown prevents re-screening same stocks, ensuring broader universe rotation
- ~~Per-ticker news extraction~~ → Claude sees stock-specific news, not combined dump
- ~~Stop-loss orders~~ → Auto-placed after BUY using Claude's stop_loss_pct
- ~~REDUCE action~~ → Partial sell support in order manager and risk agent
- ~~Strategy assessment to moderators~~ → GPT-4o and Gemini can challenge Claude's thesis
- ~~Curated seed universe~~ → ~160 well-known US equities, eliminates delisted noise
- ~~Company profiles~~ → Business summaries + industry from yfinance fed to Claude for qualitative reasoning
- ~~Enriched cycle output~~ → Trades include industry, market cap, description, reasoning
- ~~Rejected stock tracking~~ → Every non-traded stock recorded with stage, reason, and company metadata

**Phase 2 — Enhanced Intelligence:**
- Backtesting engine with historical data replay
- Portfolio optimization (Markowitz / risk parity)
- Alternative data: earnings call transcripts, SEC filings
- Regime-dependent strategy weighting (adjust 35/30/35 split based on market regime)
- Limit orders / take-profit orders using T212's existing API

**Phase 3 — Production Hardening:**
- Real-time alerting (Slack, email, PagerDuty)
- Human-in-the-loop for trades above £500
- Multi-account support
- Performance attribution analytics

**Phase 4 — Scale:**
- PostgreSQL migration for multi-instance
- Redis for caching and job queues
- API gateway for remote monitoring
- Mobile dashboard

---

## Slide 17: Summary

| Metric | Value |
|--------|-------|
| Components | 24+ Python modules |
| Tests | 123 (all passing) |
| LLM Providers | 3 (Anthropic, OpenAI, Google) |
| Data Sources | 3 (yfinance, Finnhub, Alpha Vantage) |
| Risk Rules | 9 (hard, never overridden by LLMs) |
| Strategies | 3 (Momentum, Mean Reversion, Factor) |
| Order Types | Market, stop-loss, REDUCE (partial sell) |
| Universe Screening | Sector-balanced, cap-tiered, 72h cooldown rotation |
| Cost per cycle | ~£0.03-0.05 |
| Monthly cost | ~£2-3 estimated |
| State Machine | 3 states (ACTIVE, CAUTIOUS, HALTED) |

**An autonomous, cost-effective, multi-LLM investment system
with defense-in-depth safety, universe discovery, and complete auditability.**
