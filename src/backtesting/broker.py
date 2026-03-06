"""Paper broker: simulated fills at next-open with slippage, cash and position tracking."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("backtesting.broker")


@dataclass
class Fill:
    """Single fill record."""
    timestamp: datetime
    ticker: str
    side: str  # BUY, SELL
    quantity: float
    price: float
    value: float
    slippage_bps: float
    cost_basis: float | None = None  # For SELL: cost of quantity sold (for PnL)


@dataclass
class Position:
    """Position in one ticker."""
    ticker: str
    quantity: float
    cost_basis: float  # total cost of position
    last_price: float


class PaperBroker:
    """Paper broker: tracks cash and positions; fills at next open with configurable slippage."""

    def __init__(
        self,
        initial_cash: float,
        slippage_bps: float = 10.0,
    ) -> None:
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.slippage_bps = slippage_bps
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self._pending_orders: list[dict[str, Any]] = []

    def position(self, ticker: str) -> Position | None:
        return self.positions.get(ticker)

    def position_value(self, ticker: str, price: float) -> float:
        pos = self.positions.get(ticker)
        if pos is None or pos.quantity <= 0:
            return 0.0
        return pos.quantity * price

    def total_equity(self, prices: dict[str, float]) -> float:
        """Total portfolio value (cash + positions at given prices)."""
        total = self.cash
        for ticker, pos in self.positions.items():
            if pos.quantity > 0 and ticker in prices:
                total += pos.quantity * prices[ticker]
        return total

    def submit_order(self, ticker: str, side: str, quantity: float, fill_date: datetime) -> None:
        """Queue order to be filled at next open (call process_fills with next day's bars)."""
        if quantity <= 0:
            return
        self._pending_orders.append({
            "ticker": ticker,
            "side": side.upper(),
            "quantity": quantity,
            "fill_date": fill_date,
        })

    def process_fills(self, date: datetime, open_prices: dict[str, float]) -> None:
        """Apply slippage to next-day open and execute pending orders."""
        for order in self._pending_orders:
            ticker = order["ticker"]
            side = order["side"]
            qty = order["quantity"]
            if ticker not in open_prices:
                continue
            open_price = open_prices[ticker]
            slippage = open_price * (self.slippage_bps / 10_000)
            if side == "BUY":
                fill_price = open_price + slippage
                cost = qty * fill_price
                if cost > self.cash:
                    continue
                self.cash -= cost
                if ticker in self.positions:
                    pos = self.positions[ticker]
                    total_qty = pos.quantity + qty
                    total_cost = pos.cost_basis + cost
                    self.positions[ticker] = Position(ticker=ticker, quantity=total_qty, cost_basis=total_cost, last_price=fill_price)
                else:
                    self.positions[ticker] = Position(ticker=ticker, quantity=qty, cost_basis=cost, last_price=fill_price)
                self.fills.append(Fill(
                    timestamp=date,
                    ticker=ticker,
                    side="BUY",
                    quantity=qty,
                    price=fill_price,
                    value=cost,
                    slippage_bps=self.slippage_bps,
                    cost_basis=None,
                ))
            else:
                fill_price = open_price - slippage
                pos = self.positions.get(ticker)
                if pos is None or pos.quantity <= 0:
                    continue
                sell_qty = min(qty, pos.quantity)
                value = sell_qty * fill_price
                cost_sold = pos.cost_basis * (sell_qty / pos.quantity) if pos.quantity else 0
                self.cash += value
                if pos.quantity - sell_qty <= 0:
                    del self.positions[ticker]
                else:
                    remaining_cost = pos.cost_basis * (1 - sell_qty / pos.quantity)
                    self.positions[ticker] = Position(
                        ticker=ticker,
                        quantity=pos.quantity - sell_qty,
                        cost_basis=remaining_cost,
                        last_price=fill_price,
                    )
                self.fills.append(Fill(
                    timestamp=date,
                    ticker=ticker,
                    side="SELL",
                    quantity=sell_qty,
                    price=fill_price,
                    value=value,
                    slippage_bps=self.slippage_bps,
                    cost_basis=cost_sold,
                ))
        self._pending_orders.clear()
