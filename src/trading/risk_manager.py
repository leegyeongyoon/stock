"""Risk management for trading."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from src.config.settings import settings
from src.trading.portfolio import Portfolio
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RiskLimits:
    """Risk limit configuration."""

    max_position_size: float = 0.1  # Max 10% per position
    max_positions: int = 10  # Max concurrent positions
    max_daily_loss: float = 0.03  # Max 3% daily loss
    max_drawdown: float = 0.1  # Max 10% drawdown from peak
    min_cash_ratio: float = 0.1  # Keep at least 10% in cash


class RiskManager:
    """Manages trading risk and enforces limits."""

    def __init__(
        self,
        portfolio: Portfolio,
        limits: Optional[RiskLimits] = None,
    ):
        """
        Initialize risk manager.

        Args:
            portfolio: Portfolio to manage.
            limits: Risk limits. Uses defaults if not provided.
        """
        self.portfolio = portfolio
        self.limits = limits or RiskLimits()
        self.peak_value = portfolio.total_value
        self.daily_start_value = portfolio.total_value
        self.last_reset_date: Optional[date] = None

    def reset_daily(self) -> None:
        """Reset daily tracking (call at start of each trading day)."""
        today = date.today()
        if self.last_reset_date != today:
            self.daily_start_value = self.portfolio.total_value
            self.last_reset_date = today

    def update_peak(self) -> None:
        """Update peak portfolio value for drawdown calculation."""
        if self.portfolio.total_value > self.peak_value:
            self.peak_value = self.portfolio.total_value

    @property
    def current_drawdown(self) -> float:
        """Current drawdown from peak."""
        if self.peak_value == 0:
            return 0.0
        return (self.peak_value - self.portfolio.total_value) / self.peak_value

    @property
    def daily_pnl_rate(self) -> float:
        """Daily P&L rate."""
        if self.daily_start_value == 0:
            return 0.0
        return (self.portfolio.total_value - self.daily_start_value) / self.daily_start_value

    def can_open_position(
        self,
        position_value: int,
        code: str,
    ) -> tuple[bool, str]:
        """
        Check if a new position can be opened.

        Returns:
            Tuple of (allowed, reason).
        """
        # Check max positions
        if self.portfolio.position_count >= self.limits.max_positions:
            return False, f"Max positions ({self.limits.max_positions}) reached"

        # Check if already holding this stock
        if code in self.portfolio.positions:
            return False, f"Already holding {code}"

        # Check position size limit
        max_value = self.portfolio.total_value * self.limits.max_position_size
        if position_value > max_value:
            return False, f"Position size {position_value:,} exceeds limit {max_value:,.0f}"

        # Check cash availability
        if position_value > self.portfolio.cash:
            return False, f"Insufficient cash: {self.portfolio.cash:,} < {position_value:,}"

        # Check minimum cash ratio
        cash_after = self.portfolio.cash - position_value
        total_after = self.portfolio.total_value
        if cash_after / total_after < self.limits.min_cash_ratio:
            return False, f"Would violate min cash ratio ({self.limits.min_cash_ratio:.0%})"

        # Check daily loss limit
        if self.daily_pnl_rate <= -self.limits.max_daily_loss:
            return False, f"Daily loss limit ({self.limits.max_daily_loss:.0%}) reached"

        # Check max drawdown
        if self.current_drawdown >= self.limits.max_drawdown:
            return False, f"Max drawdown ({self.limits.max_drawdown:.0%}) reached"

        return True, "OK"

    def calculate_position_size(
        self,
        price: int,
        stop_loss: float = 0.02,
    ) -> int:
        """
        Calculate optimal position size based on risk.

        Args:
            price: Entry price per share.
            stop_loss: Stop loss percentage.

        Returns:
            Number of shares to buy.
        """
        # Max position value based on portfolio percentage
        max_position = self.portfolio.total_value * self.limits.max_position_size

        # Limit by available cash (leaving min cash ratio)
        available_cash = self.portfolio.cash * (1 - self.limits.min_cash_ratio)
        max_position = min(max_position, available_cash)

        # Calculate quantity
        quantity = int(max_position / price)

        return max(0, quantity)

    def should_force_close_all(self) -> tuple[bool, str]:
        """
        Check if all positions should be force closed.

        Returns:
            Tuple of (should_close, reason).
        """
        # Check daily loss limit
        if self.daily_pnl_rate <= -self.limits.max_daily_loss:
            return True, f"Daily loss limit reached: {self.daily_pnl_rate:.1%}"

        # Check max drawdown
        if self.current_drawdown >= self.limits.max_drawdown:
            return True, f"Max drawdown reached: {self.current_drawdown:.1%}"

        return False, ""

    def get_risk_status(self) -> dict:
        """Get current risk status summary."""
        return {
            "positions": self.portfolio.position_count,
            "max_positions": self.limits.max_positions,
            "cash_ratio": self.portfolio.cash_ratio,
            "min_cash_ratio": self.limits.min_cash_ratio,
            "daily_pnl": self.daily_pnl_rate,
            "max_daily_loss": self.limits.max_daily_loss,
            "current_drawdown": self.current_drawdown,
            "max_drawdown": self.limits.max_drawdown,
            "peak_value": self.peak_value,
            "can_trade": self.daily_pnl_rate > -self.limits.max_daily_loss
            and self.current_drawdown < self.limits.max_drawdown,
        }
