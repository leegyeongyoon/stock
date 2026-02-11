#!/usr/bin/env python3
"""Round 3 최적화: +36.39% → +45% 목표.

Round 2 실패 원인 분석:
- check_exit_fast: position.entry_bar_idx 없어서 GPT가 시간 기반 exit 구현 불가 → 해결됨
- 새 전략: GPT에게 처음부터 설계 요청 → 모두 마이너스 → 기존 코드 복사+시간대 변경으로 전환
- 전략 2,3: GPT가 동일 코드 반복 생성 → 전략 1 성공 패턴을 구체적으로 제시

Round 3 접근:
Phase 1: 파라미터 그리드 서치 (GPT 없이 직접 테스트)
Phase 2: check_exit_fast 추가 (working example 제공)
Phase 3: 기존 코드 복사 + 시간대 변경으로 새 전략
Phase 4: GPT 미세 조정
"""

import importlib
import importlib.util
import json
import os
import sys
import copy
import traceback
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

import numpy as np
import pandas as pd
from openai import OpenAI
from sqlalchemy import text

from src.backtest.intraday_engine import IntradayBacktestConfig
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2
from src.database.connection import get_backtest_engine as get_engine
from src.utils.logger import get_logger

logger = get_logger(__name__)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"
CONFIG = IntradayBacktestConfig(initial_capital=5_000_000, max_positions=3, position_size=0.3)


def load_intraday_data():
    engine = get_engine()
    with engine.connect() as conn:
        codes = [r[0] for r in conn.execute(text(
            "SELECT code FROM ohlcv_intraday GROUP BY code HAVING COUNT(*) >= 100"
        )).fetchall()]
    data = {}
    with engine.connect() as conn:
        for code in codes:
            rows = conn.execute(text(
                "SELECT datetime, open, high, low, close, volume "
                "FROM ohlcv_intraday WHERE code = :code ORDER BY datetime"
            ), {"code": code}).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
                data[code] = df
    logger.info(f"로드: {len(data)}종목, {sum(len(df) for df in data.values()):,}건")
    return data


def split_data(data, is_ratio=0.75):
    all_dates = sorted(set(d for df in data.values() for d in df.index.date))
    split_idx = int(len(all_dates) * is_ratio)
    is_dates = set(all_dates[:split_idx])
    oos_dates = set(all_dates[split_idx:])
    is_data = {c: df[df.index.map(lambda x: x.date() in is_dates)] for c, df in data.items()}
    oos_data = {c: df[df.index.map(lambda x: x.date() in oos_dates)] for c, df in data.items()}
    is_data = {k: v for k, v in is_data.items() if not v.empty}
    oos_data = {k: v for k, v in oos_data.items() if not v.empty}
    logger.info(f"IS: {len(is_dates)}일, OOS: {len(oos_dates)}일")
    return is_data, oos_data


def load_strategy_from_file(filepath):
    module_name = f"r3_{filepath.stem}_{datetime.now().strftime('%H%M%S%f')}"
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from src.strategies.intraday.base import IntradayStrategy
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if isinstance(attr, type) and issubclass(attr, IntradayStrategy) and attr is not IntradayStrategy:
            return attr()
    raise ValueError(f"전략 클래스 없음: {filepath}")


def run_backtest(strategy, data):
    engine = IntradayBacktestEngineV2(CONFIG)
    try:
        metrics, trades = engine.run(strategy, data, show_progress=False)
        return {"success": True, "metrics": metrics.to_dict(), "total_trades": metrics.total_trades,
                "return": metrics.total_return_pct, "win_rate": metrics.win_rate}
    except Exception as e:
        return {"success": False, "error": str(e), "return": -999}


def run_full_eval(strategy, data, is_data, oos_data):
    """IS, OOS, Full 모두 테스트."""
    is_r = run_backtest(strategy, is_data)
    oos_r = run_backtest(strategy, oos_data)
    full_r = run_backtest(strategy, data)
    return is_r, oos_r, full_r


def call_openai(client, prompt, temperature=0.5):
    model = OPENAI_MODEL
    kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
    if model.startswith("gpt-5"):
        kwargs["max_completion_tokens"] = 6000
    else:
        kwargs["max_tokens"] = 6000
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def clean_code(code):
    if "```python" in code:
        code = code.split("```python", 1)[1]
        if "```" in code:
            code = code.split("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1]
        if "```" in code:
            code = code.split("```", 1)[0]
    return code.strip()


def generate_init_file():
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    imports, classes = [], []
    for i in range(1, 10):
        fp = STRATEGY_DIR / f"intraday_strategy_{i}.py"
        if fp.exists():
            content = fp.read_text(encoding="utf-8")
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


# ============================================================
# Phase 1: 파라미터 그리드 서치 (GPT 없이!)
# ============================================================

def make_strategy_variant(base_code, replacements):
    """기존 전략 코드에서 파라미터만 변경한 코드 생성."""
    code = base_code
    for old, new in replacements:
        code = code.replace(old, new)
    return code


def phase1_parameter_grid(data, is_data, oos_data):
    """기존 전략의 파라미터를 직접 변경하면서 테스트."""
    logger.info("\n" + "=" * 70)
    logger.info("Phase 1: 파라미터 그리드 서치 (GPT 없이 직접 테스트)")
    logger.info("=" * 70)

    improvements = {}

    # 전략 2: vol_ratio와 ATR 조합 테스트
    strat2_path = STRATEGY_DIR / "intraday_strategy_2.py"
    if strat2_path.exists():
        logger.info(f"\n{'=' * 60}")
        logger.info("전략 2: 파라미터 그리드 서치")
        logger.info(f"{'=' * 60}")

        base_code = strat2_path.read_text(encoding="utf-8")
        strategy = load_strategy_from_file(strat2_path)
        base_result = run_backtest(strategy, data)
        base_ret = base_result["return"] if base_result["success"] else -999
        logger.info(f"  베이스라인: Full={base_ret:+.2f}%")

        best_code = base_code
        best_ret = base_ret

        # 테스트할 파라미터 조합
        grid = [
            # (vol_ratio, atr_threshold) 조합
            [("self.vol_ratio_threshold = 1.17", "self.vol_ratio_threshold = 1.10"),
             ("self.atr_threshold = 0.005389", "self.atr_threshold = 0.005")],
            [("self.vol_ratio_threshold = 1.17", "self.vol_ratio_threshold = 1.25"),
             ("self.atr_threshold = 0.005389", "self.atr_threshold = 0.005")],
            [("self.vol_ratio_threshold = 1.17", "self.vol_ratio_threshold = 1.10"),
             ("self.atr_threshold = 0.005389", "self.atr_threshold = 0.0045")],
            # VWAP 추가 변형
            [("self.vol_ratio_threshold = 1.17", "self.vol_ratio_threshold = 1.10"),
             ("self.atr_threshold = 0.005389", "self.atr_threshold = 0.005"),
             # 2연속 양봉으로 변경
             ("if not bullish_candle[bar_idx - 1]:\n            return None",
              "if not bullish_candle[bar_idx - 1] or not bullish_candle[bar_idx - 2]:\n            return None")],
            # VWAP 필터 추가
            [("self.vol_ratio_threshold = 1.17", "self.vol_ratio_threshold = 1.10"),
             ("self.atr_threshold = 0.005389", "self.atr_threshold = 0.005"),
             ("if not bullish_candle[bar_idx - 1]:\n            return None",
              "if not bullish_candle[bar_idx - 1]:\n            return None\n\n        # VWAP 위 필터\n        if indicators['close'][bar_idx] < indicators['vwap'][bar_idx]:\n            return None")],
        ]

        for idx, replacements in enumerate(grid):
            code = make_strategy_variant(base_code, replacements)
            tmp_path = STRATEGY_DIR / f"_tmp_grid_2.py"
            tmp_path.write_text(code, encoding="utf-8")

            try:
                strategy = load_strategy_from_file(tmp_path)
                is_r, oos_r, full_r = run_full_eval(strategy, data, is_data, oos_data)

                if full_r["success"]:
                    is_ret = is_r["return"] if is_r["success"] else -999
                    oos_ret = oos_r["return"] if oos_r["success"] else -999
                    full_ret = full_r["return"]
                    trades = full_r.get("total_trades", 0)
                    logger.info(f"  그리드 {idx+1}: IS={is_ret:+.2f}%, OOS={oos_ret:+.2f}%, Full={full_ret:+.2f}% ({trades}건)")

                    if full_ret > best_ret and is_ret > 0 and oos_ret > -2 and trades >= 50:
                        best_ret = full_ret
                        best_code = code
                        logger.info(f"    ★ 최고 기록 갱신!")
            except Exception as e:
                logger.warning(f"  그리드 {idx+1}: 에러 - {e}")
            finally:
                tmp_path.unlink(missing_ok=True)

        if best_ret > base_ret:
            strat2_path.write_text(best_code, encoding="utf-8")
            logger.info(f"  ★ 전략 2 개선: {base_ret:+.2f}% → {best_ret:+.2f}%")
            improvements[2] = best_ret - base_ret
        else:
            logger.info(f"  전략 2: 개선 없음")
            improvements[2] = 0

    # 전략 3: ATR과 시간 조합 테스트
    strat3_path = STRATEGY_DIR / "intraday_strategy_3.py"
    if strat3_path.exists():
        logger.info(f"\n{'=' * 60}")
        logger.info("전략 3: 파라미터 그리드 서치")
        logger.info(f"{'=' * 60}")

        base_code = strat3_path.read_text(encoding="utf-8")
        strategy = load_strategy_from_file(strat3_path)
        base_result = run_backtest(strategy, data)
        base_ret = base_result["return"] if base_result["success"] else -999
        logger.info(f"  베이스라인: Full={base_ret:+.2f}%")

        best_code = base_code
        best_ret = base_ret

        grid = [
            # ATR 변경
            [("self.atr_threshold = 0.005389", "self.atr_threshold = 0.005")],
            [("self.atr_threshold = 0.005389", "self.atr_threshold = 0.0048")],
            [("self.atr_threshold = 0.005389", "self.atr_threshold = 0.0055")],
            # 시간 윈도우 좁히기
            [("if hour < 9 or hour >= 14:", "if hour < 9 or hour >= 13:"),
             ("self.atr_threshold = 0.005389", "self.atr_threshold = 0.005")],
            # VWAP 이격도 추가
            [("self.atr_threshold = 0.005389", "self.atr_threshold = 0.005"),
             ("if closes[bar_idx] <= vwap[bar_idx]:\n            return None",
              "if closes[bar_idx] <= vwap[bar_idx] * 1.002:\n            return None")],
        ]

        for idx, replacements in enumerate(grid):
            code = make_strategy_variant(base_code, replacements)
            tmp_path = STRATEGY_DIR / f"_tmp_grid_3.py"
            tmp_path.write_text(code, encoding="utf-8")

            try:
                strategy = load_strategy_from_file(tmp_path)
                is_r, oos_r, full_r = run_full_eval(strategy, data, is_data, oos_data)

                if full_r["success"]:
                    is_ret = is_r["return"] if is_r["success"] else -999
                    oos_ret = oos_r["return"] if oos_r["success"] else -999
                    full_ret = full_r["return"]
                    trades = full_r.get("total_trades", 0)
                    logger.info(f"  그리드 {idx+1}: IS={is_ret:+.2f}%, OOS={oos_ret:+.2f}%, Full={full_ret:+.2f}% ({trades}건)")

                    if full_ret > best_ret and is_ret > 0 and oos_ret > -2 and trades >= 50:
                        best_ret = full_ret
                        best_code = code
                        logger.info(f"    ★ 최고 기록 갱신!")
            except Exception as e:
                logger.warning(f"  그리드 {idx+1}: 에러 - {e}")
            finally:
                tmp_path.unlink(missing_ok=True)

        if best_ret > base_ret:
            strat3_path.write_text(best_code, encoding="utf-8")
            logger.info(f"  ★ 전략 3 개선: {base_ret:+.2f}% → {best_ret:+.2f}%")
            improvements[3] = best_ret - base_ret
        else:
            logger.info(f"  전략 3: 개선 없음")
            improvements[3] = 0

    # 전략 6: 파라미터 그리드
    strat6_path = STRATEGY_DIR / "intraday_strategy_6.py"
    if strat6_path.exists():
        logger.info(f"\n{'=' * 60}")
        logger.info("전략 6: 파라미터 그리드 서치")
        logger.info(f"{'=' * 60}")

        base_code = strat6_path.read_text(encoding="utf-8")
        strategy = load_strategy_from_file(strat6_path)
        base_result = run_backtest(strategy, data)
        base_ret = base_result["return"] if base_result["success"] else -999
        logger.info(f"  베이스라인: Full={base_ret:+.2f}%")

        best_code = base_code
        best_ret = base_ret

        grid = [
            # ATR 범위 조절
            [("self.atr_threshold_low = 0.0040", "self.atr_threshold_low = 0.0035"),
             ("self.atr_threshold_high = 0.0060", "self.atr_threshold_high = 0.0065")],
            # 거래량 조건 완화
            [("if volumes[bar_idx] <= 1.3 * avg_volume_last_5[bar_idx]:",
              "if volumes[bar_idx] <= 1.2 * avg_volume_last_5[bar_idx]:")],
            # RSI 범위 조절 (40-55 → 40-58)
            [("if not (40 <= rsi[bar_idx] <= 55):", "if not (40 <= rsi[bar_idx] <= 58):")],
            # 1양봉으로 완화
            [("if not bullish_candle[bar_idx - 1] or (bar_idx > 1 and not bullish_candle[bar_idx - 2]):\n            return None",
              "if not bullish_candle[bar_idx - 1]:\n            return None")],
            # 복합: ATR 넓히기 + 거래량 완화
            [("self.atr_threshold_low = 0.0040", "self.atr_threshold_low = 0.0035"),
             ("self.atr_threshold_high = 0.0060", "self.atr_threshold_high = 0.007"),
             ("if volumes[bar_idx] <= 1.3 * avg_volume_last_5[bar_idx]:",
              "if volumes[bar_idx] <= 1.15 * avg_volume_last_5[bar_idx]:")],
        ]

        for idx, replacements in enumerate(grid):
            code = make_strategy_variant(base_code, replacements)
            tmp_path = STRATEGY_DIR / f"_tmp_grid_6.py"
            tmp_path.write_text(code, encoding="utf-8")

            try:
                strategy = load_strategy_from_file(tmp_path)
                is_r, oos_r, full_r = run_full_eval(strategy, data, is_data, oos_data)

                if full_r["success"]:
                    is_ret = is_r["return"] if is_r["success"] else -999
                    oos_ret = oos_r["return"] if oos_r["success"] else -999
                    full_ret = full_r["return"]
                    trades = full_r.get("total_trades", 0)
                    logger.info(f"  그리드 {idx+1}: IS={is_ret:+.2f}%, OOS={oos_ret:+.2f}%, Full={full_ret:+.2f}% ({trades}건)")

                    if full_ret > best_ret and is_ret > 0 and oos_ret > -2 and trades >= 30:
                        best_ret = full_ret
                        best_code = code
                        logger.info(f"    ★ 최고 기록 갱신!")
            except Exception as e:
                logger.warning(f"  그리드 {idx+1}: 에러 - {e}")
            finally:
                tmp_path.unlink(missing_ok=True)

        if best_ret > base_ret:
            strat6_path.write_text(best_code, encoding="utf-8")
            logger.info(f"  ★ 전략 6 개선: {base_ret:+.2f}% → {best_ret:+.2f}%")
            improvements[6] = best_ret - base_ret
        else:
            logger.info(f"  전략 6: 개선 없음")
            improvements[6] = 0

    return improvements


# ============================================================
# Phase 2: check_exit_fast GPT 최적화 (working example 제공)
# ============================================================

EXIT_EXAMPLE = '''
    def check_exit_fast(self, position, bar_idx, indicators):
        """청산 조건 확인.

        사용 가능한 속성:
        - position.entry_price (float): 진입가
        - position.entry_bar_idx (int): 진입 시 bar index (당일 기준)
        - position.stop_loss (float): 손절가 (절대값)
        - position.take_profit (float): 익절가 (절대값)
        - position.code (str): 종목코드
        - bar_idx (int): 현재 bar index (당일 기준)
        - indicators: dict with 'close', 'high', 'low', 'open', 'volume', 'rsi_14', 'vwap', etc.

        bars_held = bar_idx - position.entry_bar_idx  # 진입 후 경과 bar 수

        반환: 문자열(청산 이유) 또는 None(청산 안함)
        """
        bars_held = bar_idx - position.entry_bar_idx

        # 예시 1: RSI 75 이상이면 조기 익절
        rsi = indicators["rsi_14"]
        if not np.isnan(rsi[bar_idx]) and rsi[bar_idx] >= 75:
            return "RSI overbought exit"

        # 예시 2: 10바 이상 보유 + 수익 감소 시 청산
        current_price = indicators["close"][bar_idx]
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        if bars_held >= 10 and pnl_pct < 0.005:
            return "Time decay exit"

        return None
'''


def phase2_exit_logic(client, data, is_data, oos_data):
    """check_exit_fast 추가로 기존 전략 개선."""
    logger.info("\n" + "=" * 70)
    logger.info("Phase 2: check_exit_fast 로직 추가 (GPT + working example)")
    logger.info("=" * 70)

    improvements = {}

    for strat_num in [1, 2, 3, 6]:
        filepath = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
        if not filepath.exists():
            continue

        logger.info(f"\n{'=' * 60}")
        logger.info(f"전략 {strat_num}: exit 로직 개선")
        logger.info(f"{'=' * 60}")

        current_code = filepath.read_text(encoding="utf-8")

        # 이미 exit 로직이 있으면 건너뛰기
        if "return None" not in current_code.split("check_exit_fast")[1].split("def ")[0] if "check_exit_fast" in current_code else True:
            logger.info(f"  이미 exit 로직 존재, 건너뛰기")
            continue

        strategy = load_strategy_from_file(filepath)
        is_r = run_backtest(strategy, is_data)
        oos_r = run_backtest(strategy, oos_data)
        full_r = run_backtest(strategy, data)

        if not full_r["success"]:
            continue

        base_full_ret = full_r["return"]
        base_is_ret = is_r["return"] if is_r["success"] else -999
        base_oos_ret = oos_r["return"] if oos_r["success"] else -999
        logger.info(f"  베이스라인: IS={base_is_ret:+.2f}%, OOS={base_oos_ret:+.2f}%, Full={base_full_ret:+.2f}%")

        best_code = current_code
        best_full_ret = base_full_ret

        prompt = f"""당신은 한국 주식 5분봉 단타 전략의 check_exit_fast 로직 전문가입니다.

## 현재 전략 코드:
```python
{current_code}
```

## 현재 성과:
- IS (44일): 수익률={base_is_ret:+.2f}%
- OOS (15일): 수익률={base_oos_ret:+.2f}%
- Full (59일): 수익률={base_full_ret:+.2f}%

## check_exit_fast 작동 예시:
```python
{EXIT_EXAMPLE}
```

## 요청사항:
check_exit_fast 메서드에 **스마트한 청산 로직**을 추가해주세요.

### ★★★ 중요: position 속성 (반드시 이대로 사용!) ★★★
- `position.entry_price` (float) - 진입가
- `position.entry_bar_idx` (int) - 진입 시 bar index
- `position.stop_loss` (float) - 손절 절대가격
- `position.take_profit` (float) - 익절 절대가격
- `position.code` (str) - 종목코드
- `bar_idx` (int) - 현재 bar index
- `bars_held = bar_idx - position.entry_bar_idx` (경과 bar 수)

### ★ position은 객체입니다! dict가 아닙니다! ★
- position.entry_price (O)
- position["entry_price"] (X, 에러남!)

### 유효한 exit 전략:
1. RSI 과매수(70-75+) 시 조기 익절
2. 보유 시간 N바 이상이고 수익 미미하면 청산 (기회비용)
3. VWAP 이탈 시 청산 (상승 모멘텀 소실)
4. 수익이 2% 이상이었다가 1% 미만으로 떨어지면 트레일링 스탑

### 규칙:
- check_exit_fast 메서드만 수정! 나머지 코드 그대로!
- 문자열 반환(청산 이유) 또는 None(유지)
- numpy import 이미 있음

**전체 코드를 반환. 마크다운 없이 순수 Python만.**"""

        for attempt in range(6):
            temp = 0.4 + attempt * 0.15
            logger.info(f"  시도 {attempt+1}/6 (temp={temp:.2f})")

            try:
                raw = call_openai(client, prompt, temperature=temp)
                code = clean_code(raw)

                try:
                    compile(code, "<exit>", "exec")
                except SyntaxError as e:
                    logger.warning(f"    문법 에러: {e}")
                    continue

                if "from src.strategies.intraday.base import" not in code:
                    code = "from src.strategies.intraday.base import IntradayStrategy\n" + code

                tmp_path = STRATEGY_DIR / f"_tmp_exit_{strat_num}.py"
                tmp_path.write_text(code, encoding="utf-8")

                try:
                    strategy = load_strategy_from_file(tmp_path)
                except Exception as e:
                    logger.warning(f"    로드 에러: {e}")
                    tmp_path.unlink(missing_ok=True)
                    continue

                is_r2 = run_backtest(strategy, is_data)
                if not is_r2["success"]:
                    logger.warning(f"    IS에러: {is_r2['error']}")
                    tmp_path.unlink(missing_ok=True)
                    continue

                oos_r2 = run_backtest(strategy, oos_data)
                tmp_path.unlink(missing_ok=True)
                if not oos_r2["success"]:
                    logger.warning(f"    OOS에러: {oos_r2['error']}")
                    continue

                full_r2 = run_backtest(strategy, data)
                if not full_r2["success"]:
                    continue

                new_full_ret = full_r2["return"]
                new_is_ret = is_r2["return"]
                new_oos_ret = oos_r2["return"]
                trades = full_r2.get("total_trades", 0)

                logger.info(f"    IS={new_is_ret:+.2f}%, OOS={new_oos_ret:+.2f}%, Full={new_full_ret:+.2f}% ({trades}건)")

                # 개선 판단: Full 수익 개선 + IS 양수 + OOS 크게 안 나빠짐
                if (new_full_ret > best_full_ret and
                    new_is_ret > 0 and
                    new_oos_ret >= base_oos_ret * 0.7 and
                    trades >= 30):
                    best_full_ret = new_full_ret
                    best_code = code
                    logger.info(f"    ★ 최고 기록 갱신! Full: {base_full_ret:+.2f}% → {new_full_ret:+.2f}%")

            except Exception as e:
                logger.error(f"    에러: {e}")
                traceback.print_exc()

        if best_full_ret > base_full_ret:
            filepath.write_text(best_code, encoding="utf-8")
            logger.info(f"  ★ 전략 {strat_num} exit 개선: {base_full_ret:+.2f}% → {best_full_ret:+.2f}%")
            improvements[strat_num] = best_full_ret - base_full_ret
        else:
            logger.info(f"  전략 {strat_num}: exit 개선 없음")
            improvements[strat_num] = 0

    return improvements


# ============================================================
# Phase 3: 기존 코드 복사 + 시간대 변경으로 새 전략
# ============================================================

def phase3_time_window_variants(data, is_data, oos_data):
    """기존 성공 전략의 시간대만 변경한 새 전략 생성."""
    logger.info("\n" + "=" * 70)
    logger.info("Phase 3: 시간대 변경 변형 전략 (GPT 없이)")
    logger.info("=" * 70)

    created = {}

    # 전략 1 기반 (9:30-11시 → 다른 시간대)
    strat1_code = (STRATEGY_DIR / "intraday_strategy_1.py").read_text(encoding="utf-8")

    # 전략 4: 전략 1 코드 기반, 시간대 = 13-15시
    variants = [
        {
            "num": 4,
            "desc": "전략 1 기반 → 13-15시 (오후)",
            "base_code": strat1_code,
            "replacements": [
                ("class MorningRSINeutralATRStrategy", "class AfternoonRSINeutralATRStrategy"),
                ('super().__init__(name="morning_rsi_neutral_atr")', 'super().__init__(name="afternoon_from_morning")'),
                # 시간 필터 변경: 9:30-11 → 13-15
                ("if hour < 9 or (hour == 9 and bar_idx % 12 < 6) or hour >= 11:",
                 "if hour < 13 or hour >= 15:"),
            ],
        },
        {
            "num": 5,
            "desc": "전략 2 기반 → 9-11시 (오전 + 거래량)",
            "base_code": (STRATEGY_DIR / "intraday_strategy_2.py").read_text(encoding="utf-8"),
            "replacements": [
                ("class LunchRSINeutralATRVolumeStrategy", "class MorningRSINeutralATRVolumeStrategy"),
                ('super().__init__(name="lunch_rsi_neutral_atr_volume")', 'super().__init__(name="morning_vol_variant")'),
                # 시간 필터 변경: 11-13 → 9:30-11
                ("if hour < 11 or hour >= 13:", "if hour < 9 or (hour == 9 and bar_idx % 12 < 6) or hour >= 11:"),
            ],
        },
        {
            "num": 7,
            "desc": "전략 6 기반 → 9:30-11시 (오전 변형)",
            "base_code": (STRATEGY_DIR / "intraday_strategy_6.py").read_text(encoding="utf-8"),
            "replacements": [
                ("class AfternoonRSINeutralATRVolumeStrategy", "class MorningRSINeutralATRVolume2Strategy"),
                ('super().__init__(name="afternoon_rsi_neutral_atr_volume")', 'super().__init__(name="morning_atr_vol2")'),
                # 시간 필터 변경: 13-14:30 → 9:30-11
                ("if hour < 13 or (hour == 14 and bar_idx % 12 > 5):",
                 "if hour < 9 or (hour == 9 and bar_idx % 12 < 6) or hour >= 11:"),
            ],
        },
        {
            "num": 8,
            "desc": "전략 3 기반 → 9:30-12시 (좁은 윈도우)",
            "base_code": (STRATEGY_DIR / "intraday_strategy_3.py").read_text(encoding="utf-8"),
            "replacements": [
                ("class ModifiedRSINeutralATRStrategy", "class MorningWideRSINeutralATRStrategy"),
                ('super().__init__(name="modified_rsi_neutral_atr")', 'super().__init__(name="morning_wide_rsi")'),
                # 시간 윈도우 좁히기: 9-14 → 9:30-12
                ("if hour < 9 or hour >= 14:",
                 "if hour < 9 or (hour == 9 and bar_idx % 12 < 6) or hour >= 12:"),
            ],
        },
    ]

    for v in variants:
        num = v["num"]
        filepath = STRATEGY_DIR / f"intraday_strategy_{num}.py"

        logger.info(f"\n{'=' * 60}")
        logger.info(f"전략 {num}: {v['desc']}")
        logger.info(f"{'=' * 60}")

        code = make_strategy_variant(v["base_code"], v["replacements"])
        filepath.write_text(code, encoding="utf-8")

        try:
            strategy = load_strategy_from_file(filepath)
            is_r, oos_r, full_r = run_full_eval(strategy, data, is_data, oos_data)

            if full_r["success"]:
                is_ret = is_r["return"] if is_r["success"] else -999
                oos_ret = oos_r["return"] if oos_r["success"] else -999
                full_ret = full_r["return"]
                trades = full_r.get("total_trades", 0)
                wr = full_r.get("win_rate", 0)

                logger.info(f"  IS={is_ret:+.2f}%, OOS={oos_ret:+.2f}%, Full={full_ret:+.2f}% ({trades}건, WR={wr:.1f}%)")

                # 채택 기준: Full 양수 + IS 양수 + OOS > -2% + 거래 30건+
                if full_ret > 0 and is_ret > 0 and oos_ret > -2 and trades >= 30:
                    logger.info(f"  ★ 전략 {num} 채택!")
                    created[num] = {"return": full_ret, "trades": trades, "desc": v["desc"]}
                else:
                    logger.info(f"  ✗ 기준 미달 → 삭제")
                    filepath.unlink(missing_ok=True)
            else:
                logger.warning(f"  에러: {full_r.get('error', '?')}")
                filepath.unlink(missing_ok=True)

        except Exception as e:
            logger.error(f"  에러: {e}")
            filepath.unlink(missing_ok=True)

    return created


# ============================================================
# Phase 4: GPT 미세 조정 (새 전략만)
# ============================================================

def phase4_gpt_finetune(client, data, is_data, oos_data, strategy_nums):
    """Phase 3에서 채택된 새 전략을 GPT로 미세 조정."""
    logger.info("\n" + "=" * 70)
    logger.info("Phase 4: GPT 미세 조정 (채택된 새 전략)")
    logger.info("=" * 70)

    improvements = {}

    for strat_num in strategy_nums:
        filepath = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
        if not filepath.exists():
            continue

        logger.info(f"\n{'=' * 60}")
        logger.info(f"전략 {strat_num}: GPT 미세 조정")
        logger.info(f"{'=' * 60}")

        current_code = filepath.read_text(encoding="utf-8")
        strategy = load_strategy_from_file(filepath)
        is_r = run_backtest(strategy, is_data)
        oos_r = run_backtest(strategy, oos_data)
        full_r = run_backtest(strategy, data)

        if not full_r["success"]:
            continue

        base_full_ret = full_r["return"]
        base_is_ret = is_r["return"] if is_r["success"] else -999
        base_oos_ret = oos_r["return"] if oos_r["success"] else -999
        base_trades = full_r.get("total_trades", 0)
        logger.info(f"  베이스라인: IS={base_is_ret:+.2f}%, OOS={base_oos_ret:+.2f}%, Full={base_full_ret:+.2f}% ({base_trades}건)")

        best_code = current_code
        best_full_ret = base_full_ret
        history = []

        prompt_base = f"""당신은 한국 주식 5분봉 단타 전략 최적화 전문가입니다.

## 현재 전략 코드:
```python
{{code}}
```

## 현재 성과:
- IS (44일): 수익률={{is_ret}}
- OOS (15일): 수익률={{oos_ret}}
- Full (59일): 수익률={{full_ret}}, 거래={{trades}}건

{{history}}

## 개선 요청
수익률을 높여주세요. **작은 변경만!** 한 번에 1-2가지만.

### 가능한 개선 방향:
1. ATR 임계값 미세 조정 (±0.0005 범위)
2. RSI 범위 미세 조정 (현재 40-60 유지, 38-62 또는 42-58 시도 가능)
3. 거래량 조건 추가/조절
4. VWAP 이격도 조건 추가
5. check_exit_fast 추가 (entry_bar_idx 사용 가능!)

### check_exit_fast 예시:
```python
{EXIT_EXAMPLE}
```

### ★★★ 절대 규칙 ★★★
- SL=3%, TP=5% 유지
- import: `from src.strategies.intraday.base import IntradayStrategy` 만 사용
- 클래스명 변경 금지
- position.entry_price (O), position["entry_price"] (X)

**전체 코드를 반환. 마크다운 없이 순수 Python만.**"""

        for round_num in range(1, 7):
            temp = 0.4 + (round_num - 1) * 0.15
            logger.info(f"  라운드 {round_num}/6 (temp={temp:.2f})")

            history_text = ""
            if history:
                history_text = "\n### 이전 시도:\n"
                for h in history[-3:]:
                    history_text += f"- R{h['round']}: Full={h['ret']:+.2f}% → {'채택' if h['ok'] else '거부'}\n"
                history_text += "\n다른 접근을 시도해주세요!\n"

            prompt = prompt_base.format(
                code=best_code,
                is_ret=f"{base_is_ret:+.2f}%",
                oos_ret=f"{base_oos_ret:+.2f}%",
                full_ret=f"{best_full_ret:+.2f}%",
                trades=base_trades,
                history=history_text,
            )

            try:
                raw = call_openai(client, prompt, temperature=temp)
                code = clean_code(raw)

                try:
                    compile(code, "<ft>", "exec")
                except SyntaxError:
                    continue

                if "from src.strategies.intraday.base import" not in code:
                    continue

                tmp_path = STRATEGY_DIR / f"_tmp_ft_{strat_num}.py"
                tmp_path.write_text(code, encoding="utf-8")

                try:
                    strategy = load_strategy_from_file(tmp_path)
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    continue

                r = run_backtest(strategy, data)
                tmp_path.unlink(missing_ok=True)

                if not r["success"]:
                    logger.warning(f"    에러: {r.get('error', '')}")
                    history.append({"round": round_num, "ret": -999, "ok": False})
                    continue

                new_ret = r["return"]
                new_trades = r.get("total_trades", 0)
                logger.info(f"    Full={new_ret:+.2f}% ({new_trades}건)")

                if new_ret > best_full_ret and new_trades >= 30:
                    # OOS 확인
                    is_r2 = run_backtest(strategy, is_data)
                    oos_r2 = run_backtest(strategy, oos_data)
                    if is_r2["success"] and oos_r2["success"]:
                        new_is = is_r2["return"]
                        new_oos = oos_r2["return"]
                        if new_is > 0 and new_oos >= base_oos_ret * 0.7:
                            best_full_ret = new_ret
                            best_code = code
                            logger.info(f"    ★ 채택! IS={new_is:+.2f}%, OOS={new_oos:+.2f}%, Full={new_ret:+.2f}%")
                            history.append({"round": round_num, "ret": new_ret, "ok": True})
                            continue

                history.append({"round": round_num, "ret": new_ret, "ok": False})

            except Exception as e:
                logger.error(f"    에러: {e}")

        if best_full_ret > base_full_ret:
            filepath.write_text(best_code, encoding="utf-8")
            logger.info(f"  ★ 전략 {strat_num} 개선: {base_full_ret:+.2f}% → {best_full_ret:+.2f}%")
            improvements[strat_num] = best_full_ret - base_full_ret
        else:
            logger.info(f"  전략 {strat_num}: 개선 없음")
            improvements[strat_num] = 0

    return improvements


def main():
    logger.info("=" * 70)
    logger.info("Round 3 최적화: +36.39% → +45% 목표")
    logger.info("=" * 70)

    data = load_intraday_data()
    is_data, oos_data = split_data(data)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Phase 1: 파라미터 그리드 (GPT 없이)
    grid_results = phase1_parameter_grid(data, is_data, oos_data)
    logger.info(f"\nPhase 1 결과: {grid_results}")

    # Phase 2: check_exit_fast (GPT)
    exit_results = phase2_exit_logic(client, data, is_data, oos_data)
    logger.info(f"\nPhase 2 결과: {exit_results}")

    # Phase 3: 시간대 변형 (GPT 없이)
    variant_results = phase3_time_window_variants(data, is_data, oos_data)
    logger.info(f"\nPhase 3 결과: {variant_results}")

    # Phase 4: GPT 미세 조정 (채택된 새 전략만)
    new_strat_nums = list(variant_results.keys())
    if new_strat_nums:
        finetune_results = phase4_gpt_finetune(client, data, is_data, oos_data, new_strat_nums)
        logger.info(f"\nPhase 4 결과: {finetune_results}")

    # __init__.py 재생성
    generate_init_file()

    # 최종 합산
    logger.info(f"\n{'=' * 70}")
    logger.info("★★★ 최종 합산 결과 (전체 데이터) ★★★")
    logger.info(f"{'=' * 70}")

    engine_v2 = IntradayBacktestEngineV2(CONFIG)
    total_return = 0

    for i in range(1, 10):
        fp = STRATEGY_DIR / f"intraday_strategy_{i}.py"
        if not fp.exists():
            continue
        try:
            strategy = load_strategy_from_file(fp)
            metrics, _ = engine_v2.run(strategy, data, show_progress=False)
            m = metrics.to_dict()
            total_return += m["total_return_pct"]
            logger.info(
                f"  전략 {i} ({strategy.name}): "
                f"승률={m['win_rate']:.1f}%, 수익률={m['total_return_pct']:+.2f}%, 거래={m['total_trades']}건"
            )
        except Exception as e:
            logger.error(f"  전략 {i}: 에러 - {e}")

    logger.info(f"\n  ★★★ 합산 수익률: {total_return:+.2f}% ★★★")

    # 결과 저장
    result = {
        "timestamp": datetime.now().isoformat(),
        "phase1_grid": grid_results,
        "phase2_exit": exit_results,
        "phase3_variants": {str(k): v for k, v in variant_results.items()},
        "combined_return": total_return,
    }

    report_path = project_root / "reports" / "round3_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"\n결과 저장: {report_path}")


if __name__ == "__main__":
    main()
