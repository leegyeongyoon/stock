"""백테스트 체결 현실성 모델 (슬리피지 / 체결확률 / 유동성캡 / 상한가 체결불가).

기존 엔진은 '신호 봉 종가에 무한 수량 정확히' 체결한다고 가정해 백테스트가 라이브를
크게 과대평가한다(README의 53%→25% 격차). 이 모델이 그 격차를 메운다.

전부 순수 함수(외부 의존 없음)라 완전 오프라인 단위 테스트가 가능하다. 엔진은 이 모델을
옵트인으로 호출하며, 모델이 없으면 기존 동작과 동일하다.
"""

from dataclasses import dataclass
from typing import Literal, Optional

Side = Literal["buy", "sell"]

# 저유동성 가산 기준 거래량(주). 20일 평균이 이보다 적으면 슬리피지를 키운다.
_LIQUIDITY_REFERENCE_SHARES = 1_000_000.0


@dataclass(frozen=True)
class RealismConfig:
    """체결 현실성 파라미터(불변). 모의 포워드 실측으로 보정(Phase 4)."""

    base_slippage_bps: float = 5.0       # 매 체결 기본 슬리피지 (bp, 1bp=0.01%)
    k_range: float = 0.20                # 봉내 변동폭(fraction) 계수
    k_impact: float = 0.50               # 주문량/봉거래량(fraction) 충격 계수
    illiquid_mult_cap: float = 4.0       # 저유동성 슬리피지 가산 상한(배수)
    max_slippage_frac: float = 0.03      # 슬리피지 상한 (3%)
    liquidity_cap_frac: float = 0.01     # 한 봉 거래량의 최대 체결 비율 (1%)
    thin_volume_shares: int = 0          # 봉거래량 < 이 값이면 체결 0 (0=비활성)
    block_limit_up_entry: bool = True    # 잠긴 상한가 매수 금지


@dataclass(frozen=True)
class FillResult:
    """체결 결과."""

    filled_qty: int
    fill_price: float
    reason: str = "ok"  # ok / partial / limit_up_blocked / thin / no_liquidity


class RealismModel:
    """슬리피지·체결확률·유동성캡·상한가 체결불가를 적용하는 모델."""

    def __init__(self, config: Optional[RealismConfig] = None):
        self.config = config or RealismConfig()

    # --- 슬리피지 ---

    def slippage_frac(
        self,
        price: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        order_qty: int,
        vol_avg_20: Optional[float] = None,
    ) -> float:
        """체결 슬리피지를 가격 대비 fraction으로 계산(>=0)."""
        if price <= 0:
            return 0.0
        c = self.config
        range_frac = max(0.0, (bar_high - bar_low) / price)
        impact = (order_qty / bar_volume) if bar_volume and bar_volume > 0 else 0.0

        illiquid = 1.0
        if vol_avg_20 and vol_avg_20 > 0:
            illiquid = min(c.illiquid_mult_cap, max(1.0, _LIQUIDITY_REFERENCE_SHARES / vol_avg_20))

        base = c.base_slippage_bps / 10_000.0
        frac = (base + c.k_range * range_frac + c.k_impact * impact) * illiquid
        return min(c.max_slippage_frac, max(0.0, frac))

    def apply_slippage(
        self,
        side: Side,
        price: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        order_qty: int,
        vol_avg_20: Optional[float] = None,
    ) -> float:
        """매수는 불리하게(↑), 매도는 불리하게(↓) 슬리피지 적용한 체결가."""
        frac = self.slippage_frac(price, bar_high, bar_low, bar_volume, order_qty, vol_avg_20)
        if side == "buy":
            return price * (1.0 + frac)
        return price * (1.0 - frac)

    # --- 유동성 캡 ---

    def cap_quantity(self, desired_qty: int, bar_volume: float) -> int:
        """한 봉에서 체결 가능한 최대 수량(봉거래량의 liquidity_cap_frac)."""
        if desired_qty <= 0:
            return 0
        if not bar_volume or bar_volume <= 0:
            return 0
        cap = int(bar_volume * self.config.liquidity_cap_frac)
        return max(0, min(desired_qty, cap))

    # --- 진입 체결 게이트 ---

    def can_fill(
        self,
        side: Side,
        price: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        desired_qty: int,
        *,
        is_limit_locked: bool = False,
        vol_avg_20: Optional[float] = None,
    ) -> FillResult:
        """진입 체결 시도. 상한가 잠김/얇은 봉/유동성 부족을 반영해 (수량, 체결가) 반환."""
        c = self.config
        if side == "buy" and is_limit_locked and c.block_limit_up_entry:
            return FillResult(0, price, "limit_up_blocked")
        if c.thin_volume_shares and (not bar_volume or bar_volume < c.thin_volume_shares):
            return FillResult(0, price, "thin")

        qty = self.cap_quantity(desired_qty, bar_volume)
        if qty <= 0:
            return FillResult(0, price, "no_liquidity")

        fill = self.apply_slippage(side, price, bar_high, bar_low, bar_volume, qty, vol_avg_20)
        return FillResult(qty, fill, "ok" if qty == desired_qty else "partial")
