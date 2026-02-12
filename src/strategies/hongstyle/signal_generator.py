"""시그널 생성 - 홍인기 매매법 기반 진입/청산 판단"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from .daily_chart_analyzer import DailyPosition, KiScore
from .pattern_detector import PatternAlert
from .sector_analyzer import SectorInfo


@dataclass
class EntrySignal:
    """진입 시그널"""
    action: str          # "buy", "wait", "skip"
    method: str          # "돌파매매", "눌림매매", "D+0", "없음"
    confidence: float    # 0.0 ~ 1.0
    reason: str
    stop_loss: float = 0.04    # -4% 기본 손절
    take_profit: float = 0.05  # +5% 기본 1차 익절


@dataclass
class ExitSignal:
    """청산 시그널"""
    action: str          # "sell", "partial_sell", "hold"
    portion: float       # 0.0 ~ 1.0 (매도 비율)
    reason: str
    urgency: str = "normal"  # "urgent", "normal", "low"


@dataclass
class DPlusCandidate:
    """D+1/D+2 후보 종목"""
    code: str
    name: str
    d_day: int           # 0: 당일, 1: D+1, 2: D+2
    change_rate: float   # 전일 등락률
    trading_value: int   # 거래대금
    reason: str


class SignalGenerator:
    """진입/청산 시그널 생성기"""

    # 손절 기준
    STOP_LOSS_PCT = 0.04        # -4%
    # 1차 익절 기준
    TAKE_PROFIT_1_PCT = 0.05    # +5% (70% 물량)
    # 1차 익절 비율
    PARTIAL_SELL_RATIO = 0.7
    # D+ 후보 최소 상승률
    DPLUS_MIN_CHANGE = 5.0      # +5%

    def generate_entry_signal(
        self,
        stock_code: str,
        daily_position: DailyPosition,
        ki_score: KiScore,
        patterns: list[PatternAlert],
        is_leader: bool,
        sector_info: Optional[SectorInfo] = None,
    ) -> EntrySignal:
        """
        진입 시그널 생성

        돌파 매매: 신고가 + 유동성 장세 + 패턴 없음
        눌림 매매: 매물대 밀집 + 눌림 후 반등
        D+0: 장대양봉 발생일 진입
        """
        try:
            # 위험 패턴이 있으면 진입 보류
            high_severity = [
                p for p in patterns if p.severity == "high"
            ]
            if high_severity:
                pattern_names = ", ".join(p.pattern_name for p in high_severity)
                return EntrySignal(
                    action="skip",
                    method="없음",
                    confidence=0.2,
                    reason=f"위험 패턴 감지: {pattern_names}",
                )

            # 끼가 너무 낮으면 스킵
            if ki_score.score < 20:
                return EntrySignal(
                    action="skip",
                    method="없음",
                    confidence=0.3,
                    reason=f"끼 부족 ({ki_score.score:.0f}/100) - 변동성 부족 종목",
                )

            # 대장주가 아니면 신중
            if not is_leader:
                confidence_penalty = 0.2
            else:
                confidence_penalty = 0.0

            # 일봉 자리별 매매법 결정
            pos_type = daily_position.position_type

            if pos_type == "신고가":
                return EntrySignal(
                    action="buy",
                    method="돌파매매",
                    confidence=max(0.8 - confidence_penalty, 0.4),
                    reason=(
                        f"신고가 돌파 매매 - {daily_position.description}. "
                        f"끼 {ki_score.score:.0f}점"
                        + (" | 대장주" if is_leader else "")
                    ),
                    stop_loss=self.STOP_LOSS_PCT,
                    take_profit=self.TAKE_PROFIT_1_PCT,
                )

            if pos_type == "전고점돌파":
                return EntrySignal(
                    action="buy",
                    method="돌파매매",
                    confidence=max(0.75 - confidence_penalty, 0.4),
                    reason=(
                        f"전고점 돌파 매매 - {daily_position.description}. "
                        f"끼 {ki_score.score:.0f}점"
                    ),
                    stop_loss=self.STOP_LOSS_PCT,
                    take_profit=self.TAKE_PROFIT_1_PCT,
                )

            if pos_type == "빈집":
                return EntrySignal(
                    action="buy",
                    method="돌파매매",
                    confidence=max(0.7 - confidence_penalty, 0.35),
                    reason=(
                        f"빈집 구간 돌파 - {daily_position.description}. "
                        f"매물대 얇아 빠른 상승 기대"
                    ),
                    stop_loss=self.STOP_LOSS_PCT,
                    take_profit=self.TAKE_PROFIT_1_PCT,
                )

            if pos_type == "바닥반등":
                return EntrySignal(
                    action="buy",
                    method="눌림매매",
                    confidence=max(0.6 - confidence_penalty, 0.3),
                    reason=(
                        f"바닥 반등 매매 - {daily_position.description}. "
                        f"MA20 돌파 확인"
                    ),
                    stop_loss=self.STOP_LOSS_PCT,
                    take_profit=self.TAKE_PROFIT_1_PCT,
                )

            return EntrySignal(
                action="wait",
                method="없음",
                confidence=0.3,
                reason=f"명확한 자리 아님 - {daily_position.description}",
            )

        except Exception as e:
            logger.error(f"진입 시그널 생성 실패 ({stock_code}): {e}")
            return EntrySignal(
                action="skip",
                method="없음",
                confidence=0.0,
                reason=f"시그널 생성 오류: {e}",
            )

    def generate_exit_signal(
        self,
        entry_price: float,
        current_price: float,
        patterns: list[PatternAlert],
        position_info: Optional[dict] = None,
    ) -> ExitSignal:
        """
        청산 시그널 생성

        손절: 전저점 이탈 OR -4%
        1차 익절(70%): +3~5%
        2차 본전컷(30%): 수익 전환 후 원가 복귀
        고점 시그널: 최대거래량 + 윗꼬리 음봉
        """
        try:
            if entry_price <= 0:
                return ExitSignal(
                    action="hold",
                    portion=0.0,
                    reason="매입가 정보 없음",
                )

            pnl_rate = (current_price - entry_price) / entry_price

            # 1. 손절 체크 (-4%)
            if pnl_rate <= -self.STOP_LOSS_PCT:
                return ExitSignal(
                    action="sell",
                    portion=1.0,
                    reason=f"손절 ({pnl_rate * 100:+.1f}%) - 원칙 준수 전량 매도",
                    urgency="urgent",
                )

            # 2. 고점 패턴 감지 → 즉시 매도
            high_patterns = [
                p for p in patterns
                if p.severity == "high" and p.pattern_name in ("거래량고점", "끼소진", "가분수")
            ]
            if high_patterns and pnl_rate > 0:
                pattern_names = ", ".join(p.pattern_name for p in high_patterns)
                return ExitSignal(
                    action="sell",
                    portion=1.0,
                    reason=f"고점 시그널 ({pattern_names}) - 수익 확보 전량 매도",
                    urgency="urgent",
                )

            # 3. 1차 익절 (+5%)
            already_partial = (position_info or {}).get("partial_sold", False)
            if pnl_rate >= self.TAKE_PROFIT_1_PCT and not already_partial:
                return ExitSignal(
                    action="partial_sell",
                    portion=self.PARTIAL_SELL_RATIO,
                    reason=(
                        f"1차 익절 ({pnl_rate * 100:+.1f}%) - "
                        f"{self.PARTIAL_SELL_RATIO * 100:.0f}% 물량 매도"
                    ),
                )

            # 4. 2차 본전컷 (부분매도 후 원가 복귀)
            if already_partial and pnl_rate <= 0.005:
                return ExitSignal(
                    action="sell",
                    portion=1.0,
                    reason="본전컷 - 1차 익절 후 원가 복귀, 잔여 물량 청산",
                )

            # 5. 3파동 완료 시 주의
            three_wave = [
                p for p in patterns if p.pattern_name == "3파동"
            ]
            if three_wave and pnl_rate > 0.02:
                return ExitSignal(
                    action="partial_sell",
                    portion=0.5,
                    reason=f"3파동 완성 - 추가 상승 제한적, 50% 익절 ({pnl_rate * 100:+.1f}%)",
                )

            return ExitSignal(
                action="hold",
                portion=0.0,
                reason=f"보유 유지 (수익률 {pnl_rate * 100:+.1f}%)",
            )

        except Exception as e:
            logger.error(f"청산 시그널 생성 실패: {e}")
            return ExitSignal(
                action="hold",
                portion=0.0,
                reason=f"시그널 생성 오류: {e}",
            )

    def generate_dplus_candidates(
        self, daily_bars_all_stocks: dict[str, pd.DataFrame]
    ) -> list[DPlusCandidate]:
        """
        D+1/D+2 후보 종목 생성

        전일 장대양봉(+5% 이상) + 거래대금 상위 종목
        """
        candidates: list[DPlusCandidate] = []

        try:
            for code, df in daily_bars_all_stocks.items():
                if df is None or df.empty or len(df) < 2:
                    continue

                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 2 else None

                close = float(latest.get("close", 0))
                open_price = float(latest.get("open", 0))
                volume = float(latest.get("volume", 0))
                value = float(latest.get("value", 0))
                name = str(latest.get("name", code))

                if open_price <= 0:
                    continue

                change_rate = ((close - open_price) / open_price) * 100

                # D+1 후보: 전일 +5% 이상 장대양봉
                if change_rate >= self.DPLUS_MIN_CHANGE:
                    reason_parts = [f"장대양봉 +{change_rate:.1f}%"]
                    if value > 10_000_000_000:
                        reason_parts.append("거래대금 상위")

                    candidates.append(DPlusCandidate(
                        code=code,
                        name=name,
                        d_day=1,
                        change_rate=round(change_rate, 2),
                        trading_value=int(value),
                        reason=" | ".join(reason_parts),
                    ))

                    # D+2 후보: D+1 + 전전일도 양봉이면
                    if prev is not None:
                        prev_close = float(prev.get("close", 0))
                        prev_open = float(prev.get("open", 0))
                        if prev_open > 0 and prev_close > prev_open:
                            candidates.append(DPlusCandidate(
                                code=code,
                                name=name,
                                d_day=2,
                                change_rate=round(change_rate, 2),
                                trading_value=int(value),
                                reason=f"2일 연속 양봉 | D+2 관전 포인트",
                            ))

        except Exception as e:
            logger.error(f"D+ 후보 생성 실패: {e}")

        # 거래대금 순 정렬
        candidates.sort(key=lambda x: x.trading_value, reverse=True)
        return candidates[:20]
