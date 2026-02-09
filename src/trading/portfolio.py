"""Portfolio management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.config.constants import PositionStatus


@dataclass
class PortfolioPosition:
    """Represents a position in the portfolio."""

    code: str
    name: str
    quantity: int
    avg_price: int
    current_price: int
    entry_date: datetime
    strategy_name: str
    status: PositionStatus = PositionStatus.OPEN

    @property
    def market_value(self) -> int:
        """Current market value of position."""
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> int:
        """Total cost of position."""
        return self.quantity * self.avg_price

    @property
    def unrealized_pnl(self) -> int:
        """Unrealized profit/loss."""
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_rate(self) -> float:
        """Unrealized profit/loss rate."""
        if self.cost_basis == 0:
            return 0.0
        return self.unrealized_pnl / self.cost_basis


@dataclass
class Portfolio:
    """Portfolio tracking and management."""

    initial_capital: int
    cash: int
    positions: dict[str, PortfolioPosition] = field(default_factory=dict)
    realized_pnl: int = 0
    total_trades: int = 0

    @property
    def total_value(self) -> int:
        """Total portfolio value (cash + positions)."""
        positions_value = sum(p.market_value for p in self.positions.values())
        return self.cash + positions_value

    @property
    def unrealized_pnl(self) -> int:
        """Total unrealized P&L."""
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def total_pnl(self) -> int:
        """Total P&L (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def total_return(self) -> float:
        """Total return rate."""
        if self.initial_capital == 0:
            return 0.0
        return (self.total_value - self.initial_capital) / self.initial_capital

    @property
    def cash_ratio(self) -> float:
        """Cash ratio of portfolio."""
        if self.total_value == 0:
            return 1.0
        return self.cash / self.total_value

    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return len(self.positions)

    def add_position(
        self,
        code: str,
        name: str,
        quantity: int,
        price: int,
        strategy_name: str,
    ) -> Optional[PortfolioPosition]:
        """Add a new position or increase existing."""
        cost = quantity * price

        if cost > self.cash:
            return None

        if code in self.positions:
            # Average up/down existing position
            existing = self.positions[code]
            total_qty = existing.quantity + quantity
            total_cost = existing.cost_basis + cost
            new_avg = total_cost // total_qty

            existing.quantity = total_qty
            existing.avg_price = new_avg
            self.cash -= cost
            return existing
        else:
            # New position
            position = PortfolioPosition(
                code=code,
                name=name,
                quantity=quantity,
                avg_price=price,
                current_price=price,
                entry_date=datetime.now(),
                strategy_name=strategy_name,
            )
            self.positions[code] = position
            self.cash -= cost
            return position

    def close_position(
        self,
        code: str,
        price: int,
        quantity: Optional[int] = None,
    ) -> Optional[int]:
        """Close a position (fully or partially)."""
        if code not in self.positions:
            return None

        position = self.positions[code]
        close_qty = quantity or position.quantity

        if close_qty > position.quantity:
            close_qty = position.quantity

        # Calculate P&L
        proceeds = close_qty * price
        cost = close_qty * position.avg_price
        pnl = proceeds - cost

        self.cash += proceeds
        self.realized_pnl += pnl
        self.total_trades += 1

        if close_qty >= position.quantity:
            # Full close
            del self.positions[code]
        else:
            # Partial close
            position.quantity -= close_qty

        return pnl

    def update_prices(self, prices: dict[str, int]) -> None:
        """Update current prices for all positions."""
        for code, price in prices.items():
            if code in self.positions:
                self.positions[code].current_price = price

    def get_summary(self) -> dict:
        """Get portfolio summary."""
        return {
            "total_value": self.total_value,
            "cash": self.cash,
            "positions_value": sum(p.market_value for p in self.positions.values()),
            "position_count": self.position_count,
            "cash_ratio": self.cash_ratio,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "total_pnl": self.total_pnl,
            "total_return": self.total_return,
            "total_trades": self.total_trades,
        }
