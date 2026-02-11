#!/usr/bin/env python3
"""OpenAI 기반 분봉 단타 전략 설계 + 즉시 검증 (v2: 가격 경로 분석 포함).

데이터 기반 접근:
1. Phase 1 패턴 분석 + 가격 경로(MAE/MFE) 분석 결과를 GPT-4.5에 전달
2. 데이터로 검증된 SL/TP 범위를 기반으로 전략 설계
3. V2 엔진으로 즉시 백테스트 검증
4. 실패 시 MAE/MFE 데이터와 함께 개선 요청 → 최대 10회 반복
5. In-sample(45일)/Out-of-sample(15일) 분리 검증

Output:
- src/strategies/data_driven/intraday_strategy_{1,2,3}.py
- reports/data_driven_strategy_design.json
"""

import importlib
import importlib.util
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

import pandas as pd
from openai import OpenAI
from sqlalchemy import text

from src.backtest.intraday_engine import IntradayBacktestConfig
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2
from src.database.connection import get_backtest_engine as get_engine
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ITERATIONS = 10
TARGET_WIN_RATE = 40.0
TARGET_RETURN = 5.0

# 검증된 최적 SL/TP (강제 적용 - GPT 출력 무시)
FORCED_STOP_LOSS = 0.03   # 3%
FORCED_TAKE_PROFIT = 0.05  # 5%

# 이미 채택된 전략 스킵 (인덱스 = 1-based)
SKIP_STRATEGIES = {1}  # 전략 1은 이미 +7.86%로 채택됨

STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"
REPORT_PATH = project_root / "reports" / "data_driven_strategy_design.json"

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.5-preview")

# ─── Working Example Strategy ────────────────────────────────────────────
WORKING_EXAMPLE = '''
"""Example: 거래량 급증 + 변동성 확대 전략 (100% 작동하는 예시)."""
import numpy as np
from src.strategies.intraday.base import IntradayStrategy, rolling_mean_np, rsi_np, vwap_np

class ExampleVolatilityStrategy(IntradayStrategy):
    """거래량 급증 시 변동성 확대 구간에서 진입하는 전략."""

    def __init__(self):
        super().__init__(name="example_volatility")
        self.min_bars = 15          # 최소 15번째 bar부터 진입 가능
        self.vol_surge_ratio = 1.5  # 평균 대비 1.5배 거래량
        self.atr_threshold = 0.005  # ATR이 0.5% 이상
        self.stop_loss_pct = 0.02   # 2% 손절
        self.take_profit_pct = 0.03 # 3% 익절

    def precompute_day(self, day_df):
        """하루치 지표를 numpy 배열로 사전계산."""
        ind = super().precompute_day(day_df)  # close, open, high, low, volume, timestamps, n_bars, rsi_14, vwap, vol_avg_20

        closes = ind["close"]
        highs = ind["high"]
        lows = ind["low"]
        n = ind["n_bars"]

        # ATR (10-bar) 계산
        atr = np.full(n, np.nan)
        for i in range(1, n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            if i >= 10:
                tr_sum = 0.0
                for j in range(i-9, i+1):
                    tr_sum += max(highs[j] - lows[j],
                                  abs(highs[j] - closes[j-1]),
                                  abs(lows[j] - closes[j-1]))
                atr[i] = (tr_sum / 10.0) / closes[i] if closes[i] > 0 else 0.0
        ind["atr_10_pct"] = atr

        # 시간 (hour) 배열 - timestamps에서 추출
        hours = np.array([ts.hour if hasattr(ts, 'hour') else 0 for ts in ind["timestamps"]])
        ind["hours"] = hours

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        """진입 조건 확인 (numpy 기반)."""
        if bar_idx < self.min_bars:
            return None

        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        closes = indicators["close"]
        volumes = indicators["volume"]
        vol_avg = indicators["vol_avg_20"]
        atr = indicators["atr_10_pct"]
        rsi = indicators["rsi_14"]
        hours = indicators["hours"]

        # 시간 필터: 9시~14시
        hour = hours[bar_idx]
        if hour < 9 or hour >= 14:
            return None

        # NaN 체크
        if np.isnan(vol_avg[bar_idx]) or vol_avg[bar_idx] <= 0:
            return None
        if np.isnan(atr[bar_idx]):
            return None
        if np.isnan(rsi[bar_idx]):
            return None

        # 조건 1: 거래량 급증
        vol_ratio = volumes[bar_idx] / vol_avg[bar_idx]
        if vol_ratio < self.vol_surge_ratio:
            return None

        # 조건 2: 변동성 확대
        if atr[bar_idx] < self.atr_threshold:
            return None

        # 조건 3: RSI 과매수 아님
        if rsi[bar_idx] > 70:
            return None

        # 조건 4: 양봉 (현재 close > open)
        if closes[bar_idx] <= indicators["open"][bar_idx]:
            return None

        return {
            "reason": f"vol_surge={vol_ratio:.1f}x, atr={atr[bar_idx]:.4f}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        """청산 조건 확인."""
        if bar_idx >= indicators["n_bars"]:
            return None

        rsi = indicators["rsi_14"]
        if not np.isnan(rsi[bar_idx]) and rsi[bar_idx] > 75:
            return "RSI과매수"

        # 2연속 음봉
        if bar_idx >= 2:
            closes = indicators["close"]
            opens = indicators["open"]
            if closes[bar_idx] < opens[bar_idx] and closes[bar_idx-1] < opens[bar_idx-1]:
                return "2연속음봉"

        return None

    def check_entry(self, code, current_bar, historical):
        return None

    def check_exit(self, position, current_bar, historical):
        return None
'''


def load_pattern_analysis() -> dict:
    """Phase 1 패턴 분석 결과 로드."""
    path = project_root / "reports" / "intraday_pattern_analysis.json"
    if not path.exists():
        raise FileNotFoundError(f"패턴 분석 결과 없음: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_price_path_analysis() -> dict:
    """가격 경로(MAE/MFE) 분석 결과 로드."""
    path = project_root / "reports" / "price_path_analysis.json"
    if not path.exists():
        raise FileNotFoundError(f"가격 경로 분석 결과 없음: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_intraday_data() -> dict[str, pd.DataFrame]:
    """DB에서 전체 분봉 데이터 로드."""
    engine = get_engine()

    with engine.connect() as conn:
        codes_result = conn.execute(text("""
            SELECT code, COUNT(*) as cnt
            FROM ohlcv_intraday
            GROUP BY code
            HAVING COUNT(*) >= 100
            ORDER BY cnt DESC
        """))
        codes = [row[0] for row in codes_result.fetchall()]

    logger.info(f"분봉 데이터 로드: {len(codes)}종목")

    data = {}
    with engine.connect() as conn:
        for code in codes:
            result = conn.execute(text("""
                SELECT datetime, open, high, low, close, volume
                FROM ohlcv_intraday
                WHERE code = :code
                ORDER BY datetime
            """), {"code": code})
            rows = result.fetchall()

            if rows:
                df = pd.DataFrame(
                    rows,
                    columns=["datetime", "open", "high", "low", "close", "volume"],
                )
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({
                    "open": float, "high": float, "low": float,
                    "close": float, "volume": float,
                })
                data[code] = df

    total_bars = sum(len(df) for df in data.values())
    logger.info(f"로드 완료: {len(data)}종목, 총 {total_bars:,}건")
    return data


def split_data_by_date(
    data: dict[str, pd.DataFrame],
    is_ratio: float = 0.75,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """데이터를 in-sample / out-of-sample로 분리."""
    all_dates = set()
    for df in data.values():
        all_dates.update(df.index.date)
    all_dates = sorted(all_dates)

    split_idx = int(len(all_dates) * is_ratio)
    is_dates = set(all_dates[:split_idx])
    oos_dates = set(all_dates[split_idx:])

    is_data = {}
    oos_data = {}

    for code, df in data.items():
        is_mask = df.index.map(lambda x: x.date() in is_dates)
        oos_mask = df.index.map(lambda x: x.date() in oos_dates)

        is_df = df[is_mask]
        oos_df = df[oos_mask]

        if not is_df.empty:
            is_data[code] = is_df
        if not oos_df.empty:
            oos_data[code] = oos_df

    logger.info(
        f"IS: {len(is_dates)}일 ({len(is_data)}종목), "
        f"OOS: {len(oos_dates)}일 ({len(oos_data)}종목)"
    )
    return is_data, oos_data


def build_deep_analysis_prompt(analysis: dict, price_path: dict) -> str:
    """패턴 분석 + 가격 경로 분석 결과를 포함한 심층 분석 프롬프트."""

    # Phase 1: 피처 예측력
    top_features = analysis.get("feature_predictive_power", [])[:15]
    features_table = "| 피처 | IC | 히트율 | 스프레드 | 급등평균 | 일반평균 |\n"
    features_table += "|------|----:|------:|--------:|--------:|--------:|\n"
    for fp in top_features:
        features_table += (
            f"| {fp['feature']} | {fp['ic']:+.4f} | {fp['top20_hit_rate']:.1%} | "
            f"{fp['spread']:+.4%} | {fp['surge_mean']:.4f} | {fp['normal_mean']:.4f} |\n"
        )

    top_combos = analysis.get("top_feature_combinations", [])[:20]
    combos_table = "| 피처 조합 | 히트율 | 평균수익 | 발생건수 |\n"
    combos_table += "|----------|------:|-------:|--------:|\n"
    for combo in top_combos:
        feats = " + ".join(combo["features"])
        combos_table += (
            f"| {feats} | {combo['hit_rate']:.1%} | "
            f"{combo['avg_return']:.3%} | {combo['count']} |\n"
        )

    # Phase 2: 가격 경로 분석
    percentiles = price_path.get("percentiles", {})
    pct_section = "| 피처 | p50 | p75 | p80 | p90 |\n"
    pct_section += "|------|----:|----:|----:|----:|\n"
    for feat, vals in percentiles.items():
        pct_section += (
            f"| {feat} | {vals['p50']:.6f} | {vals['p75']:.6f} | "
            f"{vals['p80']:.6f} | {vals['p90']:.6f} |\n"
        )

    # 조합별 가격 경로 요약
    combo_results = price_path.get("combinations", [])
    path_table = "| 조합 | 신호수 | 최적SL | 최적TP | 승률 | EV% | PF | 평균MAE(5bar) | 평균MFE(5bar) |\n"
    path_table += "|------|------:|------:|------:|----:|----:|---:|-----------:|-----------:|\n"
    for c in combo_results:
        opt = c.get("optimal_sl_tp", {})
        if not opt:
            continue
        mae_5 = c["price_path"]["avg_mae"][4] if len(c["price_path"]["avg_mae"]) > 4 else 0
        mfe_5 = c["price_path"]["avg_mfe"][4] if len(c["price_path"]["avg_mfe"]) > 4 else 0
        path_table += (
            f"| {c['name']} | {c['total_signals']:,} | "
            f"{opt['stop_loss']*100:.1f}% | {opt['take_profit']*100:.1f}% | "
            f"{opt['win_rate']*100:.1f}% | {opt['expected_value_pct']:+.4f}% | "
            f"{opt['profit_factor']:.3f} | {mae_5:+.3f}% | {mfe_5:+.3f}% |\n"
        )

    # 가격 경로 상세 (상위 3개 조합)
    path_details = ""
    top3 = sorted(
        [c for c in combo_results if c.get("optimal_sl_tp")],
        key=lambda x: x["optimal_sl_tp"]["expected_value_pct"],
        reverse=True,
    )[:3]

    for c in top3:
        path_details += f"\n### {c['name']} ({c['desc']})\n"
        path_details += f"- 조건: {c['conditions']}\n"
        path_details += f"- 신호 수: {c['total_signals']:,}건\n"

        opt = c["optimal_sl_tp"]
        path_details += f"- 최적 SL/TP: {opt['stop_loss']*100:.1f}% / {opt['take_profit']*100:.1f}%\n"
        path_details += f"- 승률: {opt['win_rate']*100:.1f}%, EV: {opt['expected_value_pct']:+.4f}%\n"
        path_details += f"- 평균 승: {opt['avg_win_pct']:+.3f}%, 평균 패: {opt['avg_loss_pct']:+.3f}%\n"

        # MAE 분포
        mae = c["price_path"]["mae"]
        path_details += f"- MAE 분포 (5bar 후): p25={mae['p25'][4]:+.3f}%, p50={mae['p50'][4]:+.3f}%, p75={mae['p75'][4]:+.3f}%\n"

        # MFE 분포
        mfe = c["price_path"]["mfe"]
        path_details += f"- MFE 분포 (5bar 후): p25={mfe['p25'][4]:+.3f}%, p50={mfe['p50'][4]:+.3f}%, p75={mfe['p75'][4]:+.3f}%\n"

        # SL/TP 그리드 일부
        grid = c.get("sl_tp_grid", [])
        if grid:
            path_details += "- SL/TP 그리드 상위 5:\n"
            sorted_grid = sorted(grid, key=lambda x: x["expected_value_pct"], reverse=True)[:5]
            for g in sorted_grid:
                path_details += (
                    f"  SL={g['stop_loss']*100:.1f}%/TP={g['take_profit']*100:.1f}% → "
                    f"WR={g['win_rate']*100:.1f}%, EV={g['expected_value_pct']:+.4f}%\n"
                )

    # 베이스라인
    baseline = price_path.get("baseline", {})
    baseline_opt = baseline.get("optimal_sl_tp", {})
    baseline_section = ""
    if baseline_opt:
        baseline_section = (
            f"\n### 베이스라인 (랜덤 진입)\n"
            f"- 신호 수: {baseline.get('total_signals', 0):,}건\n"
            f"- 최적 SL/TP: {baseline_opt.get('stop_loss', 0)*100:.1f}% / {baseline_opt.get('take_profit', 0)*100:.1f}%\n"
            f"- 승률: {baseline_opt.get('win_rate', 0)*100:.1f}%, EV: {baseline_opt.get('expected_value_pct', 0):+.4f}%\n"
        )

    stats = analysis.get("data_stats", {})

    return f"""당신은 한국 주식시장 분봉 단타 전문 퀀트입니다.

## 데이터 규모
- {stats.get('stocks', 986)}종목, {stats.get('trading_days', 60)}거래일
- 5분봉 총 {stats.get('total_records', 1922125):,}건

---

## A. 피처 예측력 분석 (급등 직전 vs 일반)

{features_table}

## B. 피처 조합 히트율 (30분 미래 수익률 기준)

{combos_table}

## C. 피처 백분위 분포 (데이터 기준)

{pct_section}

---

## D. 가격 경로(MAE/MFE) 분석 결과 ★핵심★

**MAE**: 진입 후 가격이 하락한 최대 폭 (손절에 걸릴 확률 결정)
**MFE**: 진입 후 가격이 상승한 최대 폭 (익절 목표 현실성 결정)

{path_table}

## E. 상위 3개 조합의 가격 경로 상세 분석

{path_details}

## F. 베이스라인 (랜덤 진입)
{baseline_section}

---

## 중요한 발견 (이전 실험에서 확인된 치명적 교훈!)

1. **0.2% 손절은 거의 항상 걸림**: 5분봉 1개에서도 0.2% 이상 하락이 빈번
2. **TP=0.7% 전략은 실전에서 반드시 실패**: 승률 61%여도 수익률 -20%. 1번 지면 4번 이겨야 본전
3. **SL=3%, TP=5%가 유일하게 가능성 있음**: 손익비 1:1.67, 승률 40%만 되면 수익
4. **거래 비용**: 수수료 0.015% 양방향 + 세금 0.23%(매도 시) → 건당 약 0.26% 비용
5. **수학적 계산**: TP=5%일 때 비용 후 순이익 ~4.74%, SL=3%일 때 순손실 ~3.03%
   → 손익분기 승률 = 3.03/(4.74+3.03) = 39%. 승률 45%면 건당 EV = +0.47%
   → 400건 × 0.47% = 복리로 +20%+ 가능!

---

## 요청 (★★★ 절대 규칙 ★★★)

위 데이터를 심층 분석하여:

1. **가장 유망한 3개 전략** 설계 (각각 서로 다른 시장 메커니즘)
2. **SL=3%, TP=5% 고정!** (모든 전략에 동일하게 적용. 다른 값 사용 절대 금지!)
3. **거래 비용(0.26%)을 고려**하여 승률 40%+ 이면 수익이 나는 구조
4. **목표: 462종목 × 60일 백테스트에서 +20% 이상 수익**
5. **과적합 방지**: 조건은 2~3개, 너무 구체적이면 OOS에서 실패
6. **전략 간 다양성**: 전략 1은 RSI 중립(이미 채택됨), 전략 2는 거래량 기반, 전략 3은 VWAP+모멘텀 기반으로 설계
7. **시간대 분산**: 각 전략이 다른 시간대를 커버하여 전체적으로 9시~14시를 폭넓게 커버

**핵심**: TP >= 3%인 전략만 설계하세요. TP < 3%는 절대 금지입니다.

응답은 JSON:
{{
    "pattern_interpretation": "데이터에서 발견한 핵심 패턴 해석",
    "price_path_insights": "MAE/MFE 분석에서 얻은 핵심 인사이트",
    "cost_adjusted_analysis": "거래 비용 고려 후 실제 수익성 분석",
    "strategies": [
        {{
            "name": "strategy_name_snake_case",
            "description": "전략 설명",
            "mechanism": "포착하는 시장 메커니즘",
            "entry_conditions": ["조건1", "조건2"],
            "exit_conditions": ["조건1", "조건2"],
            "stop_loss_pct": 0.03,
            "take_profit_pct": 0.05,
            "time_filter": "유효 시간대",
            "data_basis": "이 SL/TP를 선택한 데이터 근거",
            "expected_win_rate": 45,
            "expected_ev_pct": 0.4,
            "confidence": 0.7
        }}
    ]
}}

**★★★ 절대 규칙: 3개 전략 모두 stop_loss_pct=0.03(3%), take_profit_pct=0.05(5%)로 고정! 다른 값 사용 금지! ★★★**
**SL=2%/TP=3%는 실전에서 실패 확인됨 → 절대 사용하지 마세요!**"""


def build_code_generation_prompt(
    strategy_spec: dict,
    strategy_number: int,
    price_path: dict,
) -> str:
    """전략 스펙 + 작동 예시 + 가격 경로 데이터를 포함한 코드 생성 프롬프트."""

    # 해당 전략에 관련된 가격 경로 데이터 요약
    pct = price_path.get("percentiles", {})
    pct_summary = ""
    for feat, vals in pct.items():
        pct_summary += f"- {feat}: p50={vals['p50']:.6f}, p75={vals['p75']:.6f}, p90={vals['p90']:.6f}\n"

    return f"""아래 전략 스펙을 IntradayStrategy 서브클래스로 구현해주세요.

## 전략 스펙
- 이름: {strategy_spec['name']}
- 설명: {strategy_spec['description']}
- 메커니즘: {strategy_spec['mechanism']}
- 진입 조건: {json.dumps(strategy_spec['entry_conditions'], ensure_ascii=False)}
- 청산 조건: {json.dumps(strategy_spec['exit_conditions'], ensure_ascii=False)}
- 손절: {strategy_spec['stop_loss_pct']*100:.1f}%
- 익절: {strategy_spec['take_profit_pct']*100:.1f}%
- 시간 필터: {strategy_spec.get('time_filter', '9시-14시')}
- 데이터 근거: {strategy_spec.get('data_basis', 'N/A')}

## 데이터로 검증된 피처 백분위 (임계값 설정 기준!)
{pct_summary}
→ 예: atr_10의 p75 = 0.005389이면, "상위 25% 변동성"은 atr >= 0.0054
→ vol_ratio_avg20의 p75 = 1.166이면, "거래량 급증"은 vol_ratio >= 1.17

## 100% 작동하는 예시 전략 (이 패턴을 정확히 따르세요!)
```python
{WORKING_EXAMPLE}
```

## 중요 규칙 (절대 어기지 마세요!)

1. **import**: `import numpy as np`와 `from src.strategies.intraday.base import IntradayStrategy, rolling_mean_np, rsi_np, vwap_np` 만 사용. pandas 절대 금지!
2. **super().__init__(name="전략명")** 호출 필수
3. **super().precompute_day(day_df)** 호출하여 기본 지표 포함 → ind 딕셔너리에 추가 지표 넣기
4. **indicators 딕셔너리 키**: close, open, high, low, volume, timestamps, n_bars, rsi_14, vwap, vol_avg_20 (모두 numpy 배열, float64)
5. **timestamps**: datetime 객체 리스트. hour 추출: `ts.hour if hasattr(ts, 'hour') else 0`
6. **check_entry_fast** 반환: 조건 미충족 → `None`, 충족 → `{{"reason": "...", "stop_loss": {strategy_spec['stop_loss_pct']}, "take_profit": {strategy_spec['take_profit_pct']}}}`
7. **check_exit_fast** 반환: 미충족 → `None`, 충족 → `"이유 문자열"`
8. **NaN 체크 필수**: `np.isnan()` 으로 모든 지표값 확인 후 사용
9. **bar_idx 범위 체크**: `if bar_idx < self.min_bars: return None`
10. **조건 임계값은 위 백분위 데이터를 참고!** 너무 엄격하면 거래 0건 → 462종목 × 44일에서 최소 200건+ 거래 필요
11. **check_entry()와 check_exit()**: 반드시 `return None` 으로 구현 (V2 엔진은 fast 경로만 사용)
12. **SL/TP는 반드시 {strategy_spec['stop_loss_pct']*100:.1f}% / {strategy_spec['take_profit_pct']*100:.1f}%** 사용 (데이터로 검증된 값!)

**코드만 반환. 마크다운 코드블록 없이 순수 Python만. 설명 텍스트 금지.**"""


def build_improvement_prompt(
    strategy_spec: dict,
    previous_code: str,
    metrics: dict,
    iteration: int,
    error_msg: str = "",
    price_path: dict = None,
    trades_detail: list = None,
    best_metrics: dict = None,
    best_code: str = None,
) -> str:
    """실패한 전략 개선 프롬프트 (거래 내역 + 최고 성과 포함)."""
    total_trades = metrics.get("total_trades", 0)

    if total_trades == 0:
        failure_analysis = """
## *** 치명적 문제: 거래가 0건입니다! ***
임계값을 크게 완화! 462종목 × 44일에서 최소 200건+ 거래 필요
"""
    elif total_trades < 50:
        failure_analysis = f"""
## 문제: 거래가 {total_trades}건으로 너무 적습니다.
→ 진입 조건 완화 필요. 최소 200건 이상.
"""
    elif metrics.get("win_rate", 0) < TARGET_WIN_RATE:
        failure_analysis = f"""
## 문제: 승률이 {metrics.get('win_rate', 0):.1f}%로 목표(40%) 미달
→ 진입 조건을 약간 완화하거나, 진입 시 양봉 확인 등 방향성 필터 추가
→ TP는 절대 줄이지 마세요!
"""
    else:
        failure_analysis = f"""
## 문제: 수익률이 {metrics.get('total_return_pct', 0):+.2f}%로 목표(+5%) 미달
→ 승률은 OK이지만 패배 시 손실이 크거나 거래비용이 수익을 잡아먹음
→ 진입 조건의 질을 높여서 평균 승폭을 키우세요
"""

    if error_msg:
        failure_analysis += f"\n## 실행 에러\n```\n{error_msg}\n```\n에러를 수정하세요.\n"

    # 거래 내역 분석 (핵심 추가!)
    trades_analysis = ""
    if trades_detail and len(trades_detail) > 0:
        wins = [t for t in trades_detail if t["pnl_pct"] > 0]
        losses = [t for t in trades_detail if t["pnl_pct"] <= 0]

        # 청산 이유별 분석
        exit_reasons = {}
        for t in trades_detail:
            reason = t.get("exit_reason", "unknown")
            if reason not in exit_reasons:
                exit_reasons[reason] = {"count": 0, "total_pnl": 0}
            exit_reasons[reason]["count"] += 1
            exit_reasons[reason]["total_pnl"] += t["pnl_pct"]

        trades_analysis = f"""
## 거래 내역 상세 분석 (이걸 보고 구체적으로 개선!)

- 승리 거래: {len(wins)}건, 평균 +{sum(t['pnl_pct'] for t in wins)/len(wins):.2f}% (있다면)
- 패배 거래: {len(losses)}건, 평균 {sum(t['pnl_pct'] for t in losses)/max(len(losses),1):.2f}%

### 청산 이유별 분석:
"""
        for reason, data in sorted(exit_reasons.items(), key=lambda x: x[1]["total_pnl"]):
            avg_pnl = data["total_pnl"] / data["count"]
            trades_analysis += f"- {reason}: {data['count']}건, 평균 {avg_pnl:+.2f}%, 총 {data['total_pnl']:+.2f}%\n"

        # 손실이 큰 거래 TOP 5
        worst = sorted(trades_detail, key=lambda t: t["pnl_pct"])[:5]
        trades_analysis += "\n### 최악의 거래 TOP 5:\n"
        for t in worst:
            trades_analysis += f"- {t['code']}: {t['pnl_pct']:+.2f}% ({t.get('exit_reason', '?')})\n"

    # 최고 성과 코드 정보
    best_info = ""
    if best_metrics and best_code and best_metrics.get("total_return_pct", -999) > metrics.get("total_return_pct", -999):
        best_info = f"""
## ★ 지금까지 최고 성과 (이 코드를 기반으로 개선!)
- 승률: {best_metrics.get('win_rate', 0):.1f}%
- 수익률: {best_metrics.get('total_return_pct', 0):+.2f}%
- 거래: {best_metrics.get('total_trades', 0)}건

이 코드가 더 좋았습니다. 이 코드를 기반으로 약간만 수정하세요:
```python
{best_code}
```
"""

    # 가격 경로 힌트
    path_hint = ""
    if price_path:
        pct = price_path.get("percentiles", {})
        if pct:
            path_hint = "\n## 피처 백분위\n"
            for feat, vals in pct.items():
                path_hint += f"- {feat}: p50={vals['p50']:.6f}, p75={vals['p75']:.6f}\n"

    base_code = best_code if best_info else previous_code

    return f"""이전 전략을 개선해주세요. 반복 {iteration}/{MAX_ITERATIONS}

## 최근 백테스트 결과
- 승률: {metrics.get('win_rate', 0):.1f}%
- 수익률: {metrics.get('total_return_pct', 0):+.2f}%
- 총 거래: {total_trades}건
- 평균 승: {metrics.get('avg_win', 0):.2f}%
- 평균 패: {metrics.get('avg_loss', 0):.2f}%
{failure_analysis}
{trades_analysis}
{best_info}
{path_hint}

## 개선할 코드
```python
{base_code}
```

## 개선 방향 (구체적으로!)
1. 위 거래 내역을 보고 **손실이 많은 이유를 제거**하세요
2. stop_loss로 인한 손실이 많으면 → 진입 조건에 "추세 확인" 추가 (직전 bar 양봉 등)
3. 장 마감 청산 손실이 많으면 → 마감 1시간 전 신규 진입 금지
4. **SL={strategy_spec['stop_loss_pct']*100:.1f}%, TP={strategy_spec['take_profit_pct']*100:.1f}%는 유지!**
5. 임계값만 미세 조정하세요 (큰 구조는 유지)

**개선된 전체 코드만 반환. 마크다운 코드블록 없이. 설명 금지.**"""


def get_openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 환경변수를 설정하세요.")
    return OpenAI(api_key=api_key)


def call_openai(client: OpenAI, prompt: str, is_json: bool = False) -> str:
    model = OPENAI_MODEL
    logger.info(f"    OpenAI 호출: model={model}")
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    # gpt-5.x uses max_completion_tokens, gpt-4o uses max_tokens
    if model.startswith("gpt-5"):
        kwargs["max_completion_tokens"] = 8000
    else:
        kwargs["max_tokens"] = 8000
    if is_json:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def save_strategy_code(code: str, strategy_number: int) -> Path:
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = STRATEGY_DIR / f"intraday_strategy_{strategy_number}.py"
    filepath.write_text(code, encoding="utf-8")
    return filepath


def load_and_instantiate_strategy(filepath: Path):
    """동적 로드 (매번 새로운 모듈명 사용하여 캐시 방지)."""
    module_name = f"dds_{filepath.stem}_{datetime.now().strftime('%H%M%S%f')}"
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from src.strategies.intraday.base import IntradayStrategy
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, IntradayStrategy)
            and attr is not IntradayStrategy
        ):
            return attr()

    raise ValueError(f"IntradayStrategy 서브클래스를 찾을 수 없음: {filepath}")


def run_backtest(strategy, data: dict[str, pd.DataFrame]) -> dict:
    config = IntradayBacktestConfig(
        initial_capital=5_000_000,
        max_positions=3,
        position_size=0.3,
    )
    engine = IntradayBacktestEngineV2(config)

    try:
        metrics, trades = engine.run(strategy, data, show_progress=False)
        return {
            "success": True,
            "metrics": metrics.to_dict(),
            "num_trades": len(trades),
            "trades_sample": [
                {
                    "code": t.code,
                    "pnl_pct": round(t.pnl_pct, 2),
                    "exit_reason": t.exit_reason,
                }
                for t in trades[:100]
            ],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def is_strategy_acceptable(metrics: dict) -> bool:
    return (
        metrics.get("win_rate", 0) >= TARGET_WIN_RATE
        and metrics.get("total_return_pct", 0) > TARGET_RETURN
        and metrics.get("total_trades", 0) >= 50
    )


def clean_code_response(code: str) -> str:
    if "```python" in code:
        code = code.split("```python", 1)[1]
        if "```" in code:
            code = code.split("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1]
        if "```" in code:
            code = code.split("```", 1)[0]
    return code.strip()


def syntax_check(code: str) -> str:
    try:
        compile(code, "<strategy>", "exec")
        return ""
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"


def main():
    logger.info("=" * 70)
    logger.info(f"OpenAI 기반 분봉 단타 전략 설계 (v2: 가격경로 포함)")
    logger.info(f"모델: {OPENAI_MODEL}")
    logger.info("=" * 70)

    # 패턴 분석 결과 로드
    logger.info("\n[1/5] 패턴 분석 + 가격 경로 분석 결과 로드...")
    analysis = load_pattern_analysis()
    price_path = load_price_path_analysis()

    logger.info(
        f"  패턴: 급등 {analysis['data_stats']['surge_events']}건, "
        f"피처 {analysis['data_stats']['feature_count']}개"
    )
    valid_combos = [c for c in price_path.get("combinations", []) if c.get("optimal_sl_tp")]
    logger.info(
        f"  가격경로: {len(valid_combos)}개 조합 분석 완료, "
        f"피처 백분위 {len(price_path.get('percentiles', {}))}개"
    )

    # DB 데이터 로드
    logger.info("\n[2/5] 분봉 데이터 로드...")
    data = load_intraday_data()
    is_data, oos_data = split_data_by_date(data)

    # OpenAI 클라이언트
    client = get_openai_client()

    # Step 1: 데이터 심층 분석 + 전략 스펙 설계
    logger.info(f"\n[3/5] {OPENAI_MODEL} 심층 분석 & 전략 설계...")
    deep_prompt = build_deep_analysis_prompt(analysis, price_path)
    logger.info(f"  프롬프트 길이: {len(deep_prompt):,} chars")

    deep_response = call_openai(client, deep_prompt, is_json=True)
    strategy_design = json.loads(deep_response)

    logger.info(f"\n  패턴 해석: {strategy_design.get('pattern_interpretation', 'N/A')[:300]}...")
    logger.info(f"\n  가격경로 인사이트: {strategy_design.get('price_path_insights', 'N/A')[:300]}...")
    logger.info(f"\n  비용분석: {strategy_design.get('cost_adjusted_analysis', 'N/A')[:300]}...")

    strategies = strategy_design.get("strategies", [])
    logger.info(f"\n  설계된 전략 수: {len(strategies)}")

    for i, s in enumerate(strategies, 1):
        logger.info(
            f"  전략 {i}: {s['name']} - {s['description'][:100]}\n"
            f"    SL={s['stop_loss_pct']*100:.1f}%, TP={s['take_profit_pct']*100:.1f}%, "
            f"예상 승률={s.get('expected_win_rate', '?')}%, "
            f"예상 EV={s.get('expected_ev_pct', '?')}%"
        )

    # Step 2: 전략 코드 생성 + 즉시 검증 반복
    logger.info("\n[4/5] 전략 코드 생성 & 즉시 검증...")

    design_results = {
        "timestamp": datetime.now().isoformat(),
        "model": OPENAI_MODEL,
        "deep_analysis": strategy_design,
        "price_path_percentiles": price_path.get("percentiles", {}),
        "strategies": {},
    }

    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)

    for strat_idx, strategy_spec in enumerate(strategies[:3], 1):
        # 이미 채택된 전략 스킵
        if strat_idx in SKIP_STRATEGIES:
            strat_name = strategy_spec["name"]
            logger.info(f"\n{'='*60}")
            logger.info(f"전략 {strat_idx}: {strat_name} - ★ SKIP (이미 채택됨) ★")
            logger.info(f"{'='*60}")
            continue

        # GPT가 어떤 SL/TP를 제안하든 검증된 값으로 강제 오버라이드
        strategy_spec["stop_loss_pct"] = FORCED_STOP_LOSS
        strategy_spec["take_profit_pct"] = FORCED_TAKE_PROFIT

        strat_name = strategy_spec["name"]
        logger.info(f"\n{'='*60}")
        logger.info(f"전략 {strat_idx}: {strat_name}")
        logger.info(f"  SL={strategy_spec['stop_loss_pct']*100:.1f}%, TP={strategy_spec['take_profit_pct']*100:.1f}% (강제 적용)")
        logger.info(f"{'='*60}")

        current_code = None
        best_metrics = None
        best_code = None
        last_error = ""
        last_metrics = None
        last_trades_detail = None

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info(f"\n  반복 {iteration}/{MAX_ITERATIONS}")

            if current_code is None:
                prompt = build_code_generation_prompt(strategy_spec, strat_idx, price_path)
            else:
                prompt = build_improvement_prompt(
                    strategy_spec, current_code, last_metrics or {},
                    iteration, last_error, price_path,
                    trades_detail=last_trades_detail,
                    best_metrics=best_metrics,
                    best_code=best_code,
                )

            try:
                raw_code = call_openai(client, prompt)
                code = clean_code_response(raw_code)

                syntax_err = syntax_check(code)
                if syntax_err:
                    logger.warning(f"    문법 에러: {syntax_err}")
                    last_error = syntax_err
                    current_code = code
                    continue

                current_code = code

                filepath = save_strategy_code(code, strat_idx)
                logger.info(f"    코드 저장됨")

                strategy_instance = load_and_instantiate_strategy(filepath)
                logger.info(f"    로드 성공: {strategy_instance.name}")
                last_error = ""

                # IN-SAMPLE 백테스트
                logger.info(f"    IS 백테스트...")
                is_result = run_backtest(strategy_instance, is_data)

                if not is_result["success"]:
                    last_error = is_result["error"]
                    logger.warning(f"    IS 실패: {last_error}")
                    last_metrics = {
                        "win_rate": 0, "total_return_pct": -100,
                        "total_trades": 0, "avg_win": 0, "avg_loss": 0,
                        "max_drawdown": 100,
                    }
                    last_trades_detail = None
                    continue

                is_metrics = is_result["metrics"]
                last_metrics = is_metrics
                last_trades_detail = is_result.get("trades_sample", [])

                logger.info(
                    f"    IS: 승률={is_metrics['win_rate']:.1f}%, "
                    f"수익률={is_metrics['total_return_pct']:+.2f}%, "
                    f"거래={is_metrics['total_trades']}건"
                )

                # 최고 성과 보존 (양수면 무조건 보존, 음수면 가장 덜 나쁜 것)
                is_better = (
                    best_metrics is None
                    or is_metrics["total_return_pct"] > best_metrics.get("total_return_pct", -999)
                )
                if is_better:
                    best_metrics = is_metrics
                    best_code = code
                    logger.info(f"    ★ 새로운 최고 성과! 수익률={is_metrics['total_return_pct']:+.2f}%")
                else:
                    logger.info(
                        f"    최고 성과 유지: {best_metrics.get('total_return_pct', 0):+.2f}% "
                        f"(이번: {is_metrics['total_return_pct']:+.2f}%)"
                    )

                last_error = ""

                if is_strategy_acceptable(is_metrics):
                    logger.info(f"    IS 목표 달성! OOS 검증...")
                    oos_strategy = load_and_instantiate_strategy(filepath)
                    oos_result = run_backtest(oos_strategy, oos_data)

                    if oos_result["success"]:
                        oos_metrics = oos_result["metrics"]
                        logger.info(
                            f"    OOS: 승률={oos_metrics['win_rate']:.1f}%, "
                            f"수익률={oos_metrics['total_return_pct']:+.2f}%, "
                            f"거래={oos_metrics['total_trades']}건"
                        )

                        if oos_metrics.get("total_return_pct", 0) > 0:
                            logger.info(f"    *** IS+OOS 통과! 채택 ***")
                            design_results["strategies"][strat_name] = {
                                "accepted": True,
                                "iterations": iteration,
                                "is_metrics": is_metrics,
                                "oos_metrics": oos_metrics,
                                "spec": strategy_spec,
                            }
                            break
                        else:
                            logger.info(f"    OOS 실패 (수익률 음수)")
                    else:
                        logger.warning(f"    OOS 에러: {oos_result['error']}")

            except Exception as e:
                last_error = str(e)
                logger.error(f"    에러: {e}")
                traceback.print_exc()
                best_metrics = best_metrics or {
                    "win_rate": 0, "total_return_pct": -100,
                    "total_trades": 0, "avg_win": 0, "avg_loss": 0,
                    "max_drawdown": 100,
                }

        if strat_name not in design_results["strategies"]:
            design_results["strategies"][strat_name] = {
                "accepted": False,
                "iterations": MAX_ITERATIONS,
                "is_metrics": best_metrics,
                "spec": strategy_spec,
            }

        if best_code:
            save_strategy_code(best_code, strat_idx)

    _generate_init_file(strategies[:3])

    # 결과 저장
    logger.info("\n[5/5] 결과 저장...")
    REPORT_PATH.parent.mkdir(exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(design_results, f, ensure_ascii=False, indent=2, default=str)

    # 최종 요약
    logger.info("\n" + "=" * 70)
    logger.info("전략 설계 완료 요약")
    logger.info("=" * 70)

    for name, result in design_results["strategies"].items():
        status = "ACCEPTED" if result["accepted"] else "FAILED"
        m = result.get("is_metrics") or {}
        logger.info(
            f"  {name}: [{status}] "
            f"승률={m.get('win_rate', 0):.1f}%, "
            f"수익률={m.get('total_return_pct', 0):+.2f}%, "
            f"반복={result['iterations']}회"
        )

    logger.info(f"\n결과: {REPORT_PATH}")
    logger.info(f"전략 코드: {STRATEGY_DIR}")
    logger.info("=" * 70)


def _generate_init_file(strategies: list[dict]):
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)

    imports = []
    classes = []

    for i in range(1, len(strategies) + 1):
        filepath = STRATEGY_DIR / f"intraday_strategy_{i}.py"
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("class ") and "IntradayStrategy" in line:
                    class_name = line.split("(")[0].replace("class ", "").strip()
                    imports.append(
                        f"from src.strategies.data_driven.intraday_strategy_{i} import {class_name}"
                    )
                    classes.append(class_name)
                    break

    init_content = '"""Data-driven intraday strategies designed by OpenAI."""\n\n'
    init_content += "\n".join(imports)
    init_content += "\n\n\ndef get_data_driven_strategies() -> list:\n"
    init_content += '    """Get instances of all data-driven strategies."""\n'
    init_content += "    return [\n"
    for cls in classes:
        init_content += f"        {cls}(),\n"
    init_content += "    ]\n\n\n"
    init_content += "__all__ = [\n"
    for cls in classes:
        init_content += f'    "{cls}",\n'
    init_content += '    "get_data_driven_strategies",\n'
    init_content += "]\n"

    init_path = STRATEGY_DIR / "__init__.py"
    init_path.write_text(init_content, encoding="utf-8")
    logger.info(f"  __init__.py 생성: {init_path}")


if __name__ == "__main__":
    main()
