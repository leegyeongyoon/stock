"""종목 상세 분석 - pykrx와 yfinance API 사용"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from pykrx import stock as pykrx_stock
import yfinance as yf
from loguru import logger


@dataclass
class CandleData:
    """캔들 데이터"""
    time: str
    open: int
    high: int
    low: int
    close: int
    volume: int
    change_rate: float = 0.0


@dataclass
class MultiDaySupply:
    """다일간 수급 데이터"""
    days: int
    foreign_total: int  # 누적 외인 순매수
    inst_total: int     # 누적 기관 순매수
    foreign_avg: float  # 일평균 외인 순매수
    inst_avg: float     # 일평균 기관 순매수
    trend: str          # 매집/매도/혼조


@dataclass
class VolumeAnalysis:
    """거래량 분석"""
    today: int
    avg_5d: int
    avg_20d: int
    ratio_vs_5d: float   # 오늘 / 5일 평균
    ratio_vs_20d: float  # 오늘 / 20일 평균
    trend: str           # 급증/증가/보통/감소/급감
    comment: str


@dataclass
class BollingerPosition:
    """볼린저밴드 위치"""
    upper: float
    middle: float
    lower: float
    current: float
    position_pct: float  # 0=하단, 50=중단, 100=상단
    zone: str            # 상단돌파/상단근접/중단/하단근접/하단이탈
    comment: str


@dataclass
class PricePosition:
    """가격 위치 분석"""
    current: int
    high_52w: int       # 52주 신고가
    low_52w: int        # 52주 신저가
    from_high_pct: float  # 신고가 대비 (%)
    from_low_pct: float   # 신저가 대비 (%)
    ma_20: float
    ma_60: float
    ma_120: float
    above_ma20: bool
    above_ma60: bool
    above_ma120: bool
    position_comment: str


@dataclass
class Valuation:
    """밸류에이션"""
    market_cap: int       # 시가총액 (억원)
    per: float            # PER
    pbr: float            # PBR
    eps: int              # EPS
    bps: int              # BPS
    dividend_yield: float # 배당수익률 (%)
    comment: str


@dataclass
class TechnicalIndicators:
    """기술적 지표"""
    # 이동평균
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    ma120: float = 0.0

    # RSI
    rsi14: float = 50.0

    # MACD
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0

    # 스토캐스틱
    stoch_k: float = 50.0
    stoch_d: float = 50.0


@dataclass
class BuySignal:
    """매수 신호 분석"""
    score: int           # 총점 (100점 만점)
    grade: str           # A/B/C/D/F
    positives: list[str] # 긍정 요인
    negatives: list[str] # 부정 요인
    recommendation: str  # 최종 추천
    risk_level: str      # 위험도 (높음/중간/낮음)


@dataclass
class StockDetail:
    """종목 상세 정보"""
    code: str
    name: str
    current_price: int
    change_rate: float
    change_amount: int

    # 거래 정보
    volume: int
    trading_value: int  # 거래대금 (백만원)

    # 가격 정보
    open_price: int
    high_price: int
    low_price: int
    prev_close: int

    # 다일간 수급 분석
    supply_3d: MultiDaySupply
    supply_7d: MultiDaySupply
    supply_10d: MultiDaySupply
    supply_30d: MultiDaySupply

    # 거래량 분석
    volume_analysis: VolumeAnalysis

    # 볼린저밴드 위치
    bb_position: BollingerPosition

    # 가격 위치
    price_position: PricePosition

    # 밸류에이션
    valuation: Valuation

    # 기술적 지표
    indicators: TechnicalIndicators

    # 분봉 데이터
    candles_1m: list[CandleData] = field(default_factory=list)
    candles_5m: list[CandleData] = field(default_factory=list)

    # 매수 신호 분석
    buy_signal: BuySignal = None

    # 종합 코멘트
    summary: str = ""


class StockAnalyzer:
    """종목 분석기 - pykrx와 yfinance 사용"""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)

    def _to_str_date(self, d: date) -> str:
        """Convert date to string format for pykrx."""
        return d.strftime("%Y%m%d")

    def _get_ohlcv_sync(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        """OHLCV 데이터 조회 (동기)"""
        try:
            df = pykrx_stock.get_market_ohlcv(
                self._to_str_date(start_date),
                self._to_str_date(end_date),
                code
            )
            if df.empty:
                return pd.DataFrame()

            df = df.rename(columns={
                "시가": "open",
                "고가": "high",
                "저가": "low",
                "종가": "close",
                "거래량": "volume",
                "거래대금": "value",
                "등락률": "change_rate",
            })
            return df
        except Exception as e:
            logger.error(f"OHLCV 조회 실패 ({code}): {e}")
            return pd.DataFrame()

    def _get_investor_trading_sync(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        """외인/기관 매매동향 조회 (동기)"""
        try:
            df = pykrx_stock.get_market_trading_value_by_investor(
                self._to_str_date(start_date),
                self._to_str_date(end_date),
                code
            )
            if df.empty:
                return pd.DataFrame()

            result = pd.DataFrame(index=df.index)
            if "외국인합계" in df.columns:
                result["foreign"] = df["외국인합계"]
            if "기관합계" in df.columns:
                result["inst"] = df["기관합계"]

            return result
        except Exception as e:
            logger.error(f"투자자별 매매 조회 실패 ({code}): {e}")
            return pd.DataFrame()

    def _get_fundamental_sync(self, code: str, target_date: date) -> dict:
        """기본적 분석 데이터 조회 (PER, PBR 등)"""
        result = {
            "market_cap": 0,
            "per": 0.0,
            "pbr": 0.0,
            "eps": 0,
            "bps": 0,
            "dividend_yield": 0.0,
        }

        try:
            # 시가총액
            cap_df = pykrx_stock.get_market_cap(
                self._to_str_date(target_date),
                self._to_str_date(target_date),
                code
            )
            if not cap_df.empty and "시가총액" in cap_df.columns:
                result["market_cap"] = int(cap_df["시가총액"].iloc[0] // 100000000)  # 억원

            # PER, PBR, EPS, BPS, 배당수익률
            fund_df = pykrx_stock.get_market_fundamental(
                self._to_str_date(target_date),
                self._to_str_date(target_date),
                code
            )
            if not fund_df.empty:
                if "PER" in fund_df.columns:
                    result["per"] = float(fund_df["PER"].iloc[0]) if pd.notna(fund_df["PER"].iloc[0]) else 0.0
                if "PBR" in fund_df.columns:
                    result["pbr"] = float(fund_df["PBR"].iloc[0]) if pd.notna(fund_df["PBR"].iloc[0]) else 0.0
                if "EPS" in fund_df.columns:
                    result["eps"] = int(fund_df["EPS"].iloc[0]) if pd.notna(fund_df["EPS"].iloc[0]) else 0
                if "BPS" in fund_df.columns:
                    result["bps"] = int(fund_df["BPS"].iloc[0]) if pd.notna(fund_df["BPS"].iloc[0]) else 0
                if "DIV" in fund_df.columns:
                    result["dividend_yield"] = float(fund_df["DIV"].iloc[0]) if pd.notna(fund_df["DIV"].iloc[0]) else 0.0

        except Exception as e:
            logger.error(f"기본적 분석 조회 실패 ({code}): {e}")

        return result

    def _get_intraday_sync(self, code: str, interval: str = "5m") -> pd.DataFrame:
        """분봉 데이터 조회 (yfinance 사용)"""
        try:
            ticker = f"{code}.KS"
            stock = yf.Ticker(ticker)

            # 1분봉은 최근 7일만 가능
            period = "7d" if interval == "1m" else "60d"
            df = stock.history(period=period, interval=interval)

            if df.empty:
                return pd.DataFrame()

            df = df.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })

            df = df[["open", "high", "low", "close", "volume"]].copy()

            # 타임존 변환
            if df.index.tz is not None:
                df.index = df.index.tz_convert("Asia/Seoul").tz_localize(None)

            return df
        except Exception as e:
            logger.error(f"분봉 조회 실패 ({code}, {interval}): {e}")
            return pd.DataFrame()

    async def get_ohlcv(self, code: str, days: int = 120) -> pd.DataFrame:
        """OHLCV 데이터 조회 (비동기)"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._get_ohlcv_sync, code, start_date, end_date
        )

    async def get_investor_trading(self, code: str, days: int = 30) -> pd.DataFrame:
        """외인/기관 매매동향 조회 (비동기)"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days + 10)  # 휴일 고려
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._get_investor_trading_sync, code, start_date, end_date
        )

    async def get_fundamental(self, code: str) -> dict:
        """기본적 분석 데이터 조회 (비동기)"""
        target_date = date.today()
        # 주말/휴일 처리
        if target_date.weekday() >= 5:
            target_date = target_date - timedelta(days=target_date.weekday() - 4)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._get_fundamental_sync, code, target_date
        )

    async def get_intraday(self, code: str, interval: str = "5m") -> pd.DataFrame:
        """분봉 데이터 조회 (비동기)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._get_intraday_sync, code, interval
        )

    def analyze_multi_day_supply(self, df: pd.DataFrame, days: int) -> MultiDaySupply:
        """다일간 수급 분석"""
        if df.empty or len(df) == 0:
            return MultiDaySupply(
                days=days, foreign_total=0, inst_total=0,
                foreign_avg=0, inst_avg=0, trend="데이터없음"
            )

        data = df.tail(days)
        foreign_total = int(data["foreign"].sum()) if "foreign" in data.columns else 0
        inst_total = int(data["inst"].sum()) if "inst" in data.columns else 0

        actual_days = len(data) or 1
        foreign_avg = foreign_total / actual_days
        inst_avg = inst_total / actual_days

        # 추세 판단 (금액 기준: 10억 이상이면 의미있는 수준)
        threshold = 1000000000  # 10억

        if foreign_total > threshold and inst_total > threshold:
            trend = "쌍매집"
        elif foreign_total > threshold:
            trend = "외인매집"
        elif inst_total > threshold:
            trend = "기관매집"
        elif foreign_total > 0 and inst_total > 0:
            trend = "동반매수"
        elif foreign_total < -threshold and inst_total < -threshold:
            trend = "쌍매도"
        elif foreign_total < -threshold:
            trend = "외인매도"
        elif inst_total < -threshold:
            trend = "기관매도"
        elif foreign_total < 0 and inst_total < 0:
            trend = "동반매도"
        else:
            trend = "혼조"

        return MultiDaySupply(
            days=days,
            foreign_total=foreign_total,
            inst_total=inst_total,
            foreign_avg=foreign_avg,
            inst_avg=inst_avg,
            trend=trend
        )

    def analyze_volume(self, df: pd.DataFrame, today_volume: int) -> VolumeAnalysis:
        """거래량 분석"""
        if df.empty or "volume" not in df.columns:
            return VolumeAnalysis(
                today=today_volume, avg_5d=0, avg_20d=0,
                ratio_vs_5d=1.0, ratio_vs_20d=1.0,
                trend="데이터없음", comment="거래량 데이터 없음"
            )

        recent = df.tail(20)
        avg_5d = int(recent.tail(5)["volume"].mean()) if len(recent) >= 5 else 0
        avg_20d = int(recent["volume"].mean()) if len(recent) > 0 else 0

        ratio_5d = today_volume / avg_5d if avg_5d > 0 else 1
        ratio_20d = today_volume / avg_20d if avg_20d > 0 else 1

        # 추세 판단
        if ratio_5d >= 3:
            trend = "급증"
            comment = f"5일 평균 대비 {ratio_5d:.1f}배 급증! 주의 필요"
        elif ratio_5d >= 1.5:
            trend = "증가"
            comment = f"평소보다 거래량 {ratio_5d:.1f}배 증가"
        elif ratio_5d >= 0.7:
            trend = "보통"
            comment = "평균 수준 거래량"
        elif ratio_5d >= 0.3:
            trend = "감소"
            comment = "평소보다 거래량 적음"
        else:
            trend = "급감"
            comment = "거래량 급감, 관심도 하락"

        return VolumeAnalysis(
            today=today_volume,
            avg_5d=avg_5d,
            avg_20d=avg_20d,
            ratio_vs_5d=ratio_5d,
            ratio_vs_20d=ratio_20d,
            trend=trend,
            comment=comment
        )

    def calculate_bollinger(self, df: pd.DataFrame, window: int = 20) -> tuple:
        """볼린저밴드 계산"""
        if df.empty or "close" not in df.columns or len(df) < window:
            return 0, 0, 0

        recent = df.tail(window)
        middle = recent["close"].mean()
        std = recent["close"].std()
        upper = middle + std * 2
        lower = middle - std * 2

        return upper, middle, lower

    def analyze_bollinger_position(self, current: float, upper: float, middle: float, lower: float) -> BollingerPosition:
        """볼린저밴드 위치 분석"""
        if upper == lower or upper == 0:
            return BollingerPosition(
                upper=upper, middle=middle, lower=lower, current=current,
                position_pct=50, zone="산정불가", comment="데이터 부족"
            )

        # 위치 계산 (0=하단, 100=상단)
        position_pct = ((current - lower) / (upper - lower)) * 100
        position_pct = max(0, min(100, position_pct))

        # 구간 판단
        if position_pct > 100:
            zone = "상단돌파"
            comment = "볼린저 상단 돌파! 과열 주의, 단기 조정 가능"
        elif position_pct > 80:
            zone = "상단근접"
            comment = "상단 밴드 근접, 추격매수 주의"
        elif position_pct > 60:
            zone = "중상단"
            comment = "중심선 상단, 상승 추세 유지 중"
        elif position_pct > 40:
            zone = "중단"
            comment = "중심선 부근, 방향성 확인 필요"
        elif position_pct > 20:
            zone = "중하단"
            comment = "중심선 하단, 약세 또는 눌림 구간"
        elif position_pct > 0:
            zone = "하단근접"
            comment = "하단 밴드 근접, 반등 가능성"
        else:
            zone = "하단이탈"
            comment = "볼린저 하단 이탈! 급락 주의 또는 바닥 근접"

        return BollingerPosition(
            upper=upper, middle=middle, lower=lower, current=current,
            position_pct=position_pct, zone=zone, comment=comment
        )

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """RSI 계산"""
        if df.empty or "close" not in df.columns or len(df) < period + 1:
            return 50.0

        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0

    def calculate_macd(self, df: pd.DataFrame) -> tuple:
        """MACD 계산"""
        if df.empty or "close" not in df.columns or len(df) < 26:
            return 0, 0, 0

        exp12 = df["close"].ewm(span=12, adjust=False).mean()
        exp26 = df["close"].ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal

        return float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])

    def calculate_stochastic(self, df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> tuple:
        """스토캐스틱 계산"""
        if df.empty or len(df) < k_period:
            return 50.0, 50.0

        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()

        k = 100 * (df["close"] - low_min) / (high_max - low_min)
        d = k.rolling(window=d_period).mean()

        return float(k.iloc[-1]) if pd.notna(k.iloc[-1]) else 50.0, \
               float(d.iloc[-1]) if pd.notna(d.iloc[-1]) else 50.0

    def analyze_price_position(self, df: pd.DataFrame, current: int) -> PricePosition:
        """가격 위치 분석"""
        if df.empty:
            return PricePosition(
                current=current, high_52w=current, low_52w=current,
                from_high_pct=0, from_low_pct=0,
                ma_20=current, ma_60=current, ma_120=current,
                above_ma20=True, above_ma60=True, above_ma120=True,
                position_comment="데이터 부족"
            )

        # 52주 고저가
        year_data = df.tail(252)  # 약 1년
        high_52w = int(year_data["high"].max()) if len(year_data) > 0 else current
        low_52w = int(year_data["low"].min()) if len(year_data) > 0 else current

        from_high_pct = ((current - high_52w) / high_52w * 100) if high_52w > 0 else 0
        from_low_pct = ((current - low_52w) / low_52w * 100) if low_52w > 0 else 0

        # 이동평균
        ma_20 = df["close"].tail(20).mean() if len(df) >= 20 else current
        ma_60 = df["close"].tail(60).mean() if len(df) >= 60 else current
        ma_120 = df["close"].tail(120).mean() if len(df) >= 120 else current

        above_ma20 = current > ma_20
        above_ma60 = current > ma_60
        above_ma120 = current > ma_120

        # 코멘트 생성
        comments = []

        if from_high_pct > -5:
            comments.append("52주 신고가 근접/돌파")
        elif from_high_pct < -30:
            comments.append(f"52주 고점 대비 {abs(from_high_pct):.0f}% 하락")

        if from_low_pct < 10:
            comments.append("52주 신저가 근접")
        elif from_low_pct > 100:
            comments.append(f"52주 저점 대비 {from_low_pct:.0f}% 상승")

        if above_ma20 and above_ma60 and above_ma120:
            comments.append("이평선 정배열 (상승추세)")
        elif not above_ma20 and not above_ma60 and not above_ma120:
            comments.append("이평선 역배열 (하락추세)")

        return PricePosition(
            current=current,
            high_52w=high_52w,
            low_52w=low_52w,
            from_high_pct=from_high_pct,
            from_low_pct=from_low_pct,
            ma_20=ma_20,
            ma_60=ma_60,
            ma_120=ma_120,
            above_ma20=above_ma20,
            above_ma60=above_ma60,
            above_ma120=above_ma120,
            position_comment=" | ".join(comments) if comments else "특이사항 없음"
        )

    def analyze_valuation(self, fundamental: dict) -> Valuation:
        """밸류에이션 분석"""
        market_cap = fundamental.get("market_cap", 0)
        per = fundamental.get("per", 0)
        pbr = fundamental.get("pbr", 0)
        eps = fundamental.get("eps", 0)
        bps = fundamental.get("bps", 0)
        dividend_yield = fundamental.get("dividend_yield", 0)

        comments = []

        if per > 0:
            if per < 10:
                comments.append("저PER (저평가 가능)")
            elif per > 30:
                comments.append("고PER (고평가 주의)")

        if pbr > 0:
            if pbr < 1:
                comments.append("PBR 1배 미만 (자산가치 대비 저평가)")
            elif pbr > 3:
                comments.append("고PBR (프리미엄 반영)")

        if dividend_yield > 3:
            comments.append(f"배당수익률 {dividend_yield:.1f}% (고배당)")

        if market_cap > 0:
            if market_cap >= 100000:
                comments.append("대형주 (10조+)")
            elif market_cap >= 10000:
                comments.append("중형주 (1조+)")
            else:
                comments.append("소형주")

        return Valuation(
            market_cap=market_cap,
            per=per,
            pbr=pbr,
            eps=eps,
            bps=bps,
            dividend_yield=dividend_yield,
            comment=" | ".join(comments) if comments else "특이사항 없음"
        )

    def generate_buy_signal(
        self,
        supply_7d: MultiDaySupply,
        supply_30d: MultiDaySupply,
        volume_analysis: VolumeAnalysis,
        bb_position: BollingerPosition,
        price_position: PricePosition,
        rsi: float,
        change_rate: float
    ) -> BuySignal:
        """매수 신호 종합 분석"""
        score = 50  # 기본 점수
        positives = []
        negatives = []

        # 1. 수급 분석 (30점)
        if "쌍매집" in supply_7d.trend or "쌍매집" in supply_30d.trend:
            score += 20
            positives.append("외인+기관 동반 매집 중")
        elif "외인매집" in supply_7d.trend or "기관매집" in supply_7d.trend:
            score += 10
            positives.append(f"7일간 {supply_7d.trend}")
        elif "쌍매도" in supply_7d.trend:
            score -= 15
            negatives.append("외인+기관 동반 매도 중")
        elif "외인매도" in supply_7d.trend or "기관매도" in supply_7d.trend:
            score -= 10
            negatives.append(f"7일간 {supply_7d.trend}")

        # 30일 장기 추세
        if supply_30d.foreign_total > 50000000000:  # 500억 이상
            score += 10
            positives.append("30일 외인 대규모 매집")
        elif supply_30d.foreign_total < -50000000000:
            score -= 10
            negatives.append("30일 외인 대규모 이탈")

        # 2. 거래량 분석 (15점)
        if volume_analysis.trend == "급증":
            if change_rate > 0:
                score += 10
                positives.append("상승 + 거래량 급증 (관심 집중)")
            else:
                score -= 5
                negatives.append("하락 + 거래량 급증 (투매 가능)")
        elif volume_analysis.trend == "급감":
            score -= 5
            negatives.append("거래량 급감 (관심도 하락)")

        # 3. 볼린저밴드 위치 (15점)
        if bb_position.zone == "하단근접":
            score += 10
            positives.append("볼린저 하단 근접 (반등 기대)")
        elif bb_position.zone == "하단이탈":
            score += 5
            positives.append("볼린저 하단 이탈 (바닥 가능)")
        elif bb_position.zone == "상단돌파":
            score -= 10
            negatives.append("볼린저 상단 돌파 (과열)")
        elif bb_position.zone == "상단근접":
            score -= 5
            negatives.append("볼린저 상단 근접 (추격매수 주의)")

        # 4. 이평선 배열 (15점)
        if price_position.above_ma20 and price_position.above_ma60:
            score += 10
            positives.append("이평선 위 (상승 추세)")
        elif not price_position.above_ma20 and not price_position.above_ma60:
            score -= 10
            negatives.append("이평선 아래 (하락 추세)")

        # 5. 52주 위치 (10점)
        if price_position.from_high_pct > -10:
            score += 5
            positives.append("52주 신고가 근접")
        elif price_position.from_low_pct < 20:
            score += 5
            positives.append("52주 신저가 근접 (바닥 가능)")
        elif price_position.from_high_pct < -40:
            negatives.append(f"고점 대비 {abs(price_position.from_high_pct):.0f}% 하락")

        # 6. RSI (15점)
        if rsi < 30:
            score += 10
            positives.append("RSI 과매도 (반등 기대)")
        elif rsi > 70:
            score -= 10
            negatives.append("RSI 과매수 (조정 가능)")
        elif 40 <= rsi <= 60:
            positives.append("RSI 중립 구간")

        # 점수 범위 제한
        score = max(0, min(100, score))

        # 등급
        if score >= 80:
            grade = "A"
            recommendation = "적극 매수 검토"
            risk_level = "낮음"
        elif score >= 65:
            grade = "B"
            recommendation = "매수 관심"
            risk_level = "중간"
        elif score >= 50:
            grade = "C"
            recommendation = "관망 권장"
            risk_level = "중간"
        elif score >= 35:
            grade = "D"
            recommendation = "매수 보류"
            risk_level = "높음"
        else:
            grade = "F"
            recommendation = "매수 비추천"
            risk_level = "매우높음"

        return BuySignal(
            score=score,
            grade=grade,
            positives=positives,
            negatives=negatives,
            recommendation=recommendation,
            risk_level=risk_level
        )

    async def get_stock_detail(self, code: str, name: str = "") -> StockDetail:
        """종목 상세 분석"""
        logger.info(f"종목 분석 시작: {code} {name}")

        # 종목명 조회
        if not name:
            try:
                name = pykrx_stock.get_market_ticker_name(code)
            except:
                name = code

        # 병렬로 데이터 조회
        ohlcv_task = self.get_ohlcv(code, days=252)  # 1년
        investor_task = self.get_investor_trading(code, days=30)
        fundamental_task = self.get_fundamental(code)
        intraday_1m_task = self.get_intraday(code, "1m")
        intraday_5m_task = self.get_intraday(code, "5m")

        ohlcv_df, investor_df, fundamental, intraday_1m, intraday_5m = await asyncio.gather(
            ohlcv_task, investor_task, fundamental_task, intraday_1m_task, intraday_5m_task
        )

        # 현재가 및 기본 정보
        if not ohlcv_df.empty:
            latest = ohlcv_df.iloc[-1]
            prev = ohlcv_df.iloc[-2] if len(ohlcv_df) > 1 else latest
            current_price = int(latest["close"])
            prev_close = int(prev["close"])
            change_amount = current_price - prev_close
            change_rate = float(latest.get("change_rate", 0))
            volume = int(latest["volume"])
            trading_value = int(latest.get("value", 0) // 1000000)  # 백만원
            open_price = int(latest["open"])
            high_price = int(latest["high"])
            low_price = int(latest["low"])
        else:
            current_price = prev_close = volume = trading_value = 0
            change_amount = 0
            change_rate = 0.0
            open_price = high_price = low_price = 0

        # 수급 분석
        supply_3d = self.analyze_multi_day_supply(investor_df, 3)
        supply_7d = self.analyze_multi_day_supply(investor_df, 7)
        supply_10d = self.analyze_multi_day_supply(investor_df, 10)
        supply_30d = self.analyze_multi_day_supply(investor_df, 30)

        # 거래량 분석
        volume_analysis = self.analyze_volume(ohlcv_df, volume)

        # 볼린저밴드
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger(ohlcv_df)
        bb_position = self.analyze_bollinger_position(current_price, bb_upper, bb_middle, bb_lower)

        # 가격 위치
        price_position = self.analyze_price_position(ohlcv_df, current_price)

        # 밸류에이션
        valuation = self.analyze_valuation(fundamental)

        # 기술적 지표
        rsi = self.calculate_rsi(ohlcv_df)
        macd, macd_signal, macd_hist = self.calculate_macd(ohlcv_df)
        stoch_k, stoch_d = self.calculate_stochastic(ohlcv_df)

        indicators = TechnicalIndicators(
            ma5=float(ohlcv_df["close"].tail(5).mean()) if len(ohlcv_df) >= 5 else current_price,
            ma10=float(ohlcv_df["close"].tail(10).mean()) if len(ohlcv_df) >= 10 else current_price,
            ma20=price_position.ma_20,
            ma60=price_position.ma_60,
            ma120=price_position.ma_120,
            rsi14=rsi,
            macd=macd,
            macd_signal=macd_signal,
            macd_hist=macd_hist,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
        )

        # 분봉 데이터 변환
        candles_1m = []
        if not intraday_1m.empty:
            for idx, row in intraday_1m.tail(30).iterrows():
                candles_1m.append(CandleData(
                    time=idx.strftime("%H:%M"),
                    open=int(row["open"]),
                    high=int(row["high"]),
                    low=int(row["low"]),
                    close=int(row["close"]),
                    volume=int(row["volume"]),
                ))

        candles_5m = []
        if not intraday_5m.empty:
            for idx, row in intraday_5m.tail(30).iterrows():
                candles_5m.append(CandleData(
                    time=idx.strftime("%H:%M"),
                    open=int(row["open"]),
                    high=int(row["high"]),
                    low=int(row["low"]),
                    close=int(row["close"]),
                    volume=int(row["volume"]),
                ))

        # 매수 신호 분석
        buy_signal = self.generate_buy_signal(
            supply_7d, supply_30d, volume_analysis, bb_position,
            price_position, rsi, change_rate
        )

        # 종합 요약 생성
        summary_parts = []
        summary_parts.append(f"[{buy_signal.grade}등급] {buy_signal.recommendation}")
        if buy_signal.positives:
            summary_parts.append(f"긍정: {', '.join(buy_signal.positives[:2])}")
        if buy_signal.negatives:
            summary_parts.append(f"주의: {', '.join(buy_signal.negatives[:2])}")
        summary = " | ".join(summary_parts)

        return StockDetail(
            code=code,
            name=name,
            current_price=current_price,
            change_rate=change_rate,
            change_amount=change_amount,
            volume=volume,
            trading_value=trading_value,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            prev_close=prev_close,
            supply_3d=supply_3d,
            supply_7d=supply_7d,
            supply_10d=supply_10d,
            supply_30d=supply_30d,
            volume_analysis=volume_analysis,
            bb_position=bb_position,
            price_position=price_position,
            valuation=valuation,
            indicators=indicators,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            buy_signal=buy_signal,
            summary=summary
        )


# 전역 인스턴스
_analyzer: Optional[StockAnalyzer] = None


def get_stock_analyzer() -> StockAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = StockAnalyzer()
    return _analyzer


async def main():
    """테스트"""
    analyzer = StockAnalyzer()

    print("="*70)
    print("종목 상세 분석 테스트: 삼성전자 (005930)")
    print("="*70)

    detail = await analyzer.get_stock_detail("005930", "삼성전자")

    print(f"\n[기본 정보]")
    print(f"종목: {detail.name} ({detail.code})")
    print(f"현재가: {detail.current_price:,}원 ({detail.change_rate:+.2f}%)")
    print(f"거래량: {detail.volume:,}")
    print(f"거래대금: {detail.trading_value:,}백만원")

    print(f"\n[수급 분석]")
    print(f"  3일: {detail.supply_3d.trend} (외인 {detail.supply_3d.foreign_total/100000000:+,.0f}억, 기관 {detail.supply_3d.inst_total/100000000:+,.0f}억)")
    print(f"  7일: {detail.supply_7d.trend} (외인 {detail.supply_7d.foreign_total/100000000:+,.0f}억, 기관 {detail.supply_7d.inst_total/100000000:+,.0f}억)")
    print(f" 30일: {detail.supply_30d.trend} (외인 {detail.supply_30d.foreign_total/100000000:+,.0f}억, 기관 {detail.supply_30d.inst_total/100000000:+,.0f}억)")

    print(f"\n[거래량 분석]")
    print(f"  {detail.volume_analysis.comment}")
    print(f"  5일평균 대비: {detail.volume_analysis.ratio_vs_5d:.1f}배")

    print(f"\n[볼린저밴드]")
    print(f"  위치: {detail.bb_position.zone} ({detail.bb_position.position_pct:.0f}%)")
    print(f"  {detail.bb_position.comment}")

    print(f"\n[가격 위치]")
    print(f"  52주 고점 대비: {detail.price_position.from_high_pct:.1f}%")
    print(f"  52주 저점 대비: {detail.price_position.from_low_pct:+.1f}%")
    print(f"  {detail.price_position.position_comment}")

    print(f"\n[밸류에이션]")
    print(f"  시가총액: {detail.valuation.market_cap:,}억")
    print(f"  PER: {detail.valuation.per:.1f}배 / PBR: {detail.valuation.pbr:.2f}배")
    print(f"  {detail.valuation.comment}")

    print(f"\n[기술적 지표]")
    print(f"  RSI: {detail.indicators.rsi14:.1f}")
    print(f"  MACD: {detail.indicators.macd:.0f} (Sig: {detail.indicators.macd_signal:.0f})")
    print(f"  Stoch: %K={detail.indicators.stoch_k:.1f}, %D={detail.indicators.stoch_d:.1f}")

    print(f"\n[분봉 데이터]")
    print(f"  1분봉: {len(detail.candles_1m)}개")
    print(f"  5분봉: {len(detail.candles_5m)}개")

    print(f"\n[매수 신호]")
    print(f"  등급: {detail.buy_signal.grade} (점수: {detail.buy_signal.score})")
    print(f"  추천: {detail.buy_signal.recommendation}")
    print(f"  위험도: {detail.buy_signal.risk_level}")
    print(f"  긍정요인: {', '.join(detail.buy_signal.positives)}")
    print(f"  부정요인: {', '.join(detail.buy_signal.negatives)}")

    print(f"\n[종합 요약]")
    print(f"  {detail.summary}")


if __name__ == "__main__":
    asyncio.run(main())
