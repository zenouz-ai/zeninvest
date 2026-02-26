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
         +--------+----------+----------+---------+
         |        |          |          |         |
      DATA    STRATEGY   MODERATION   RISK    EXECUTE
    yfinance   Momentum   GPT-4o     8 Hard   Trading
    Finnhub    Mean Rev.  Gemini     Rules     212 API
    Alpha V.   Factor     Consensus  VETO      + Journal
               Claude     3-way vote power
```

**Key Design Principle:** Defense-in-depth. Every trade must pass through strategy, moderation, AND risk — any layer can veto.

---

## Slide 4: Data Pipeline

| Source | Data | Rate Limit | Cost |
|--------|------|-----------|------|
| Yahoo Finance | OHLCV, fundamentals, earnings | Unlimited | Free |
| Finnhub | Analyst recommendations, insider sentiment | 60 req/min | Free |
| Alpha Vantage | AI-powered news sentiment | 25 req/day | Free |

**Technical Indicators Computed:**
RSI(14), MACD(12,26,9), Bollinger Bands(20,2), 50/200-day MA, ATR(14), Relative Strength vs S&P 500

**Fundamental Metrics:**
P/E, P/B, ROE, profit margins, D/E ratio, revenue growth, earnings momentum

---

## Slide 5: Three-Strategy Approach

| Strategy | Weight | Logic | Buy Signal |
|----------|--------|-------|------------|
| **Momentum** | 35% | Trend following | Above 50MA + RSI 50-70 + MACD bullish + RS > 1.0 |
| **Mean Reversion** | 30% | Buy oversold | RSI < 30 + below lower BB + sound fundamentals |
| **Factor/Quality** | 35% | Composite scoring | Value(30%) + Quality(30%) + Momentum(40%) |

**Claude Sonnet** synthesizes all three into final decisions with:
- Ticker, action, allocation %, conviction score (0-100)
- Catalysts, risks, exit conditions, expected holding period

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

---

## Slide 7: Risk Management (Hard Rules)

**8 rules with absolute VETO power — never overridden by LLMs:**

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
- Market orders with calculated quantities
- 5-minute deduplication window
- Rate limit monitoring

**Per-Trade Journal (Markdown):**
Every executed trade generates a comprehensive report including:
- Decision summary with conviction score
- Market context (regime, VIX, S&P trend)
- Strategy rationale with catalysts and risks
- Moderation panel review (all 3 verdicts)
- Risk agent decision (rules checked, triggered)
- Technical and fundamental snapshots
- Post-trade portfolio state

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
| Testing | pytest (104 tests) |

---

## Slide 11: Testing & Quality

**104 unit tests covering:**
- Risk manager: 43 tests (all 8 rules + integration)
- Strategy engine: 17 tests (momentum, mean reversion, factor, prompts)
- Moderation: 14 tests (consensus logic, panel integration)
- Execution: 14 tests (order management, dedup, portfolio state)
- Cost tracker: 16 tests (budgets, degradation, logging)

**Diagnostics Notebook:**
- 20-section Jupyter notebook testing each component independently
- Run before every deployment to verify all APIs and agents

---

## Slide 12: Audit Trail

**Everything is logged to SQLite:**

| Table | Purpose |
|-------|---------|
| `strategy_decisions` | Every Claude decision with reasoning |
| `moderation_logs` | Every moderator verdict with scores |
| `risk_decisions` | Every risk check with triggered rules |
| `orders` | Every order (executed, dry-run, failed) |
| `cost_logs` | Every LLM API call with token counts |
| `api_logs` | Every external API call with latency |
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

**Phase 2 — Enhanced Intelligence:**
- Backtesting engine with historical data replay
- Portfolio optimization (Markowitz / risk parity)
- Alternative data: earnings call transcripts, SEC filings
- Sector rotation strategy

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
| Components | 24 Python modules |
| Tests | 104 (all passing) |
| LLM Providers | 3 (Anthropic, OpenAI, Google) |
| Data Sources | 3 (yfinance, Finnhub, Alpha Vantage) |
| Risk Rules | 8 (hard, never overridden) |
| Strategies | 3 (Momentum, Mean Reversion, Factor) |
| Cost per cycle | ~£0.03-0.05 |
| Monthly cost | ~£2-3 estimated |
| State Machine | 3 states (ACTIVE, CAUTIOUS, HALTED) |

**An autonomous, cost-effective, multi-LLM investment system
with defense-in-depth safety and complete auditability.**
