"""3-Layer risk management for live trading."""

from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from src.engine.position_manager import PositionManager


@dataclass
class RiskCheck:
    """Result of a risk check."""
    allowed: bool
    reason: str = ""


class RiskManager:
    """3-Layer risk management system.

    Layer 1 (Pre-Trade): Check before placing orders
    Layer 2 (Post-Trade): Monitor positions after entry
    Layer 3 (Circuit Breaker): Emergency stop on daily loss limit
    """

    def __init__(
        self,
        position_mgr: PositionManager,
        max_position_pct: float = 0.10,     # 종목당 최대 10%
        max_positions: int = 10,
        max_daily_loss_pct: float = 0.03,   # 일일 최대 손실 -3%
        max_single_loss_pct: float = 0.05,  # 단일 종목 최대 손실 5%
    ):
        self.pm = position_mgr
        self.max_position_pct = max_position_pct
        self.max_positions = max_positions
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_single_loss_pct = max_single_loss_pct
        self._circuit_breaker_active = False
        self._circuit_breaker_time: datetime | None = None

    @property
    def is_circuit_breaker_active(self) -> bool:
        return self._circuit_breaker_active

    # ── Layer 1: Pre-Trade Checks ──────────────────────────

    def check_pre_trade(
        self,
        stock_code: str,
        order_value: float,
    ) -> RiskCheck:
        """Run all pre-trade risk checks before placing an order."""
        # Circuit breaker
        if self._circuit_breaker_active:
            return RiskCheck(False, "서킷브레이커 발동 - 매매 중단")

        # Max positions
        if self.pm.position_count >= self.max_positions:
            return RiskCheck(False, f"최대 포지션 수 초과 ({self.max_positions})")

        # Duplicate position
        if self.pm.has_position(stock_code):
            return RiskCheck(False, f"이미 보유 중: {stock_code}")

        # Position size limit
        equity = self.pm.total_equity
        if equity > 0 and order_value / equity > self.max_position_pct:
            return RiskCheck(
                False,
                f"종목 비중 초과: {order_value/equity:.1%} > {self.max_position_pct:.1%}"
            )

        # Sufficient cash
        if order_value > self.pm.cash:
            return RiskCheck(
                False,
                f"현금 부족: 필요 {order_value:,.0f} > 보유 {self.pm.cash:,.0f}"
            )

        return RiskCheck(True)

    # ── Layer 2: Post-Trade Monitoring ─────────────────────

    def check_stop_loss_tp(self) -> list[tuple[str, str]]:
        """Check all positions for SL/TP triggers.

        Returns list of (stock_code, reason) for positions that should close.
        """
        to_close = []
        for code, pos in self.pm.positions.items():
            if pos.should_stop_loss:
                to_close.append((code, "SL"))
            elif pos.should_take_profit:
                to_close.append((code, "TP"))
        return to_close

    # ── Layer 3: Circuit Breaker ───────────────────────────

    def check_circuit_breaker(self) -> bool:
        """Check if daily loss limit is breached. Returns True if tripped."""
        if self._circuit_breaker_active:
            return True

        if self.pm.initial_capital == 0:
            return False

        daily_loss_pct = self.pm.daily_pnl / self.pm.initial_capital
        if daily_loss_pct < -self.max_daily_loss_pct:
            self._circuit_breaker_active = True
            self._circuit_breaker_time = datetime.now()
            logger.critical(
                f"서킷브레이커 발동! 일일 손실 {daily_loss_pct:.2%} "
                f"(한도: -{self.max_daily_loss_pct:.1%})"
            )
            return True

        return False

    def reset_circuit_breaker(self) -> None:
        """Reset circuit breaker for a new trading day."""
        self._circuit_breaker_active = False
        self._circuit_breaker_time = None

    # ── Utility ────────────────────────────────────────────

    def calculate_position_size(
        self, price: float, stop_loss_pct: float = 0.03
    ) -> int:
        """Calculate position size respecting max position weight."""
        equity = self.pm.total_equity
        max_value = equity * self.max_position_pct
        max_qty = int(max_value / price) if price > 0 else 0
        return max_qty

    def get_risk_status(self) -> dict:
        return {
            "circuit_breaker": self._circuit_breaker_active,
            "positions": self.pm.position_count,
            "max_positions": self.max_positions,
            "daily_pnl": int(self.pm.daily_pnl),
            "daily_loss_limit": int(-self.pm.initial_capital * self.max_daily_loss_pct),
            "total_equity": int(self.pm.total_equity),
        }
