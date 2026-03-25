"""Risk agent — hard rules with VETO power. Never overridden by LLMs."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from src.data.database import get_session
from src.data.models import Order, RiskDecision
from src.utils.datetime_utils import ensure_utc_datetime
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("risk_manager")


@dataclass
class RuleResult:
    """Result of a single risk rule check."""
    rule_name: str
    passed: bool
    message: str
    adjusted_allocation: float | None = None


@dataclass
class RiskVerdict:
    """Overall risk verdict for a proposed trade."""
    verdict: str  # APPROVE, REJECT, RESIZE
    ticker: str
    proposed_action: str
    proposed_allocation_pct: float
    adjusted_allocation_pct: float | None
    rules_checked: list[str] = field(default_factory=list)
    triggered_rules: list[str] = field(default_factory=list)
    reasoning: str = ""


class RiskManager:
    """Portfolio risk manager with hard rules."""

    def __init__(self) -> None:
        self.settings = get_settings()

    # --- Individual Rule Checks (pure functions) ---

    def check_max_single_stock(
        self,
        ticker: str,
        proposed_pct: float,
        current_portfolio: dict[str, float],
    ) -> RuleResult:
        """No single stock > max_single_stock_pct of portfolio.

        Note: proposed_pct is the strategy's TARGET allocation (total desired %),
        not an incremental addition. The risk check compares the target directly
        against the max limit.
        """
        max_pct = self.settings.max_single_stock_pct
        total_pct = proposed_pct

        if total_pct > max_pct:
            return RuleResult(
                rule_name="max_single_stock",
                passed=False,
                message=f"{ticker} would be {total_pct:.1f}% of portfolio (max {max_pct}%)",
                adjusted_allocation=max_pct,
            )
        return RuleResult(
            rule_name="max_single_stock",
            passed=True,
            message=f"{ticker} at {total_pct:.1f}% within limit ({max_pct}%)",
        )

    def check_max_sector(
        self,
        ticker: str,
        sector: str,
        proposed_pct: float,
        sector_allocations: dict[str, float],
    ) -> RuleResult:
        """No single sector > max_sector_pct."""
        max_pct = self.settings.max_sector_pct
        current_sector_pct = sector_allocations.get(sector, 0.0)
        new_sector_pct = current_sector_pct + proposed_pct

        if new_sector_pct > max_pct:
            remaining = max(0, max_pct - current_sector_pct)
            return RuleResult(
                rule_name="max_sector",
                passed=False,
                message=f"Sector '{sector}' would be {new_sector_pct:.1f}% (max {max_pct}%). Only {remaining:.1f}% room.",
                adjusted_allocation=remaining if remaining > 0 else None,
            )
        return RuleResult(
            rule_name="max_sector",
            passed=True,
            message=f"Sector '{sector}' at {new_sector_pct:.1f}% within limit ({max_pct}%)",
        )

    def check_correlation(
        self,
        portfolio_returns: dict[str, list[float]],
    ) -> RuleResult:
        """Portfolio avg pairwise correlation < max_correlation."""
        max_corr = self.settings.max_correlation
        tickers = list(portfolio_returns.keys())

        if len(tickers) < 2:
            return RuleResult(
                rule_name="correlation",
                passed=True,
                message="Not enough positions to check correlation",
            )

        try:
            returns_matrix = np.array([portfolio_returns[t] for t in tickers])
            # Minimum length check
            min_len = min(len(r) for r in portfolio_returns.values())
            if min_len < 20:
                return RuleResult(
                    rule_name="correlation",
                    passed=True,
                    message="Insufficient return history for correlation check",
                )

            # Truncate to same length
            returns_matrix = np.array([r[:min_len] for r in portfolio_returns.values()])
            corr_matrix = np.corrcoef(returns_matrix)

            # Average pairwise correlation (upper triangle, excluding diagonal)
            n = len(tickers)
            pairwise_corrs = []
            for i in range(n):
                for j in range(i + 1, n):
                    pairwise_corrs.append(abs(corr_matrix[i, j]))

            avg_corr = float(np.mean(pairwise_corrs)) if pairwise_corrs else 0.0

            if avg_corr > max_corr:
                return RuleResult(
                    rule_name="correlation",
                    passed=False,
                    message=f"Avg pairwise correlation {avg_corr:.2f} exceeds limit ({max_corr})",
                )
            return RuleResult(
                rule_name="correlation",
                passed=True,
                message=f"Avg pairwise correlation {avg_corr:.2f} within limit ({max_corr})",
            )
        except Exception as e:
            logger.warning(f"Correlation check failed: {e}")
            return RuleResult(
                rule_name="correlation",
                passed=True,
                message=f"Correlation check error: {e} (allowing trade)",
            )

    def check_drawdown(
        self,
        current_value: float,
        peak_value: float,
    ) -> RuleResult:
        """Check drawdown thresholds. Returns state transition info."""
        if peak_value <= 0:
            return RuleResult(
                rule_name="drawdown",
                passed=True,
                message="No peak value recorded yet",
            )

        drawdown_pct = ((peak_value - current_value) / peak_value) * 100

        if drawdown_pct >= self.settings.halt_drawdown_pct:
            return RuleResult(
                rule_name="drawdown",
                passed=False,
                message=f"HALT: Drawdown {drawdown_pct:.1f}% exceeds {self.settings.halt_drawdown_pct}%! Liquidate all.",
            )
        elif drawdown_pct >= self.settings.cautious_drawdown_pct:
            return RuleResult(
                rule_name="drawdown",
                passed=True,  # passes but triggers CAUTIOUS
                message=f"CAUTIOUS: Drawdown {drawdown_pct:.1f}% exceeds {self.settings.cautious_drawdown_pct}%",
            )
        return RuleResult(
            rule_name="drawdown",
            passed=True,
            message=f"Drawdown {drawdown_pct:.1f}% within limits",
        )

    def get_drawdown_state(self, current_value: float, peak_value: float) -> str:
        """Get system state based on drawdown."""
        if peak_value <= 0:
            return "ACTIVE"

        drawdown_pct = ((peak_value - current_value) / peak_value) * 100

        if drawdown_pct >= self.settings.halt_drawdown_pct:
            return "HALTED"
        elif drawdown_pct >= self.settings.cautious_drawdown_pct:
            return "CAUTIOUS"
        return "ACTIVE"

    def check_vix_limit(
        self,
        vix: float | None,
        proposed_pct: float,
    ) -> RuleResult:
        """Apply VIX-based position limits."""
        if vix is None:
            return RuleResult(
                rule_name="vix_limit",
                passed=True,
                message="VIX data unavailable, skipping check",
            )

        if vix > self.settings.vix_extreme:
            max_pct = 5.0
            if proposed_pct > max_pct:
                return RuleResult(
                    rule_name="vix_limit",
                    passed=False,
                    message=f"VIX extreme ({vix:.1f}>{self.settings.vix_extreme}): max position {max_pct}%",
                    adjusted_allocation=max_pct,
                )
        elif vix > self.settings.vix_high:
            max_pct = 8.0
            if proposed_pct > max_pct:
                return RuleResult(
                    rule_name="vix_limit",
                    passed=False,
                    message=f"VIX high ({vix:.1f}>{self.settings.vix_high}): max position {max_pct}%",
                    adjusted_allocation=max_pct,
                )

        return RuleResult(
            rule_name="vix_limit",
            passed=True,
            message=f"VIX at {vix:.1f}, position size OK",
        )

    def check_daily_loss_halt(
        self,
        daily_pnl_pct: float,
        halt_until: datetime | None,
    ) -> RuleResult:
        """Check if daily loss halt is active."""
        max_loss = self.settings.daily_loss_halt_pct

        halt_until_utc = ensure_utc_datetime(halt_until)
        now_utc = datetime.now(timezone.utc)
        if halt_until_utc is not None and now_utc < halt_until_utc:
            return RuleResult(
                rule_name="daily_loss_halt",
                passed=False,
                message=f"Daily loss halt active until {halt_until_utc.isoformat()}",
            )

        if daily_pnl_pct < -max_loss:
            return RuleResult(
                rule_name="daily_loss_halt",
                passed=False,
                message=f"Daily loss {daily_pnl_pct:.1f}% exceeds limit (-{max_loss}%). No new buys for 24h.",
            )

        return RuleResult(
            rule_name="daily_loss_halt",
            passed=True,
            message=f"Daily P&L {daily_pnl_pct:+.1f}% within limits",
        )

    def check_cash_floor(
        self,
        cash_pct: float,
        trade_pct: float,
    ) -> RuleResult:
        """Ensure cash stays above minimum floor after trade."""
        min_cash = self.settings.cash_floor_pct
        projected_cash = cash_pct - trade_pct

        if projected_cash < min_cash:
            max_trade = max(0, cash_pct - min_cash)
            return RuleResult(
                rule_name="cash_floor",
                passed=False,
                message=f"Trade would leave cash at {projected_cash:.1f}% (min {min_cash}%). Max trade: {max_trade:.1f}%",
                adjusted_allocation=max_trade if max_trade > 0 else None,
            )
        return RuleResult(
            rule_name="cash_floor",
            passed=True,
            message=f"Post-trade cash {projected_cash:.1f}% above floor ({min_cash}%)",
        )

    def check_min_holding_period(
        self,
        ticker: str,
        action: str,
        current_portfolio: dict[str, float],
        sector: str,
        sector_allocations: dict[str, float],
    ) -> RuleResult:
        """Block REDUCE/SELL on positions held less than min_holding_hours unless risk limit exceeded."""
        if action not in ("SELL", "REDUCE"):
            return RuleResult(
                rule_name="min_holding_period",
                passed=True,
                message="Not a reduce/sell action",
            )

        min_hours = self.settings.min_holding_hours_before_reduce
        current_pct = current_portfolio.get(ticker, 0.0)
        sector_pct = sector_allocations.get(sector, 0.0)

        # Exempt: reducing because over max_single_stock or max_sector
        if current_pct > self.settings.max_single_stock_pct:
            return RuleResult(
                rule_name="min_holding_period",
                passed=True,
                message=f"Exempt: {ticker} at {current_pct:.1f}% exceeds max ({self.settings.max_single_stock_pct}%)",
            )
        if sector_pct > self.settings.max_sector_pct:
            return RuleResult(
                rule_name="min_holding_period",
                passed=True,
                message=f"Exempt: sector {sector} at {sector_pct:.1f}% exceeds max ({self.settings.max_sector_pct}%)",
            )

        session = get_session()
        try:
            last_buy = (
                session.query(Order)
                .filter(
                    Order.ticker == ticker,
                    Order.action == "BUY",
                    Order.status.in_(["filled", "dry_run"]),
                )
                .order_by(Order.timestamp.desc())
                .first()
            )
            if not last_buy:
                return RuleResult(
                    rule_name="min_holding_period",
                    passed=True,
                    message=f"No BUY history for {ticker}, allowing REDUCE/SELL",
                )
            last_buy_ts_utc = ensure_utc_datetime(last_buy.timestamp)
            now_utc = datetime.now(timezone.utc)
            # If the DB row has no timestamp (unexpected), allow the action.
            if last_buy_ts_utc is None:
                return RuleResult(
                    rule_name="min_holding_period",
                    passed=True,
                    message=f"No timestamp for last BUY of {ticker}, allowing REDUCE/SELL",
                )

            elapsed = (now_utc - last_buy_ts_utc).total_seconds() / 3600
            if elapsed >= min_hours:
                return RuleResult(
                    rule_name="min_holding_period",
                    passed=True,
                    message=f"Holding period {elapsed:.1f}h >= {min_hours}h for {ticker}",
                )
            return RuleResult(
                rule_name="min_holding_period",
                passed=False,
                message=f"min_holding_period: {ticker} held {elapsed:.1f}h < {min_hours}h",
            )
        finally:
            session.close()

    def check_min_positions(
        self,
        num_positions: int,
        action: str,
        conviction: int = 0,
        is_losing_position: bool = False,
    ) -> RuleResult:
        """Ensure minimum position count for diversification.

        Exemption (audit fix H-1): high-conviction SELL (>=80) on a losing position
        is allowed even at min_positions to exit crashing stocks.
        """
        min_pos = self.settings.min_positions

        if action == "SELL" and num_positions <= min_pos:
            # Allow risk-driven exits for losing positions with high conviction
            if conviction >= 80 and is_losing_position:
                return RuleResult(
                    rule_name="min_positions",
                    passed=True,
                    message=f"Risk-driven exit allowed: conviction {conviction}, losing position, "
                            f"{num_positions} positions (min {min_pos})",
                )
            return RuleResult(
                rule_name="min_positions",
                passed=False,
                message=f"Cannot sell: only {num_positions} positions (min {min_pos} required)",
            )
        return RuleResult(
            rule_name="min_positions",
            passed=True,
            message=f"Position count {num_positions} meets minimum ({min_pos})",
        )

    def check_cautious_state(
        self,
        state: str,
        action: str,
        proposed_pct: float,
        is_winner: bool = False,
    ) -> RuleResult:
        """Apply CAUTIOUS state restrictions."""
        if state != "CAUTIOUS":
            return RuleResult(
                rule_name="cautious_state",
                passed=True,
                message="System not in CAUTIOUS state",
            )

        if action == "BUY" and not is_winner:
            return RuleResult(
                rule_name="cautious_state",
                passed=False,
                message="CAUTIOUS: No new positions allowed, only add to winners",
            )

        max_cautious_pct = 8.0
        if proposed_pct > max_cautious_pct:
            return RuleResult(
                rule_name="cautious_state",
                passed=False,
                message=f"CAUTIOUS: Max position {max_cautious_pct}% (proposed {proposed_pct:.1f}%)",
                adjusted_allocation=max_cautious_pct,
            )

        return RuleResult(
            rule_name="cautious_state",
            passed=True,
            message=f"CAUTIOUS state check passed for {action}",
        )

    # --- Main evaluation ---

    def evaluate_trade(
        self,
        ticker: str,
        action: str,
        proposed_allocation_pct: float,
        sector: str,
        current_portfolio: dict[str, float],
        sector_allocations: dict[str, float],
        portfolio_returns: dict[str, list[float]],
        current_value: float,
        peak_value: float,
        cash_pct: float,
        vix: float | None,
        daily_pnl_pct: float,
        daily_loss_halt_until: datetime | None,
        num_positions: int,
        system_state: str,
        is_existing_winner: bool = False,
        cycle_id: str | None = None,
        conviction: int = 0,
        is_losing_position: bool = False,
        skip_min_holding_period: bool = False,
    ) -> RiskVerdict:
        """Run all risk checks on a proposed trade.

        Returns: RiskVerdict with APPROVE, REJECT, or RESIZE.
        """
        results: list[RuleResult] = []

        # Check system state first
        if system_state == "HALTED":
            verdict = RiskVerdict(
                verdict="REJECT",
                ticker=ticker,
                proposed_action=action,
                proposed_allocation_pct=proposed_allocation_pct,
                adjusted_allocation_pct=None,
                rules_checked=["system_halted"],
                triggered_rules=["system_halted"],
                reasoning="System is HALTED. All trading suspended.",
            )
            self._log_decision(verdict, cycle_id)
            return verdict

        # Run all checks
        if action in ("BUY", "HOLD"):
            results.append(self.check_max_single_stock(ticker, proposed_allocation_pct, current_portfolio))
            results.append(self.check_max_sector(ticker, sector, proposed_allocation_pct, sector_allocations))
            results.append(self.check_vix_limit(vix, proposed_allocation_pct))
            results.append(self.check_cash_floor(cash_pct, proposed_allocation_pct - current_portfolio.get(ticker, 0)))
            results.append(self.check_daily_loss_halt(daily_pnl_pct, daily_loss_halt_until))
            results.append(self.check_cautious_state(system_state, action, proposed_allocation_pct, is_existing_winner))

        results.append(self.check_drawdown(current_value, peak_value))
        results.append(self.check_correlation(portfolio_returns))

        if action in ("SELL", "REDUCE"):
            results.append(self.check_min_positions(
                num_positions, action, conviction=conviction, is_losing_position=is_losing_position,
            ))
            if skip_min_holding_period:
                results.append(
                    RuleResult(
                        rule_name="min_holding_period",
                        passed=True,
                        message="Bypassed minimum holding period for deterministic take-profit exit",
                    )
                )
            else:
                results.append(
                    self.check_min_holding_period(
                        ticker=ticker,
                        action=action,
                        current_portfolio=current_portfolio,
                        sector=sector,
                        sector_allocations=sector_allocations,
                    )
                )

        # Evaluate results
        rules_checked = [r.rule_name for r in results]
        triggered = [r for r in results if not r.passed]
        triggered_names = [r.rule_name for r in triggered]

        # Hard reject if drawdown halt triggered
        drawdown_result = next((r for r in results if r.rule_name == "drawdown" and "HALT" in r.message), None)
        if drawdown_result and not drawdown_result.passed:
            verdict = RiskVerdict(
                verdict="REJECT",
                ticker=ticker,
                proposed_action=action,
                proposed_allocation_pct=proposed_allocation_pct,
                adjusted_allocation_pct=None,
                rules_checked=rules_checked,
                triggered_rules=triggered_names,
                reasoning=drawdown_result.message,
            )
            self._log_decision(verdict, cycle_id)
            return verdict

        if not triggered:
            verdict = RiskVerdict(
                verdict="APPROVE",
                ticker=ticker,
                proposed_action=action,
                proposed_allocation_pct=proposed_allocation_pct,
                adjusted_allocation_pct=proposed_allocation_pct,
                rules_checked=rules_checked,
                triggered_rules=[],
                reasoning="All risk checks passed",
            )
            self._log_decision(verdict, cycle_id)
            return verdict

        # Check if any resizing is possible
        adjustments = [r.adjusted_allocation for r in triggered if r.adjusted_allocation is not None]

        if adjustments:
            min_adjusted = min(adjustments)
            if min_adjusted >= self.settings.min_position_pct:
                verdict = RiskVerdict(
                    verdict="RESIZE",
                    ticker=ticker,
                    proposed_action=action,
                    proposed_allocation_pct=proposed_allocation_pct,
                    adjusted_allocation_pct=min_adjusted,
                    rules_checked=rules_checked,
                    triggered_rules=triggered_names,
                    reasoning=f"Resized from {proposed_allocation_pct:.1f}% to {min_adjusted:.1f}%: " +
                              "; ".join(r.message for r in triggered),
                )
                self._log_decision(verdict, cycle_id)
                return verdict

        # Hard reject
        verdict = RiskVerdict(
            verdict="REJECT",
            ticker=ticker,
            proposed_action=action,
            proposed_allocation_pct=proposed_allocation_pct,
            adjusted_allocation_pct=None,
            rules_checked=rules_checked,
            triggered_rules=triggered_names,
            reasoning="; ".join(r.message for r in triggered),
        )
        self._log_decision(verdict, cycle_id)
        return verdict

    def _log_decision(self, verdict: RiskVerdict, cycle_id: str | None) -> None:
        """Log risk decision to database."""
        session = get_session()
        try:
            session.add(RiskDecision(
                timestamp=datetime.now(timezone.utc),
                cycle_id=cycle_id or "manual",
                ticker=verdict.ticker,
                proposed_action=verdict.proposed_action,
                proposed_allocation_pct=verdict.proposed_allocation_pct,
                verdict=verdict.verdict,
                adjusted_allocation_pct=verdict.adjusted_allocation_pct,
                rules_checked_json=json.dumps(verdict.rules_checked),
                triggered_rules_json=json.dumps(verdict.triggered_rules),
                reasoning=verdict.reasoning,
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to log risk decision: {e}")
            session.rollback()
        finally:
            session.close()
