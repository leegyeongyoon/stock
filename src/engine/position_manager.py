"""Position tracking and P&L calculation for live trading."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger


@dataclass
class LivePosition:
    """A live trading position."""
    stock_code: str
    stock_name: str
    strategy_name: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    stop_loss_pct: float = 0.03      # 3%
    take_profit_pct: float = 0.05    # 5%
    entry_time: datetime = field(default_factory=datetime.now)
    order_id: str = ""

    @property
    def stop_loss_price(self) -> float:
        return self.avg_price * (1 - self.stop_loss_pct)

    @property
    def take_profit_price(self) -> float:
        return self.avg_price * (1 + self.take_profit_pct)

    @property
    def market_value(self) -> float:
        return self.current_price * self.quantity

    @property
    def cost_basis(self) -> float:
        return self.avg_price * self.quantity

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_price == 0:
            return 0.0
        return (self.current_price / self.avg_price - 1) * 100

    @property
    def should_stop_loss(self) -> bool:
        return self.current_price > 0 and self.current_price <= self.stop_loss_price

    @property
    def should_take_profit(self) -> bool:
        return self.current_price > 0 and self.current_price >= self.take_profit_price


@dataclass
class ClosedTrade:
    """A completed (closed) trade record."""
    stock_code: str
    stock_name: str
    strategy_name: str
    side: str               # "BUY"
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    exit_reason: str        # "SL", "TP", "CLOSE", "MANUAL"
    order_id: str = ""


class PositionManager:
    """Tracks all live positions and completed trades."""

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self._positions: dict[str, LivePosition] = {}
        self._trades: list[ClosedTrade] = []
        self._daily_pnl: float = 0.0

    # ── Commission constants ──────────────────────────────
    COMMISSION_RATE = 0.00015   # 0.015%
    TAX_RATE = 0.0023           # 0.23% (매도세)

    @property
    def positions(self) -> dict[str, LivePosition]:
        return dict(self._positions)

    @property
    def position_count(self) -> int:
        return len(self._positions)

    @property
    def trades_today(self) -> list[ClosedTrade]:
        return list(self._trades)

    @property
    def total_equity(self) -> float:
        holdings = sum(p.market_value for p in self._positions.values())
        return self.cash + holdings

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.initial_capital

    @property
    def total_pnl_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return (self.total_equity / self.initial_capital - 1) * 100

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def win_rate(self) -> float:
        if not self._trades:
            return 0.0
        wins = sum(1 for t in self._trades if t.pnl > 0)
        return wins / len(self._trades) * 100

    def has_position(self, code: str) -> bool:
        return code in self._positions

    def get_position(self, code: str) -> Optional[LivePosition]:
        return self._positions.get(code)

    def get_held_codes(self) -> set[str]:
        return set(self._positions.keys())

    def open_position(
        self,
        stock_code: str,
        stock_name: str,
        strategy_name: str,
        quantity: int,
        price: float,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.05,
        order_id: str = "",
    ) -> LivePosition:
        """Record a new position entry."""
        cost = price * quantity
        commission = cost * self.COMMISSION_RATE
        self.cash -= (cost + commission)

        pos = LivePosition(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=strategy_name,
            quantity=quantity,
            avg_price=price,
            current_price=price,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            entry_time=datetime.now(),
            order_id=order_id,
        )
        self._positions[stock_code] = pos

        logger.info(
            f"포지션 진입: {stock_code} {quantity}주 @{price:,.0f} "
            f"SL={pos.stop_loss_price:,.0f} TP={pos.take_profit_price:,.0f} "
            f"[{strategy_name}]"
        )
        return pos

    def close_position(
        self, code: str, exit_price: float, exit_reason: str
    ) -> Optional[ClosedTrade]:
        """Close a position and record the trade."""
        pos = self._positions.pop(code, None)
        if not pos:
            return None

        proceeds = exit_price * pos.quantity
        commission = proceeds * self.COMMISSION_RATE
        tax = proceeds * self.TAX_RATE
        self.cash += (proceeds - commission - tax)

        pnl = (exit_price - pos.avg_price) * pos.quantity - commission - tax
        entry_cost = pos.avg_price * pos.quantity
        pnl_pct = pnl / entry_cost * 100 if entry_cost > 0 else 0.0

        trade = ClosedTrade(
            stock_code=code,
            stock_name=pos.stock_name,
            strategy_name=pos.strategy_name,
            side="BUY",
            quantity=pos.quantity,
            entry_price=pos.avg_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=datetime.now(),
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            order_id=pos.order_id,
        )
        self._trades.append(trade)
        self._daily_pnl += pnl

        emoji = "+" if pnl > 0 else ""
        logger.info(
            f"포지션 청산: {code} @{exit_price:,.0f} "
            f"PnL={emoji}{pnl:,.0f} ({emoji}{pnl_pct:.2f}%) "
            f"사유={exit_reason} [{pos.strategy_name}]"
        )
        return trade

    def update_price(self, code: str, price: float) -> None:
        """Update current price for a position."""
        pos = self._positions.get(code)
        if pos:
            pos.current_price = price

    def update_prices(self, prices: dict[str, float]) -> None:
        """Batch update prices for all positions."""
        for code, price in prices.items():
            self.update_price(code, price)

    def reset_daily(self) -> None:
        """Reset daily counters for a new trading day."""
        self._daily_pnl = 0.0
        self._trades.clear()

    def get_summary(self) -> dict:
        return {
            "total_equity": self.total_equity,
            "cash": self.cash,
            "positions": self.position_count,
            "daily_pnl": self._daily_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "trades_today": len(self._trades),
            "win_rate": self.win_rate,
        }
