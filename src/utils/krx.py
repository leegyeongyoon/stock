"""KRX 호가단위(tick size) 및 일일 가격제한(상/하한가) 유틸.

순수 함수만 — 외부 의존성 없음(stdlib only). 상한가 이벤트 탐지(데이터 수집)와
상따 전략(체결 현실성)에서 공용으로 쓰인다.

호가단위는 2023년 통합 기준(KOSPI/KOSDAQ 동일):
    <  2,000      → 1원
    2,000~5,000   → 5원
    5,000~20,000  → 10원
    20,000~50,000 → 50원
    50,000~200,000→ 100원
    200,000~500,000→ 500원
    >= 500,000    → 1,000원

주의: ETF/ETN, 정리매매, 신규상장 등 일부 종목은 호가단위·가격제한폭이 다르다.
일반 주식(±30%) 기준이며, 수집 단계에서는 ``source='daily_inferred'`` 로 표기하고
분봉 확인 단계에서 보정한다.
"""

from typing import Literal

# (상한 미만 가격, 호가단위) — 오름차순. 마지막은 그 이상 전부.
_TICK_TABLE: tuple[tuple[int, int], ...] = (
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
)
_TOP_TICK = 1_000

# 일일 가격제한폭 (일반 주식)
PRICE_LIMIT_RATE = 0.30

Direction = Literal["up", "down"]
RoundMode = Literal["floor", "ceil"]


def krx_tick_size(price: float) -> int:
    """주어진 가격대에 적용되는 KRX 호가단위(원)를 반환."""
    if price < 0:
        raise ValueError(f"price must be non-negative: {price}")
    for upper, tick in _TICK_TABLE:
        if price < upper:
            return tick
    return _TOP_TICK


def round_to_tick(price: float, mode: RoundMode = "floor") -> int:
    """가격을 해당 가격대의 호가단위로 내림(floor)/올림(ceil)한다.

    호가단위는 *반올림 대상 가격* 이 속한 구간 기준으로 정한다(KRX 방식).
    """
    if price < 0:
        raise ValueError(f"price must be non-negative: {price}")
    tick = krx_tick_size(price)
    if mode == "floor":
        return int(price // tick) * tick
    if mode == "ceil":
        return -int(-price // tick) * tick
    raise ValueError(f"invalid mode: {mode!r} (expected 'floor'|'ceil')")


def limit_price(prev_close: float, direction: Direction, rate: float = PRICE_LIMIT_RATE) -> int:
    """전일 종가 기준 상한가('up') 또는 하한가('down')를 계산한다.

    상한가 = 기준가 × (1+rate) → 호가단위 내림 (밴드를 넘지 않도록)
    하한가 = 기준가 × (1-rate) → 호가단위 올림 (밴드를 넘지 않도록)
    """
    if prev_close <= 0:
        raise ValueError(f"prev_close must be positive: {prev_close}")
    if direction == "up":
        return round_to_tick(prev_close * (1.0 + rate), mode="floor")
    if direction == "down":
        return round_to_tick(prev_close * (1.0 - rate), mode="ceil")
    raise ValueError(f"invalid direction: {direction!r} (expected 'up'|'down')")


def is_at_upper_limit(prev_close: float, price: float, tolerance_ticks: int = 0) -> bool:
    """주어진 가격이 상한가 이상인지(= 상한가 도달/굳히기) 판정."""
    if prev_close <= 0:
        return False
    upper = limit_price(prev_close, "up")
    if tolerance_ticks > 0:
        upper -= tolerance_ticks * krx_tick_size(upper)
    return price >= upper


def is_at_lower_limit(prev_close: float, price: float, tolerance_ticks: int = 0) -> bool:
    """주어진 가격이 하한가 이하인지 판정."""
    if prev_close <= 0:
        return False
    lower = limit_price(prev_close, "down")
    if tolerance_ticks > 0:
        lower += tolerance_ticks * krx_tick_size(lower)
    return price <= lower
