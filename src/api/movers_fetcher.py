"""그날의 유니버스(생존편향 없는 movers) 수집기.

pykrx 일봉 데이터로 '그날 어떤 스캐너로든 포착됐을' 종목 전체를 계산한다:
  - top_gainer : 등락률 상위
  - value_top  : 거래대금 상위
  - vol_surge  : 거래량 급증(20일 평균 대비)
  - limit_up / limit_down : 상/하한가

flag/limit 계산은 순수 함수(`compute_movers`, `compute_limit_events`)로 분리해
pykrx 없이도 단위 테스트할 수 있게 한다. 클래스는 I/O만 담당한다.
"""

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

import pandas as pd
from pykrx import stock as pykrx_stock

from src.utils.krx import limit_price
from src.utils.logger import get_logger

logger = get_logger(__name__)


# vol_avg_20을 code로 조회하는 공급자(없으면 거래량급증 판정은 비활성).
VolAvgProvider = Callable[[str], Optional[float]]


@dataclass(frozen=True)
class MoversConfig:
    """movers 선정 임계치(불변)."""

    top_gainer_n: int = 100          # 등락률 상위 N
    value_top_n: int = 300           # 거래대금 상위 N
    vol_surge_ratio: float = 3.0     # 거래량 / 20일평균 >= 이 값
    vol_surge_min_value: int = 1_000_000_000  # 거래대금 10억 이상(잡신호 제거)
    limit_up_threshold: float = 29.0    # 등락률 >= → 상한가 추정
    limit_down_threshold: float = -29.0  # 등락률 <= → 하한가 추정


# 정규화된 DataFrame이 가져야 할 컬럼(index=code).
NORMALIZED_COLUMNS = (
    "market", "open", "high", "low", "close",
    "change_rate", "volume", "value", "market_cap", "vol_avg_20", "prev_close",
)


def _to_int(v) -> Optional[int]:
    if v is None or pd.isna(v):
        return None
    return int(v)


def _to_float(v) -> Optional[float]:
    if v is None or pd.isna(v):
        return None
    return float(v)


def compute_movers(df: pd.DataFrame, target_date: date, config: MoversConfig) -> list[dict]:
    """정규화 DataFrame → DailyMovers upsert용 dict 리스트(순수 함수).

    어떤 flag로든 포착된 종목만 union으로 반환한다(생존편향 제거).
    """
    if df is None or df.empty:
        return []

    work = df.copy()
    work["rank_change"] = work["change_rate"].rank(ascending=False, method="min")
    work["rank_value"] = work["value"].rank(ascending=False, method="min")
    vol_avg = work["vol_avg_20"].where(work["vol_avg_20"] > 0)
    work["volume_ratio"] = work["volume"] / vol_avg
    work["rank_volume_ratio"] = work["volume_ratio"].rank(ascending=False, method="min")

    records: list[dict] = []
    for code, row in work.iterrows():
        cr = _to_float(row["change_rate"])
        value = _to_int(row["value"])
        vr = _to_float(row["volume_ratio"])
        rank_change = _to_int(row["rank_change"])
        rank_value = _to_int(row["rank_value"])

        flags: list[str] = []
        if rank_change is not None and rank_change <= config.top_gainer_n and cr is not None and cr > 0:
            flags.append("top_gainer")
        if rank_value is not None and rank_value <= config.value_top_n:
            flags.append("value_top")
        if (
            vr is not None and vr >= config.vol_surge_ratio
            and value is not None and value >= config.vol_surge_min_value
        ):
            flags.append("vol_surge")
        is_lu = cr is not None and cr >= config.limit_up_threshold
        is_ld = cr is not None and cr <= config.limit_down_threshold
        if is_lu:
            flags.append("limit_up")
        if is_ld:
            flags.append("limit_down")

        if not flags:
            continue

        records.append(
            {
                "date": target_date,
                "code": str(code),
                "market": row.get("market"),
                "open": _to_int(row["open"]),
                "high": _to_int(row["high"]),
                "low": _to_int(row["low"]),
                "close": _to_int(row["close"]),
                "change_rate": cr,
                "volume": _to_int(row["volume"]),
                "value": value,
                "market_cap": _to_int(row["market_cap"]),
                "volume_ratio": round(vr, 4) if vr is not None else None,
                "is_limit_up": is_lu,
                "is_limit_down": is_ld,
                "rank_change": rank_change,
                "rank_value": rank_value,
                "rank_volume_ratio": _to_int(row["rank_volume_ratio"]),
                "flags": flags,
                "theme_tags": None,
            }
        )
    return records


def compute_limit_events(df: pd.DataFrame, target_date: date, config: MoversConfig) -> list[dict]:
    """정규화 DataFrame → LimitEvent(daily_inferred) upsert용 dict 리스트(순수 함수).

    분봉이 없으므로 first_hit_time=None, hit_count=0. closed_at_limit는 종가=고가(상한)/
    종가=저가(하한)로 추정한다.
    """
    if df is None or df.empty:
        return []

    records: list[dict] = []
    for code, row in df.iterrows():
        cr = _to_float(row["change_rate"])
        if cr is None:
            continue
        close = _to_int(row["close"])
        high = _to_int(row["high"])
        low = _to_int(row["low"])
        prev = _to_int(row["prev_close"])

        if cr >= config.limit_up_threshold:
            lp = limit_price(prev, "up") if prev else None
            records.append(
                {
                    "date": target_date, "code": str(code), "event_type": "limit_up",
                    "limit_price": lp, "first_hit_time": None, "hit_count": 0,
                    "closed_at_limit": bool(close is not None and high is not None and close == high),
                    "source": "daily_inferred",
                }
            )
        elif cr <= config.limit_down_threshold:
            lp = limit_price(prev, "down") if prev else None
            records.append(
                {
                    "date": target_date, "code": str(code), "event_type": "limit_down",
                    "limit_price": lp, "first_hit_time": None, "hit_count": 0,
                    "closed_at_limit": bool(close is not None and low is not None and close == low),
                    "source": "daily_inferred",
                }
            )
    return records


class MoversFetcher:
    """pykrx로 전종목 일봉을 받아 정규화하는 I/O 계층."""

    def __init__(self, config: Optional[MoversConfig] = None):
        self.config = config or MoversConfig()

    @staticmethod
    def _to_str(d: date) -> str:
        return d.strftime("%Y%m%d")

    def fetch_raw(
        self, target_date: date, vol_avg_provider: Optional[VolAvgProvider] = None
    ) -> pd.DataFrame:
        """전종목 일봉 + 시총 + 시장구분 + 전일종가 + 20일평균거래량을 정규화한 DataFrame.

        비거래일/데이터 없음이면 빈 DataFrame.
        """
        ds = self._to_str(target_date)
        try:
            ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(ds, market="ALL")
        except Exception as e:  # noqa: BLE001 - pykrx는 다양한 예외를 던진다
            logger.error(f"get_market_ohlcv_by_ticker 실패 {ds}: {e}")
            return pd.DataFrame()

        if ohlcv is None or ohlcv.empty:
            logger.info(f"일봉 데이터 없음(비거래일 추정): {ds}")
            return pd.DataFrame()

        df = ohlcv.rename(
            columns={
                "시가": "open", "고가": "high", "저가": "low", "종가": "close",
                "거래량": "volume", "거래대금": "value", "등락률": "change_rate",
            }
        )[["open", "high", "low", "close", "volume", "value", "change_rate"]].copy()

        # 시가총액
        try:
            cap = pykrx_stock.get_market_cap_by_ticker(ds, market="ALL")
            df["market_cap"] = cap["시가총액"].reindex(df.index) if cap is not None and not cap.empty else pd.NA
        except Exception as e:  # noqa: BLE001
            logger.warning(f"시가총액 조회 실패 {ds}: {e}")
            df["market_cap"] = pd.NA

        # 시장 구분
        try:
            kospi = set(pykrx_stock.get_market_ticker_list(ds, market="KOSPI"))
        except Exception:  # noqa: BLE001
            kospi = set()
        df["market"] = ["KOSPI" if c in kospi else "KOSDAQ" for c in df.index]

        # 전일 종가(등락률로 역산; -100% 방지)
        denom = 1.0 + df["change_rate"] / 100.0
        prev = df["close"] / denom.where(denom > 0)
        df["prev_close"] = prev.round()

        # 20일 평균 거래량(공급자 없으면 NA → 거래량급증 판정 비활성)
        if vol_avg_provider is not None:
            df["vol_avg_20"] = [vol_avg_provider(str(c)) for c in df.index]
        else:
            df["vol_avg_20"] = pd.NA

        return df

    def fetch(
        self, target_date: date, vol_avg_provider: Optional[VolAvgProvider] = None
    ) -> tuple[list[dict], list[dict]]:
        """(movers 레코드, limit_event 레코드) 튜플 반환."""
        df = self.fetch_raw(target_date, vol_avg_provider)
        if df.empty:
            return [], []
        movers = compute_movers(df, target_date, self.config)
        limits = compute_limit_events(df, target_date, self.config)
        logger.info(
            f"{target_date} movers {len(movers)}종목, 상/하한가 {len(limits)}건 계산"
        )
        return movers, limits
