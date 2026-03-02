# Competitive Analysis: Investment Agent vs Professional Quant Systems

**Last Updated:** 2026-02-28
**Purpose:** Honest assessment of where this system stands relative to institutional quant funds and leading AI trading research, to inform our sophistication roadmap.

---

## 1. Our Strengths (Ahead or On Par)

| Area | What We Have | Why It Matters |
|------|-------------|----------------|
| **Multi-LLM adversarial moderation** | Claude (strategy) + GPT-4o (skeptic) + Gemini (risk assessor) with consensus voting | Novel architecture. Even MarketSenseAI (leading academic LLM trading system) uses a single LLM. Our 3-way adversarial panel is a genuine innovation. |
| **Deterministic risk layer** | 9 hard rules with absolute VETO power, no LLM can override | Aligns with institutional practice. Separating risk from alpha is a core principle at AQR, Two Sigma, and similar firms. |
| **State machine (ACTIVE/CAUTIOUS/HALTED)** | Auto-reduction at 5% drawdown, auto-liquidation at 15% | Similar to institutional drawdown-triggered deleveraging. Simple but sound. |
| **Cost-aware degradation** | FULL → NO_GEMINI → NO_GPT4O → NO_STRATEGY → HALTED | Unique for retail. Professional firms have unlimited compute budgets; we've built graceful degradation for budget constraints. |
| **Clean modular architecture** | Agent pipeline with clear separation of concerns | Professional-grade software design. Easy to extend, test, and reason about. |
| **Comprehensive test suite** | 119 tests covering all critical components | Above average for retail algo projects. |
| **Sector-balanced universe screening** | Cap-tier sampling (70/20/10 large/mid/small), cooldown rotation, sector minimums | Prevents concentration bias in opportunity discovery. |
| **Defense-in-depth pipeline** | Strategy → Moderation → Risk → Execution, any layer can block | True institutional pattern — multiple independent checks. |

---

## 2. Where We're Behind

| Area | Our System | Professional Standard | Gap |
|------|-----------|----------------------|-----|
| **Data sources** | 4 free APIs (yfinance, Finnhub, Alpha Vantage, T212) | 50+ feeds (Bloomberg, FactSet, satellite, web traffic) | Critical |
| **Data frequency** | Daily OHLCV, 12-hour cycles | Tick-level to intraday, real-time | Significant |
| **Indicators** | 8 textbook signals (RSI, MACD, Bollinger, MA) | 100-1000+ signals, many ML-derived | Critical |
| **Backtesting** | None — zero evidence of edge | Continuous walk-forward validation | Critical |
| **Portfolio optimisation** | Rule-based vetoes, no joint optimisation | Markowitz, risk parity, convex optimisation | Major |
| **Execution** | Market orders only, no timing | VWAP/TWAP, smart routing, slippage modelling | Major |
| **Learning/adaptation** | Completely static | Online ML, reinforcement learning | Critical |
| **Alpha sources** | Commoditised textbook signals | Proprietary data, alternative data, ML features | Critical |
| **Cross-asset awareness** | Equities only | Multi-asset (equities, bonds, FX, commodities) | Major |
| **Factor model** | Fixed weights, hardcoded thresholds | Dynamic factor rotation, long-short hedging | Significant |
| **Regime detection** | 3 binary rules (VIX, SPY) | Continuous regime models, HMM, vol clustering | Significant |

---

## 3. Realistic Return Expectations (£10k, 1 Year)

### Key Assumptions
- Practice account on Trading 212 (no real slippage, but realistic pricing)
- LLM API costs: ~£500-750/year (5-7.5% drag on £10k)
- Bid-ask spread drag: ~1-2% annually
- No backtesting evidence of edge

### Scenario Analysis

| Scenario | Probability | Annual Return | Portfolio Value |
|----------|------------|---------------|-----------------|
| Strong outperformance | ~10% | +15% | £11,500 |
| Modest positive | ~30% | +7% | £10,700 |
| Break-even | ~30% | +1% | £10,100 |
| Underperformance | ~20% | -7% | £9,300 |
| Significant loss | ~10% | -15% | £8,500 |

**Expected value: +1% to +3% (£10,100-£10,300)** — approximately matching a savings account after costs. The primary value of the POC phase is data collection and system validation, not returns.

### What The Academic Research Says

- **MarketSenseAI 2.0** (2025): LLM-based stock analysis on S&P 100 achieved 125.9% cumulative return over 2 years vs 73.5% for the index. However, this used backtesting, not live trading.
- **FINSABER** (2025): LLM timing-based strategies show promise but are sensitive to regime changes and data contamination.
- **LLM + RL hybrids** (2025): Simply injecting LLM signals into trading agents can hurt performance. Only when combined with risk-aware frameworks (CVaR-PPO) do LLM signals consistently add value.

**Key takeaway:** LLMs can generate alpha, but only with proper risk management (which we have), calibration (which we need), and learning (which we'll build).

---

## 4. Our Path Forward

The system's biggest strength isn't its current alpha — it's the **infrastructure for systematic improvement**. We already log everything (StrategyDecision, ModerationLog, RiskDecision, CostLog, PortfolioSnapshot). After 250+ trading days, we'll have a dataset that most retail traders never build.

The gap between where we are now and a genuinely competitive system is narrower than it looks, because the hardest part — the plumbing — is already built.

### Priority Order for Improvement
1. **Measure** — close the feedback loop (track outcomes, compute Sharpe/Sortino)
2. **Calibrate** — tune strategy weights based on live performance data
3. **Optimise** — portfolio construction, position sizing
4. **Enhance** — better signals, regime adaptation, ML integration

See [SOPHISTICATION_ROADMAP.md](SOPHISTICATION_ROADMAP.md) for the detailed, prioritised plan.

---

## References

- MarketSenseAI 2.0: https://arxiv.org/html/2502.00415v2
- StockBench: https://arxiv.org/html/2510.02209v1
- FINSABER: https://arxiv.org/html/2505.07078v3
- LLM + RL in Equity Trading: https://arxiv.org/html/2508.02366v2
