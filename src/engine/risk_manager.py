"""Multi-layer risk management for live trading.

Layer 1 (Pre-Trade): 주문 전 검증
Layer 2 (Post-Trade): 포지션 SL/TP 모니터링
Layer 3 (Circuit Breaker): 일일 손실 한도 (2%)
Layer 4 (SL Cooldown): SL 후 60분 쿨다운 + 포지션 축소
Layer 5 (Stock Cooldown): 종목별 재진입 차단 + 당일 2회 제한
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger

from src.engine.position_manager import PositionManager


@dataclass
class RiskCheck:
    """Result of a risk check."""
    allowed: bool
    reason: str = ""


class RiskManager:
    """Multi-layer risk management system.

    Layer 1 (Pre-Trade): Check before placing orders
    Layer 2 (Post-Trade): Monitor positions after entry
    Layer 3 (Circuit Breaker): Emergency stop on daily loss limit
    Layer 4 (SL Cooldown): SL 후 60분 쿨다운 + 연속SL 시 포지션 50% 축소
    Layer 5 (Stock Cooldown): Block re-entry after SL on same stock
    """

    # SL 후 쿨다운 시간 (분)
    SL_COOLDOWN_MINUTES = 60
    # 연속 N회 SL 후 포지션 크기 축소
    POSITION_REDUCE_AFTER = 2
    POSITION_REDUCE_SCALE = 0.5  # 50%로 축소

    def __init__(
        self,
        position_mgr: PositionManager,
        max_position_pct: float = 0.10,     # 종목당 최대 10%
        max_positions: int = 10,
        max_daily_loss_pct: float = 0.02,   # 일일 최대 손실 2%
        max_single_loss_pct: float = 0.05,  # 단일 종목 최대 손실 5%
    ):
        self.pm = position_mgr
        self.max_position_pct = max_position_pct
        self.max_positions = max_positions
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_single_loss_pct = max_single_loss_pct
        self._circuit_breaker_active = False
        self._circuit_breaker_time: datetime | None = None

        # Layer 4: SL 후 시간 쿨다운 (연속차단 대신)
        self._consecutive_losses = 0
        self._sl_cooldown_until: datetime | None = None  # SL 후 쿨다운 만료 시각

        # Layer 5: 종목 쿨다운
        self._stock_cooldown: dict[str, datetime] = {}  # SL 종목 → 당일 재진입 차단
        self._stock_entry_count: dict[str, int] = {}     # 종목별 당일 진입 횟수
        self._max_stock_entries = 2  # 같은 종목 당일 최대 2회 진입

    @property
    def is_circuit_breaker_active(self) -> bool:
        return self._circuit_breaker_active

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def position_scale(self) -> float:
        """연속SL에 따른 포지션 크기 배율 (1.0 = 100%, 0.5 = 50%)."""
        if self._consecutive_losses >= self.POSITION_REDUCE_AFTER:
            return self.POSITION_REDUCE_SCALE
        return 1.0

    def is_entry_paused(self) -> bool:
        """쿨다운 또는 서킷브레이커로 진입이 중단되었는지 확인."""
        if self._circuit_breaker_active:
            return True
        # SL 후 시간 쿨다운 체크
        if self._sl_cooldown_until and datetime.now() < self._sl_cooldown_until:
            return True
        return False

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

        # SL 후 시간 쿨다운
        if self._sl_cooldown_until and datetime.now() < self._sl_cooldown_until:
            remaining = (self._sl_cooldown_until - datetime.now()).seconds // 60
            return RiskCheck(
                False,
                f"SL 쿨다운 중 (잔여 {remaining}분)"
            )

        # Max positions
        if self.pm.position_count >= self.max_positions:
            return RiskCheck(False, f"최대 포지션 수 초과 ({self.max_positions})")

        # Duplicate position
        if self.pm.has_position(stock_code):
            return RiskCheck(False, f"이미 보유 중: {stock_code}")

        # 종목 쿨다운 (SL 후 당일 재진입 차단)
        if stock_code in self._stock_cooldown:
            return RiskCheck(
                False,
                f"종목 쿨다운 (SL 후 재진입 차단): {stock_code}"
            )

        # 같은 종목 당일 2회 이상 진입 금지
        if self._stock_entry_count.get(stock_code, 0) >= self._max_stock_entries:
            return RiskCheck(
                False,
                f"종목 당일 진입 한도 초과 ({self._max_stock_entries}회): {stock_code}"
            )

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

    # ── Layer 4: SL 쿨다운 + 포지션 축소 ─────────────────

    def record_trade_result(self, exit_reason: str, stock_code: str = "") -> None:
        """거래 결과 기록 - SL 후 시간 쿨다운 + 종목 쿨다운.

        SL 발생 시:
        - 60분 시간 쿨다운 (신규 진입 차단)
        - 해당 종목 당일 재진입 차단
        - 연속 2SL 이후 포지션 크기 50% 축소
        """
        if exit_reason in ("SL", "손절", "Stop loss"):
            self._consecutive_losses += 1
            # SL 후 60분 쿨다운
            self._sl_cooldown_until = (
                datetime.now() + timedelta(minutes=self.SL_COOLDOWN_MINUTES)
            )
            # 종목 쿨다운
            if stock_code:
                self._stock_cooldown[stock_code] = datetime.now()

            logger.warning(
                f"[리스크] SL 발생 → {self.SL_COOLDOWN_MINUTES}분 쿨다운 "
                f"(연속 {self._consecutive_losses}회, "
                f"포지션 배율 {self.position_scale:.0%})"
            )
        elif exit_reason in ("TP", "익절", "Take profit"):
            self._consecutive_losses = 0
            self._sl_cooldown_until = None  # TP 시 쿨다운 즉시 해제

        logger.info(
            f"[리스크] 거래결과: {exit_reason} "
            f"(연속SL: {self._consecutive_losses}, 배율: {self.position_scale:.0%})"
        )

    # ── Layer 5: 종목 쿨다운 ──────────────────────────────

    def record_entry(self, stock_code: str) -> None:
        """신규 진입 기록 - 종목별 당일 진입 횟수 추적."""
        self._stock_entry_count[stock_code] = (
            self._stock_entry_count.get(stock_code, 0) + 1
        )

    def is_stock_cooled_down(self, stock_code: str) -> bool:
        """종목이 쿨다운 중인지 확인."""
        if stock_code in self._stock_cooldown:
            return True
        if self._stock_entry_count.get(stock_code, 0) >= self._max_stock_entries:
            return True
        return False

    # ── Daily Reset ───────────────────────────────────────

    def reset_daily(self) -> None:
        """일일 리셋 - 새 거래일 시작 시 호출."""
        self._consecutive_losses = 0
        self._sl_cooldown_until = None
        self._stock_cooldown.clear()
        self._stock_entry_count.clear()
        self.reset_circuit_breaker()
        logger.info("[리스크] 일일 리셋 완료")

    # ── Utility ────────────────────────────────────────────

    def calculate_position_size(
        self, price: float, stop_loss_pct: float = 0.03
    ) -> int:
        """Calculate position size respecting max position weight.

        연속SL 시 position_scale 적용 (2연속SL 후 50% 축소).
        """
        equity = self.pm.total_equity
        max_value = equity * self.max_position_pct * self.position_scale
        max_qty = int(max_value / price) if price > 0 else 0
        if self.position_scale < 1.0:
            logger.info(
                f"[리스크] 포지션 축소 적용: {self.position_scale:.0%} "
                f"(연속SL {self._consecutive_losses}회)"
            )
        return max_qty

    def get_risk_status(self) -> dict:
        return {
            "circuit_breaker": self._circuit_breaker_active,
            "positions": self.pm.position_count,
            "max_positions": self.max_positions,
            "daily_pnl": int(self.pm.daily_pnl),
            "daily_loss_limit": int(-self.pm.initial_capital * self.max_daily_loss_pct),
            "total_equity": int(self.pm.total_equity),
            "consecutive_losses": self._consecutive_losses,
            "sl_cooldown_until": (
                self._sl_cooldown_until.isoformat()
                if self._sl_cooldown_until else None
            ),
            "position_scale": self.position_scale,
            "entry_paused": self.is_entry_paused(),
            "stocks_cooled_down": list(self._stock_cooldown.keys()),
            "stock_entry_counts": dict(self._stock_entry_count),
        }
