#!/usr/bin/env python3
"""성공한 전략 1의 변형을 GPT-4o로 생성하는 스크립트.

전략 1 (morning_rsi_neutral_atr)이 +7.86%로 유일하게 성공.
핵심 성공 요인: RSI 40-60 중립 필터 + ATR 상위 25% + 직전 bar 양봉

이 스크립트는:
1. 성공 전략의 코드와 결과를 GPT에 보여줌
2. 시간대/필터를 변형한 2개 추가 전략 생성 요청
3. SL=3%/TP=5% 고정, RSI 중립 필터 필수 유지
4. V2 엔진으로 즉시 검증 + 반복 개선
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
TARGET_WIN_RATE = 39.0  # 수학적 손익분기 38.96%
TARGET_RETURN = 3.0

STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

WINNING_STRATEGY_CODE = '''import numpy as np
from src.strategies.intraday.base import IntradayStrategy, rolling_mean_np, rsi_np, vwap_np

class MorningRSINeutralATRStrategy(IntradayStrategy):
    """오전 9시에서 11시 사이 RSI가 중립 영역(40-60)에 있고 ATR이 상위 25%인 경우 진입하는 전략."""

    def __init__(self):
        super().__init__(name="morning_rsi_neutral_atr")
        self.min_bars = 15
        self.atr_threshold = 0.005389
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.05

    def precompute_day(self, day_df):
        ind = super().precompute_day(day_df)
        closes = ind["close"]
        highs = ind["high"]
        lows = ind["low"]
        opens = ind["open"]
        n = ind["n_bars"]

        atr = np.full(n, np.nan)
        for i in range(1, n):
            if i >= 10:
                tr_sum = 0.0
                for j in range(i-9, i+1):
                    tr_sum += max(highs[j] - lows[j],
                                  abs(highs[j] - closes[j-1]),
                                  abs(lows[j] - closes[j-1]))
                atr[i] = (tr_sum / 10.0) / closes[i] if closes[i] > 0 else 0.0
        ind["atr_10_pct"] = atr

        hours = np.array([ts.hour if hasattr(ts, 'hour') else 0 for ts in ind["timestamps"]])
        ind["hours"] = hours

        bullish_candle = closes > opens
        ind["bullish_candle"] = bullish_candle

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        if bar_idx < self.min_bars:
            return None
        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        atr = indicators["atr_10_pct"]
        rsi = indicators["rsi_14"]
        hours = indicators["hours"]
        bullish_candle = indicators["bullish_candle"]

        hour = hours[bar_idx]
        if hour < 9 or hour >= 11:
            return None
        if np.isnan(atr[bar_idx]) or np.isnan(rsi[bar_idx]):
            return None
        if atr[bar_idx] < self.atr_threshold:
            return None
        if rsi[bar_idx] < 40 or rsi[bar_idx] > 60:
            return None
        if not bullish_candle[bar_idx - 1]:
            return None

        return {
            "reason": f"rsi_neutral={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        return None
    def check_entry(self, code, current_bar, historical):
        return None
    def check_exit(self, position, current_bar, historical):
        return None
'''

WINNING_METRICS = {
    "win_rate": 40.6,
    "total_return_pct": 7.86,
    "total_trades": 130,
    "time_window": "9-11시",
    "key_filters": "RSI 40-60 + ATR >= 0.005389 + 직전 bar 양봉",
}

VARIATION_SPECS = [
    # 전략 2: 이미 +6.33%로 성공했으므로 스킵
    # {
    #     "number": 2,
    #     "class_name_hint": "MiddayRSIVolumeATRStrategy",
    #     "time_window": "11-13시",
    #     "additional_filter": "거래량 급증 (vol_ratio >= 1.17)",
    #     "description": "점심 시간대(11-13시) RSI 중립 + 거래량 급증 + ATR 높음",
    # },
    {
        "number": 3,
        "class_name_hint": "WideDayRSIVWAPATRStrategy",
        "time_window": "9-14시 (넓은 시간대, 14시 이후 진입 금지)",
        "additional_filter": "VWAP 위 (close > vwap) + 직전 2bar 연속 양봉 (강한 모멘텀)",
        "description": "전일 시간대(9-14시) RSI 중립 + VWAP 위 + ATR 높음 + 2연속 양봉",
    },
]


def build_variation_prompt(spec: dict, iteration: int = 1,
                           prev_code: str = None, prev_metrics: dict = None,
                           trades_detail: list = None,
                           best_code: str = None, best_metrics: dict = None) -> str:
    """성공 전략 기반 변형 코드 생성 프롬프트."""

    base_info = f"""## 성공한 전략 1 (이 코드가 +7.86% 수익을 냄!)

```python
{WINNING_STRATEGY_CODE}
```

### 성공 이유 분석:
- **RSI 40-60 (중립)**: 과매수/과매도에서 진입하지 않음 → 방향성 불확실 구간 배제
- **ATR >= 0.005389 (상위 25%)**: 충분한 변동성이 있어야 5% TP에 도달 가능
- **직전 bar 양봉**: 단기 상승 모멘텀 확인
- **9-11시**: 장 초반 유동성이 높은 시간대
- 결과: 승률 40.6%, 130건 거래, +7.86% 수익

### 핵심 수학:
- SL=3%, TP=5%: 비용 후 순이익 4.74%, 순손실 3.03%
- 손익분기 승률 = 39%. 승률 40%+ 이면 양수
"""

    variation_info = f"""## 요청: 전략 {spec['number']} 변형 생성

- **시간대**: {spec['time_window']}
- **추가 필터**: {spec['additional_filter']}
- **설명**: {spec['description']}
- **SL=3%, TP=5% 고정 (절대 변경 금지!)**
- **RSI 40-60 중립 필터 반드시 포함!** (이것이 성공의 핵심)
- **ATR >= 0.005389 필터 반드시 포함!**
- **직전 bar 양봉 확인 반드시 포함!**

### 사용 가능한 indicators 키:
- close, open, high, low, volume: numpy float64 배열
- timestamps: datetime 객체 리스트
- n_bars: int
- rsi_14: numpy float64 (이미 계산됨)
- vwap: numpy float64 (이미 계산됨)
- vol_avg_20: numpy float64 (이미 계산됨, 20-bar 이동 평균 거래량)

### 피처 백분위 (임계값 참고):
- atr_10: p75=0.005389, p90=0.008057
- vol_ratio_avg20: p75=1.166119, p90=1.903984
"""

    iteration_info = ""
    if prev_code and prev_metrics and iteration > 1:
        wr = prev_metrics.get("win_rate", 0)
        ret = prev_metrics.get("total_return_pct", 0)
        trades = prev_metrics.get("total_trades", 0)

        iteration_info = f"""
## 이전 시도 결과 (반복 {iteration}/{MAX_ITERATIONS})
- 승률: {wr:.1f}%, 수익률: {ret:+.2f}%, 거래: {trades}건
"""
        if trades == 0:
            iteration_info += "→ ★ 거래 0건! 조건이 너무 엄격합니다. 임계값을 대폭 완화하세요!\n"
        elif trades < 50:
            iteration_info += f"→ 거래가 {trades}건으로 부족. 조건 완화 필요 (최소 100건+)\n"
        elif wr < 39:
            iteration_info += "→ 승률이 39% 미만. 진입 시 방향성 필터 강화 (연속 양봉, RSI 범위 조정 등)\n"
        elif ret < 0:
            iteration_info += "→ 승률은 OK이지만 수익률 음수. 진입 조건의 질을 높이세요.\n"

        # 거래 상세 분석
        if trades_detail:
            wins = [t for t in trades_detail if t["pnl_pct"] > 0]
            losses = [t for t in trades_detail if t["pnl_pct"] <= 0]

            exit_reasons = {}
            for t in trades_detail:
                reason = t.get("exit_reason", "unknown")
                if reason not in exit_reasons:
                    exit_reasons[reason] = {"count": 0, "total_pnl": 0}
                exit_reasons[reason]["count"] += 1
                exit_reasons[reason]["total_pnl"] += t["pnl_pct"]

            iteration_info += f"\n### 거래 상세:\n"
            iteration_info += f"- 승리: {len(wins)}건 (평균 {sum(t['pnl_pct'] for t in wins)/max(len(wins),1):+.2f}%)\n"
            iteration_info += f"- 패배: {len(losses)}건 (평균 {sum(t['pnl_pct'] for t in losses)/max(len(losses),1):+.2f}%)\n"

            for reason, data in sorted(exit_reasons.items(), key=lambda x: x[1]["total_pnl"]):
                avg = data["total_pnl"] / data["count"]
                iteration_info += f"- {reason}: {data['count']}건, 평균 {avg:+.2f}%\n"

        # 최고 성과 코드
        if best_code and best_metrics:
            best_ret = best_metrics.get("total_return_pct", -999)
            if best_ret > ret:
                iteration_info += f"""
### ★ 최고 성과 코드 (수익률 {best_ret:+.2f}%) - 이것을 기반으로 개선!
```python
{best_code}
```
"""

        iteration_info += f"""
### 이전 코드:
```python
{prev_code}
```

**이전 코드를 분석하고, 구체적으로 어떤 조건을 어떻게 변경해야 승률이 올라가는지 생각한 후 수정하세요.**
**단, RSI 40-60, ATR >= 0.005389, SL=3%, TP=5%는 절대 변경하지 마세요!**
**임계값 미세조정만 하세요. 큰 구조 변경은 금지!**
"""

    return f"""{base_info}
{variation_info}
{iteration_info}

## 규칙 (절대 어기지 마세요!)
1. IntradayStrategy 상속, super().__init__(name="전략명") 호출
2. super().precompute_day(day_df) 호출 → ind에 추가 지표 넣기
3. SL=0.03, TP=0.05 고정!
4. RSI 40-60 중립 필터 반드시 포함!
5. NaN 체크 필수
6. bar_idx < min_bars 체크 필수
7. check_entry(), check_exit()는 return None
8. import는 numpy와 base만 사용

**코드만 반환. 마크다운 코드블록 없이 순수 Python만. 설명 금지.**"""


def load_intraday_data() -> dict[str, pd.DataFrame]:
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
                df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
                data[code] = df

    total = sum(len(df) for df in data.values())
    logger.info(f"로드 완료: {len(data)}종목, 총 {total:,}건")
    return data


def split_data_by_date(data, is_ratio=0.75):
    all_dates = set()
    for df in data.values():
        all_dates.update(df.index.date)
    all_dates = sorted(all_dates)
    split_idx = int(len(all_dates) * is_ratio)
    is_dates = set(all_dates[:split_idx])
    oos_dates = set(all_dates[split_idx:])

    is_data, oos_data = {}, {}
    for code, df in data.items():
        is_mask = df.index.map(lambda x: x.date() in is_dates)
        oos_mask = df.index.map(lambda x: x.date() in oos_dates)
        is_df, oos_df = df[is_mask], df[oos_mask]
        if not is_df.empty:
            is_data[code] = is_df
        if not oos_df.empty:
            oos_data[code] = oos_df

    logger.info(f"IS: {len(is_dates)}일 ({len(is_data)}종목), OOS: {len(oos_dates)}일 ({len(oos_data)}종목)")
    return is_data, oos_data


def get_openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 환경변수를 설정하세요.")
    return OpenAI(api_key=api_key)


def call_openai(client: OpenAI, prompt: str) -> str:
    model = OPENAI_MODEL
    logger.info(f"    OpenAI 호출: model={model}")
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    if model.startswith("gpt-5"):
        kwargs["max_completion_tokens"] = 6000
    else:
        kwargs["max_tokens"] = 6000

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def clean_code(code: str) -> str:
    if "```python" in code:
        code = code.split("```python", 1)[1]
        if "```" in code:
            code = code.split("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1]
        if "```" in code:
            code = code.split("```", 1)[0]
    return code.strip()


def save_strategy(code: str, number: int) -> Path:
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = STRATEGY_DIR / f"intraday_strategy_{number}.py"
    filepath.write_text(code, encoding="utf-8")
    return filepath


def load_strategy(filepath: Path):
    module_name = f"var_{filepath.stem}_{datetime.now().strftime('%H%M%S%f')}"
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from src.strategies.intraday.base import IntradayStrategy
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, IntradayStrategy) and attr is not IntradayStrategy:
            return attr()
    raise ValueError(f"IntradayStrategy 서브클래스를 찾을 수 없음: {filepath}")


def run_backtest(strategy, data):
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
            "trades_detail": [
                {"code": t.code, "pnl_pct": round(t.pnl_pct, 2), "exit_reason": t.exit_reason}
                for t in trades[:100]
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def generate_init_file():
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    imports, classes = [], []

    for i in range(1, 4):
        filepath = STRATEGY_DIR / f"intraday_strategy_{i}.py"
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("class ") and "IntradayStrategy" in line:
                    cls = line.split("(")[0].replace("class ", "").strip()
                    imports.append(f"from src.strategies.data_driven.intraday_strategy_{i} import {cls}")
                    classes.append(cls)
                    break

    text = '"""Data-driven intraday strategies designed by OpenAI."""\n\n'
    text += "\n".join(imports)
    text += "\n\n\ndef get_data_driven_strategies() -> list:\n"
    text += '    """Get instances of all data-driven strategies."""\n'
    text += "    return [\n"
    for cls in classes:
        text += f"        {cls}(),\n"
    text += "    ]\n\n\n"
    text += "__all__ = [\n"
    for cls in classes:
        text += f'    "{cls}",\n'
    text += '    "get_data_driven_strategies",\n'
    text += "]\n"

    (STRATEGY_DIR / "__init__.py").write_text(text, encoding="utf-8")


def main():
    logger.info("=" * 70)
    logger.info("성공 전략 기반 변형 생성 (GPT-4o)")
    logger.info(f"모델: {OPENAI_MODEL}")
    logger.info("=" * 70)

    # 데이터 로드
    logger.info("\n[1/3] 분봉 데이터 로드...")
    data = load_intraday_data()
    is_data, oos_data = split_data_by_date(data)

    client = get_openai_client()

    results = {}

    # 각 변형에 대해 반복
    for spec in VARIATION_SPECS:
        strat_num = spec["number"]
        logger.info(f"\n{'='*60}")
        logger.info(f"전략 {strat_num}: {spec['description']}")
        logger.info(f"  시간대: {spec['time_window']}, 추가필터: {spec['additional_filter']}")
        logger.info(f"  SL=3%, TP=5% 고정 + RSI 40-60 필수")
        logger.info(f"{'='*60}")

        current_code = None
        best_code = None
        best_metrics = None
        last_metrics = None
        last_trades = None

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info(f"\n  반복 {iteration}/{MAX_ITERATIONS}")

            prompt = build_variation_prompt(
                spec, iteration,
                prev_code=current_code,
                prev_metrics=last_metrics,
                trades_detail=last_trades,
                best_code=best_code,
                best_metrics=best_metrics,
            )

            try:
                raw = call_openai(client, prompt)
                code = clean_code(raw)

                try:
                    compile(code, "<strategy>", "exec")
                except SyntaxError as e:
                    logger.warning(f"    문법 에러: {e}")
                    current_code = code
                    continue

                current_code = code
                filepath = save_strategy(code, strat_num)
                strategy = load_strategy(filepath)
                logger.info(f"    로드 성공: {strategy.name}")

                # IS 백테스트
                logger.info(f"    IS 백테스트...")
                result = run_backtest(strategy, is_data)

                if not result["success"]:
                    logger.warning(f"    IS 실패: {result['error']}")
                    last_metrics = {"win_rate": 0, "total_return_pct": -100, "total_trades": 0}
                    last_trades = None
                    continue

                metrics = result["metrics"]
                last_metrics = metrics
                last_trades = result.get("trades_detail", [])

                wr = metrics["win_rate"]
                ret = metrics["total_return_pct"]
                trades = metrics["total_trades"]
                logger.info(f"    IS: 승률={wr:.1f}%, 수익률={ret:+.2f}%, 거래={trades}건")

                # 최고 성과 보존
                is_better = best_metrics is None or ret > best_metrics.get("total_return_pct", -999)
                if is_better:
                    best_metrics = metrics
                    best_code = code
                    logger.info(f"    ★ 새로운 최고 성과! {ret:+.2f}%")
                else:
                    logger.info(f"    최고 유지: {best_metrics['total_return_pct']:+.2f}% (이번: {ret:+.2f}%)")

                # 합격 체크
                if wr >= TARGET_WIN_RATE and ret > TARGET_RETURN and trades >= 50:
                    logger.info(f"    IS 목표 달성! OOS 검증...")
                    oos_strategy = load_strategy(filepath)
                    oos_result = run_backtest(oos_strategy, oos_data)

                    if oos_result["success"]:
                        oos_m = oos_result["metrics"]
                        logger.info(f"    OOS: 승률={oos_m['win_rate']:.1f}%, 수익률={oos_m['total_return_pct']:+.2f}%")

                        if oos_m.get("total_return_pct", 0) > 0:
                            logger.info(f"    *** IS+OOS 통과! 채택 ***")
                            results[strat_num] = {
                                "accepted": True, "iterations": iteration,
                                "is_metrics": metrics, "oos_metrics": oos_m,
                            }
                            break
                        else:
                            logger.info(f"    OOS 실패 (음수)")
                    else:
                        logger.warning(f"    OOS 에러: {oos_result['error']}")

            except Exception as e:
                logger.error(f"    에러: {e}")
                traceback.print_exc()

        # 최종 결과
        if strat_num not in results:
            results[strat_num] = {
                "accepted": False, "iterations": MAX_ITERATIONS,
                "is_metrics": best_metrics,
            }
        if best_code:
            save_strategy(best_code, strat_num)

    # __init__.py 재생성
    generate_init_file()

    # 요약
    logger.info("\n" + "=" * 70)
    logger.info("변형 전략 생성 완료")
    logger.info("=" * 70)
    logger.info(f"  전략 1 (원본): 승률=40.6%, 수익률=+7.86% [ACCEPTED]")

    for num, r in results.items():
        status = "ACCEPTED" if r["accepted"] else "FAILED"
        m = r.get("is_metrics") or {}
        logger.info(
            f"  전략 {num}: [{status}] "
            f"승률={m.get('win_rate', 0):.1f}%, "
            f"수익률={m.get('total_return_pct', 0):+.2f}%, "
            f"반복={r['iterations']}회"
        )

    # 보고서 저장
    report = {
        "timestamp": datetime.now().isoformat(),
        "model": OPENAI_MODEL,
        "strategy_1": {"accepted": True, "is_metrics": WINNING_METRICS},
        "variations": {str(k): v for k, v in results.items()},
    }
    report_path = project_root / "reports" / "strategy_variations_result.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"\n결과: {report_path}")


if __name__ == "__main__":
    main()
