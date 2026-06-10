"""Helper utility functions."""

from datetime import date, datetime, timedelta
from typing import TypeVar

import pandas as pd

# KRX 호가단위/상하한가 헬퍼는 의존성 없는 src/utils/krx.py 에 정의하고 여기서 재노출한다.
from src.utils.krx import (  # noqa: F401
    krx_tick_size,
    round_to_tick,
    limit_price,
    is_at_upper_limit,
    is_at_lower_limit,
)

T = TypeVar("T")


def to_date(date_str: str) -> date:
    """Convert string to date."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def to_datetime(dt_str: str) -> datetime:
    """Convert string to datetime."""
    formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"]
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unable to parse datetime: {dt_str}")


def get_trading_days(start: date, end: date) -> list[date]:
    """Get list of trading days (excluding weekends)."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Monday=0, Friday=4
            days.append(current)
        current += timedelta(days=1)
    return days


def calculate_returns(prices: pd.Series) -> pd.Series:
    """Calculate daily returns from price series."""
    return prices.pct_change().dropna()


def calculate_cumulative_returns(returns: pd.Series) -> pd.Series:
    """Calculate cumulative returns from return series."""
    return (1 + returns).cumprod() - 1


def format_currency(amount: int | float) -> str:
    """Format amount as Korean currency."""
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.1f}억원"
    elif amount >= 10_000:
        return f"{amount / 10_000:.0f}만원"
    else:
        return f"{amount:,.0f}원"


def format_percent(value: float, decimals: int = 2) -> str:
    """Format value as percentage."""
    return f"{value * 100:.{decimals}f}%"


def chunk_list(lst: list[T], chunk_size: int) -> list[list[T]]:
    """Split list into chunks of specified size."""
    return [lst[i : i + chunk_size] for i in range(0, len(lst), chunk_size)]
