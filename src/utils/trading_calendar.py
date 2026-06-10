"""한국 주식시장 거래일/장중 판정 (경량 — 엔진/브로커 의존 없음).

데이터 수집 스크립트 등 라이브 트레이딩 스택(httpx/apscheduler)을 끌어오면 안 되는
곳에서 거래일 판정만 필요할 때 쓴다. scheduler.py 는 여기서 재노출한다.
"""

from datetime import date, datetime, time

# 2025-2026 한국 공휴일 (주식시장 휴장일)
KOREAN_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1),   # 신정
    date(2025, 1, 28),  # 설날 연휴
    date(2025, 1, 29),  # 설날
    date(2025, 1, 30),  # 설날 연휴
    date(2025, 3, 1),   # 삼일절
    date(2025, 5, 1),   # 근로자의 날
    date(2025, 5, 5),   # 어린이날
    date(2025, 5, 6),   # 부처님오신날
    date(2025, 6, 6),   # 현충일
    date(2025, 8, 15),  # 광복절
    date(2025, 10, 3),  # 개천절
    date(2025, 10, 6),  # 추석 연휴
    date(2025, 10, 7),  # 추석
    date(2025, 10, 8),  # 추석 연휴
    date(2025, 10, 9),  # 한글날
    date(2025, 12, 25), # 크리스마스
    date(2025, 12, 31), # 연말 휴장
    # 2026
    date(2026, 1, 1),   # 신정
    date(2026, 2, 16),  # 설날 연휴
    date(2026, 2, 17),  # 설날
    date(2026, 2, 18),  # 설날 연휴
    date(2026, 3, 1),   # 삼일절 (일요일→3/2 대체)
    date(2026, 3, 2),   # 삼일절 대체휴일
    date(2026, 5, 1),   # 근로자의 날
    date(2026, 5, 5),   # 어린이날
    date(2026, 5, 24),  # 부처님오신날
    date(2026, 6, 6),   # 현충일
    date(2026, 8, 15),  # 광복절
    date(2026, 9, 24),  # 추석 연휴
    date(2026, 9, 25),  # 추석
    date(2026, 9, 26),  # 추석 연휴
    date(2026, 10, 3),  # 개천절
    date(2026, 10, 9),  # 한글날
    date(2026, 12, 25), # 크리스마스
    date(2026, 12, 31), # 연말 휴장
}


def is_trading_day(d: date | None = None) -> bool:
    """주어진 날짜가 거래일인지(평일 + 공휴일 아님) 판정."""
    d = d or date.today()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if d in KOREAN_HOLIDAYS:
        return False
    return True


def is_market_hours() -> bool:
    """현재 시각이 장중(09:00~15:30 KST)인지 판정."""
    if not is_trading_day():
        return False
    now = datetime.now()
    return time(9, 0) <= now.time() <= time(15, 30)
