"""티어별(균형/공격) 리스크 상태 머신 (의존성 없는 순수 모듈).

전역 RiskManager(6단계)는 바닥(floor)으로 유지하고, 그 위에 티어 캡을 스택한다.
더 엄격한 쪽이 이긴다. equity는 호출자가 넘기는 '해당 티어 기준 자본'(총자본 × 티어 배분)이며,
이 모듈은 그 값 대비 퍼센트만 계산한다(자본 배분 정책은 RiskManager가 결정).
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class TierLimits:
    """한 티어의 리스크 한도(불변)."""

    daily_loss_cap_pct: float       # 티어 하루 손실 상한 (양수, 예: 0.03 = -3%)
    per_trade_stop_pct: float       # 트레이드당 하드 손절(정보/문서용)
    max_trades_per_day: int         # 하루 최대 거래수
    max_concurrent: int             # 동시 최대 포지션
    max_per_theme: int              # 단일 테마 최대 동시 포지션
    profit_lock_pct: float          # 일일 수익 잠금 발동 임계(이익률)
    profit_lock_trail_pct: float    # 잠금 후 고점 대비 되돌림 허용


# 사용자 결정(균형+공격 2-티어, 가드레일 조건부) 기반 기본값
BALANCED = TierLimits(
    daily_loss_cap_pct=0.03, per_trade_stop_pct=0.015,
    max_trades_per_day=6, max_concurrent=3, max_per_theme=1,
    profit_lock_pct=0.04, profit_lock_trail_pct=0.015,
)
AGGRESSIVE = TierLimits(
    daily_loss_cap_pct=0.05, per_trade_stop_pct=0.03,
    max_trades_per_day=4, max_concurrent=2, max_per_theme=1,
    profit_lock_pct=0.06, profit_lock_trail_pct=0.025,
)

DEFAULT_TIER_LIMITS = {"BALANCED": BALANCED, "AGGRESSIVE": AGGRESSIVE}


@dataclass
class TierGate:
    """티어 진입 허용 여부."""

    allowed: bool
    reason: str = ""


@dataclass
class TierRiskState:
    """한 티어의 당일 리스크 상태."""

    name: str
    limits: TierLimits
    daily_pnl: float = 0.0
    trade_count: int = 0
    concurrent: int = 0
    consecutive_losses: int = 0
    peak_pnl: float = 0.0
    profit_armed: bool = False
    locked: bool = False  # 수익잠금/손실상한으로 당일 중단
    open_codes: set = field(default_factory=set)
    open_themes: dict = field(default_factory=dict)  # theme -> count

    def can_enter(self, code: str, theme: Optional[str], equity: float) -> TierGate:
        """진입 가능 여부(티어 캡). 전역 6단계와 별개로 스택된다."""
        if self.locked:
            return TierGate(False, f"{self.name} 당일 중단(수익잠금/손실상한)")
        if self.trade_count >= self.limits.max_trades_per_day:
            return TierGate(False, f"{self.name} 하루 거래수 초과({self.limits.max_trades_per_day})")
        if self.concurrent >= self.limits.max_concurrent:
            return TierGate(False, f"{self.name} 동시 포지션 초과({self.limits.max_concurrent})")
        if code in self.open_codes:
            return TierGate(False, f"물타기 금지(이미 보유): {code}")
        if theme and self.open_themes.get(theme, 0) >= self.limits.max_per_theme:
            return TierGate(False, f"{self.name} 테마 노출 초과: {theme}")
        if equity > 0 and self.daily_pnl <= -self.limits.daily_loss_cap_pct * equity:
            return TierGate(False, f"{self.name} 하루 손실 상한")
        return TierGate(True)

    def record_entry(self, code: str, theme: Optional[str]) -> None:
        self.trade_count += 1
        self.concurrent += 1
        self.open_codes.add(code)
        if theme:
            self.open_themes[theme] = self.open_themes.get(theme, 0) + 1

    def record_exit(self, code: str, theme: Optional[str], pnl: float, equity: float) -> None:
        """청산 결과 반영 + 수익잠금/손실상한 평가."""
        self.concurrent = max(0, self.concurrent - 1)
        self.open_codes.discard(code)
        if theme and theme in self.open_themes:
            self.open_themes[theme] -= 1
            if self.open_themes[theme] <= 0:
                del self.open_themes[theme]

        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if equity > 0:
            # 일일 수익 잠금: 임계 도달 시 무장 → 고점 대비 되돌림 시 중단
            if self.daily_pnl >= self.limits.profit_lock_pct * equity:
                self.profit_armed = True
            self.peak_pnl = max(self.peak_pnl, self.daily_pnl)
            if self.profit_armed and self.daily_pnl <= self.peak_pnl - self.limits.profit_lock_trail_pct * equity:
                self.locked = True
            # 하루 손실 상한 도달 시에도 중단
            if self.daily_pnl <= -self.limits.daily_loss_cap_pct * equity:
                self.locked = True

    def reset_daily(self) -> None:
        self.daily_pnl = 0.0
        self.trade_count = 0
        self.concurrent = 0
        self.consecutive_losses = 0
        self.peak_pnl = 0.0
        self.profit_armed = False
        self.locked = False
        self.open_codes.clear()
        self.open_themes.clear()

    def status(self) -> dict:
        return {
            "tier": self.name,
            "daily_pnl": round(self.daily_pnl, 1),
            "trade_count": self.trade_count,
            "concurrent": self.concurrent,
            "consecutive_losses": self.consecutive_losses,
            "locked": self.locked,
            "open_themes": dict(self.open_themes),
        }


def make_default_tiers() -> dict:
    """기본 균형/공격 티어 상태 2개를 생성."""
    return {name: TierRiskState(name, limits) for name, limits in DEFAULT_TIER_LIMITS.items()}
