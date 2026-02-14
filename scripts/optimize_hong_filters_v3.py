#!/usr/bin/env python3
"""GPT 홍인기 파라미터 최적화 V3

2단계 최적화:
  Phase A: 그리드 서치 (핵심 파라미터 조합 직접 테스트)
  Phase B: GPT 미세조정 (그리드 서치 최적 결과 기반 전략 코드 조정)

IS/OOS 검증:
  - IS 개선 + OOS 30% 이하 악화만 수용
"""

import copy
import importlib
import importlib.util
import json
import os
import sys
import traceback
from datetime import datetime, time
from itertools import product
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
from src.strategies.data_driven.daily_context import DailyContextLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ROUNDS = 10
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"

CONFIG = IntradayBacktestConfig(
    initial_capital=10_000_000,
    max_positions=3,
    position_size=0.30,
    commission_rate=0.00015,
    tax_rate=0.0023,
    force_close_time=time(15, 20),
)

# 그리드 서치 파라미터
GRID_PARAMS = {
    "cap": [3000, 5000, 10000],
    "inst_range": [(30, 200), (50, 200), (50, 150), (80, 200)],
    "ki": [0, 20, 30, 40],
}

# 전략별 맞춤 제약조건
STRATEGY_CONSTRAINTS = {
    1: {
        "name": "Morning RSI Neutral ATR + Hong",
        "time_window": "9-11시 (오전)",
        "hong_hints": [
            "오전 장초반은 끼 높은 종목이 유리 (HONG_MIN_KI_SCORE=30-40)",
            "시총 5000-10000억 범위가 적절",
            "기관순매수 50-200억 범위 유지",
        ],
    },
    2: {
        "name": "Lunch RSI Neutral ATR Volume + Hong",
        "time_window": "11-13시 (점심)",
        "hong_hints": [
            "점심시간은 거래대금 높은 종목만 (HONG_MIN_DAILY_VALUE=100억+)",
            "끼 필터는 완화 가능 (20-30)",
        ],
    },
    3: {
        "name": "Modified RSI Neutral ATR (Wide) + Hong",
        "time_window": "9-14시 (전 시간)",
        "hong_hints": [
            "전 시간대 전략이므로 좋은 일봉자리만 (신고가, 전고점돌파)",
            "기관+시총 필터 중요",
        ],
    },
    4: {
        "name": "Afternoon RSI Neutral ATR + Hong",
        "time_window": "13-15시 (오후)",
        "hong_hints": [
            "오후는 기관 더 강한 것만 (HONG_MIN_INST_BIL=80+)",
            "끼 보다는 기관력 중요",
        ],
    },
    6: {
        "name": "Afternoon RSI Neutral ATR Volume + Hong",
        "time_window": "13-14:30시 (오후)",
        "hong_hints": [
            "오후 거래량 전략: 기관 강한 것 + 거래대금 높은 것",
            "ATR 범위와 홍인기 파라미터 동시 조정 가능",
        ],
    },
    8: {
        "name": "Morning Wide RSI + Hong",
        "time_window": "9:30-11:30 (오전)",
        "hong_hints": [
            "오전 전략: 끼 높은 종목 (HONG_MIN_KI_SCORE=30-40)",
            "볼륨 필터 + 홍인기 필터 조합 최적화",
        ],
    },
}


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
    return is_data, oos_data, all_dates


def run_backtest(strategy, data, daily_context=None):
    engine = IntradayBacktestEngineV2(CONFIG)
    try:
        metrics, trades = engine.run(strategy, data, show_progress=False, daily_context=daily_context)
        return {
            "success": True,
            "metrics": metrics.to_dict(),
            "trades_count": metrics.total_trades,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def load_strategy_from_file(filepath):
    module_name = f"opt_{filepath.stem}_{datetime.now().strftime('%H%M%S%f')}"
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from src.strategies.intraday.base import IntradayStrategy
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if isinstance(attr, type) and issubclass(attr, IntradayStrategy) and attr is not IntradayStrategy:
            return attr()
    raise ValueError(f"전략 클래스 없음: {filepath}")


def load_strategy_instance(strat_num):
    filepath = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
    if not filepath.exists():
        return None
    return load_strategy_from_file(filepath)


# =============================================
# Phase A: 그리드 서치
# =============================================

def grid_search(strat_num, is_data, oos_data, daily_context):
    """핵심 홍인기 파라미터 그리드 서치."""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Phase A: 전략 {strat_num} 그리드 서치")
    logger.info(f"{'=' * 60}")

    strategy = load_strategy_instance(strat_num)
    if strategy is None:
        logger.error(f"전략 {strat_num} 로드 실패")
        return None

    # 베이스라인 (현재 설정)
    is_result = run_backtest(strategy, is_data, daily_context)
    oos_result = run_backtest(strategy, oos_data, daily_context)

    if not is_result["success"] or not oos_result["success"]:
        logger.error(f"베이스라인 실패")
        return None

    baseline = {
        "is_ret": is_result["metrics"]["total_return_pct"],
        "oos_ret": oos_result["metrics"]["total_return_pct"],
        "is_wr": is_result["metrics"]["win_rate"],
        "is_trades": is_result["metrics"]["total_trades"],
    }
    logger.info(f"  베이스라인: IS={baseline['is_ret']:+.2f}% (WR={baseline['is_wr']:.1f}%, {baseline['is_trades']}건), OOS={baseline['oos_ret']:+.2f}%")

    best = {**baseline, "params": "baseline"}
    results_log = []

    combos = list(product(
        GRID_PARAMS["cap"],
        GRID_PARAMS["inst_range"],
        GRID_PARAMS["ki"],
    ))
    logger.info(f"  {len(combos)}개 조합 테스트 중...")

    for i, (cap, (inst_min, inst_max), ki) in enumerate(combos):
        s = copy.deepcopy(strategy)
        s.HONG_ENABLED = True
        s.HONG_MIN_CAP_BIL = cap
        s.HONG_MIN_INST_BIL = inst_min
        s.HONG_MAX_INST_BIL = inst_max
        s.HONG_MIN_KI_SCORE = ki

        is_r = run_backtest(s, is_data, daily_context)
        if not is_r["success"]:
            continue

        oos_r = run_backtest(s, oos_data, daily_context)
        if not oos_r["success"]:
            continue

        is_ret = is_r["metrics"]["total_return_pct"]
        oos_ret = oos_r["metrics"]["total_return_pct"]
        is_wr = is_r["metrics"]["win_rate"]
        is_trades = is_r["metrics"]["total_trades"]

        param_str = f"cap={cap}, inst={inst_min}~{inst_max}, ki={ki}"
        results_log.append({
            "params": param_str,
            "is_ret": is_ret,
            "oos_ret": oos_ret,
            "is_wr": is_wr,
            "is_trades": is_trades,
            "cap": cap,
            "inst_min": inst_min,
            "inst_max": inst_max,
            "ki": ki,
        })

        # 개선 판정: IS 개선 + OOS 30% 이내 악화
        is_improved = is_ret > best["is_ret"]
        oos_ok = oos_ret >= best["oos_ret"] * 0.7 if best["oos_ret"] > 0 else oos_ret >= best["oos_ret"]
        enough = is_trades >= 30

        if is_improved and oos_ok and enough:
            logger.info(f"  #{i+1} ★ {param_str}: IS={is_ret:+.2f}% OOS={oos_ret:+.2f}% WR={is_wr:.1f}% ({is_trades}건)")
            best = {
                "is_ret": is_ret,
                "oos_ret": oos_ret,
                "is_wr": is_wr,
                "is_trades": is_trades,
                "params": param_str,
                "cap": cap,
                "inst_min": inst_min,
                "inst_max": inst_max,
                "ki": ki,
            }

    logger.info(f"\n  그리드 서치 최적: {best['params']}")
    logger.info(f"  IS={best['is_ret']:+.2f}%, OOS={best['oos_ret']:+.2f}%, WR={best['is_wr']:.1f}%")

    # 상위 5개 결과 출력
    results_log.sort(key=lambda x: x["is_ret"], reverse=True)
    logger.info(f"\n  TOP 5 조합:")
    for r in results_log[:5]:
        logger.info(f"    {r['params']}: IS={r['is_ret']:+.2f}% OOS={r['oos_ret']:+.2f}% WR={r['is_wr']:.1f}%")

    return best


# =============================================
# Phase B: GPT 미세조정
# =============================================

def call_openai(client, prompt, temperature=0.5):
    model = OPENAI_MODEL
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
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


def build_hong_optimization_prompt(strat_num, code, grid_best, is_metrics, oos_metrics, round_num, history):
    """홍인기 파라미터 + 기술적 조건 동시 최적화 프롬프트."""
    constraints = STRATEGY_CONSTRAINTS.get(strat_num, {})
    hints = "\n".join(f"- {h}" for h in constraints.get("hong_hints", []))

    is_wr = is_metrics.get("win_rate", 0)
    is_ret = is_metrics.get("total_return_pct", 0)
    is_trades = is_metrics.get("total_trades", 0)
    oos_wr = oos_metrics.get("win_rate", 0)
    oos_ret = oos_metrics.get("total_return_pct", 0)
    oos_trades = oos_metrics.get("total_trades", 0)

    history_text = ""
    if history:
        history_text = "\n### 이전 라운드 결과:\n"
        for h in history[-5:]:
            status = "채택" if h["accepted"] else "거부"
            history_text += f"- R{h['round']}: IS={h['is_ret']:+.2f}%, OOS={h['oos_ret']:+.2f}% → {status} ({h.get('reason', '')})\n"

    grid_info = ""
    if grid_best and "cap" in grid_best:
        grid_info = f"""### 그리드 서치 최적 파라미터:
- HONG_MIN_CAP_BIL={grid_best.get('cap', 5000)}
- HONG_MIN_INST_BIL={grid_best.get('inst_min', 50)}
- HONG_MAX_INST_BIL={grid_best.get('inst_max', 200)}
- HONG_MIN_KI_SCORE={grid_best.get('ki', 20)}
- 그리드 서치 결과: IS={grid_best['is_ret']:+.2f}%, OOS={grid_best['oos_ret']:+.2f}%
"""

    return f"""당신은 한국 주식 5분봉 단타 전략 최적화 전문가입니다.

## 전략 {strat_num}: {constraints.get('name', '')} (라운드 {round_num}/{MAX_ROUNDS})
- 시간대: {constraints.get('time_window', '')}

### 현재 성과:
- **IS**: 승률={is_wr:.1f}%, 수익률={is_ret:+.2f}%, 거래={is_trades}건
- **OOS**: 승률={oos_wr:.1f}%, 수익률={oos_ret:+.2f}%, 거래={oos_trades}건

{grid_info}
{history_text}

### 현재 코드:
```python
{code}
```

## 최적화 요청

이 전략의 **홍인기 파라미터**와 **기술적 조건**을 함께 최적화하세요.

### 조정 가능한 홍인기 파라미터:
- HONG_MIN_CAP_BIL: 시총 하한 (3000~10000억)
- HONG_MIN_INST_BIL / HONG_MAX_INST_BIL: 기관 순매수 범위 (억원)
- HONG_MIN_KI_SCORE: 끼 최소 점수 (0~50)
- HONG_PREFERRED_POSITIONS: 허용 일봉자리 세트
- HONG_MIN_DAILY_VALUE: 전일 거래대금 하한 (원)
- MIN_INTRADAY_CUM_VALUE: 당일 누적 거래대금 하한 (원)

### 이 전략에 적합한 조정 방향:
{hints}

### 조정 가능한 기술적 조건:
- ATR, RSI 범위, 거래량/거래대금 조건
- 시간 윈도우 미세 조정

### ★★★ 절대 규칙 ★★★
- **SL=3%, TP=5% 반드시 유지!**
- **RSI 40-60 중립 필터 반드시 유지!**
- **import: `from src.strategies.intraday.base import IntradayStrategy` 사용**
- **import: `from src.strategies.data_driven.hong_filter_mixin import HongFilterMixin` 사용**
- 클래스는 `(HongFilterMixin, IntradayStrategy)` 상속!
- passes_hong_filter(), passes_intraday_value_filter(), hong_confidence_boost() 호출 유지!
- 클래스명 변경 금지!
- 작은 변경만! 한 번에 2-3가지만 변경!
- 거래가 30건 미만이면 실패!

**개선된 전체 코드만 반환. 마크다운 코드블록 없이 순수 Python만. 설명 금지.**"""


def gpt_finetune(strat_num, client, is_data, oos_data, daily_context, grid_best):
    """GPT 미세조정 라운드."""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Phase B: 전략 {strat_num} GPT 미세조정")
    logger.info(f"{'=' * 60}")

    filepath = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
    if not filepath.exists():
        return None

    current_code = filepath.read_text(encoding="utf-8")

    # 베이스라인
    strategy = load_strategy_from_file(filepath)

    # 그리드 서치 최적 파라미터 적용
    if grid_best and "cap" in grid_best:
        strategy.HONG_MIN_CAP_BIL = grid_best["cap"]
        strategy.HONG_MIN_INST_BIL = grid_best["inst_min"]
        strategy.HONG_MAX_INST_BIL = grid_best["inst_max"]
        strategy.HONG_MIN_KI_SCORE = grid_best["ki"]

    is_baseline = run_backtest(strategy, is_data, daily_context)
    oos_baseline = run_backtest(strategy, oos_data, daily_context)

    if not is_baseline["success"] or not oos_baseline["success"]:
        logger.error(f"  베이스라인 실패")
        return None

    best_code = current_code
    best_is_ret = is_baseline["metrics"]["total_return_pct"]
    best_oos_ret = oos_baseline["metrics"]["total_return_pct"]
    best_is_metrics = is_baseline["metrics"]
    best_oos_metrics = oos_baseline["metrics"]

    logger.info(f"  베이스라인: IS={best_is_ret:+.2f}%, OOS={best_oos_ret:+.2f}%")

    no_improve_count = 0
    history = []

    for round_num in range(1, MAX_ROUNDS + 1):
        temp = 0.4 + (round_num - 1) * 0.09
        temp = min(temp, 1.2)
        logger.info(f"\n  라운드 {round_num}/{MAX_ROUNDS} (temp={temp:.2f})")

        prompt = build_hong_optimization_prompt(
            strat_num, best_code, grid_best,
            best_is_metrics, best_oos_metrics,
            round_num, history,
        )

        try:
            raw = call_openai(client, prompt, temperature=temp)
            code = clean_code(raw)

            try:
                compile(code, "<opt>", "exec")
            except SyntaxError as e:
                logger.warning(f"    문법 에러: {e}")
                history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "accepted": False, "reason": f"문법: {e}"})
                continue

            # import 수정
            if "from base import" in code:
                code = code.replace("from base import IntradayStrategy",
                                   "from src.strategies.intraday.base import IntradayStrategy")

            tmp_path = STRATEGY_DIR / f"_tmp_strategy_{strat_num}.py"
            tmp_path.write_text(code, encoding="utf-8")

            try:
                strategy = load_strategy_from_file(tmp_path)
            except Exception as e:
                logger.warning(f"    로드 에러: {e}")
                tmp_path.unlink(missing_ok=True)
                history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "accepted": False, "reason": f"로드: {e}"})
                continue

            is_result = run_backtest(strategy, is_data, daily_context)
            if not is_result["success"]:
                tmp_path.unlink(missing_ok=True)
                continue

            oos_result = run_backtest(strategy, oos_data, daily_context)
            tmp_path.unlink(missing_ok=True)

            if not oos_result["success"]:
                continue

            new_is_ret = is_result["metrics"]["total_return_pct"]
            new_oos_ret = oos_result["metrics"]["total_return_pct"]
            new_is_trades = is_result["metrics"]["total_trades"]

            logger.info(f"    결과: IS={new_is_ret:+.2f}% ({new_is_trades}건), OOS={new_oos_ret:+.2f}%")

            # 개선 판정
            is_improved = new_is_ret > best_is_ret
            oos_not_worse = new_oos_ret >= best_oos_ret * 0.7 if best_oos_ret > 0 else new_oos_ret >= best_oos_ret
            enough_trades = new_is_trades >= 30
            old_combined = best_is_ret * 0.6 + best_oos_ret * 0.4
            new_combined = new_is_ret * 0.6 + new_oos_ret * 0.4
            combined_improved = new_combined > old_combined

            accepted = is_improved and oos_not_worse and enough_trades and combined_improved

            reason = ""
            if not is_improved:
                reason = f"IS 미개선"
            elif not oos_not_worse:
                reason = f"OOS 악화"
            elif not enough_trades:
                reason = f"거래 부족({new_is_trades})"
            elif not combined_improved:
                reason = f"종합 미개선"

            history.append({
                "round": round_num,
                "is_ret": new_is_ret,
                "oos_ret": new_oos_ret,
                "accepted": accepted,
                "reason": reason if not accepted else "채택",
            })

            if accepted:
                logger.info(f"    ★ 채택! IS: {best_is_ret:+.2f}%→{new_is_ret:+.2f}%, OOS: {best_oos_ret:+.2f}%→{new_oos_ret:+.2f}%")
                best_code = code
                best_is_ret = new_is_ret
                best_oos_ret = new_oos_ret
                best_is_metrics = is_result["metrics"]
                best_oos_metrics = oos_result["metrics"]
                no_improve_count = 0
            else:
                no_improve_count += 1
                logger.info(f"    거부: {reason} (미개선 {no_improve_count}회)")
                if no_improve_count >= 4:
                    logger.info(f"    4회 연속 미개선 → 조기 종료")
                    break

        except Exception as e:
            logger.error(f"    에러: {e}")
            traceback.print_exc()

    # 최종 적용
    orig_is_ret = is_baseline["metrics"]["total_return_pct"]
    if best_is_ret > orig_is_ret:
        filepath.write_text(best_code, encoding="utf-8")
        logger.info(f"\n  ★ 전략 {strat_num} 개선 적용: IS {orig_is_ret:+.2f}%→{best_is_ret:+.2f}%, OOS {oos_baseline['metrics']['total_return_pct']:+.2f}%→{best_oos_ret:+.2f}%")
        return {"is_before": orig_is_ret, "is_after": best_is_ret, "oos_before": oos_baseline["metrics"]["total_return_pct"], "oos_after": best_oos_ret}
    else:
        logger.info(f"\n  전략 {strat_num}: 개선 없음, 원본 유지")
        return {"is_before": orig_is_ret, "is_after": orig_is_ret, "oos_before": oos_baseline["metrics"]["total_return_pct"], "oos_after": oos_baseline["metrics"]["total_return_pct"]}


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

    text_content = '"""Data-driven intraday strategies designed by OpenAI."""\n\n'
    text_content += "\n".join(imports)
    text_content += "\n\n\ndef get_data_driven_strategies() -> list:\n"
    text_content += '    """Get instances of all data-driven strategies."""\n'
    text_content += "    return [\n"
    for cls in classes:
        text_content += f"        {cls}(),\n"
    text_content += "    ]\n\n\n"
    text_content += "__all__ = [\n"
    for cls in classes:
        text_content += f'    "{cls}",\n'
    text_content += '    "get_data_driven_strategies",\n'
    text_content += "]\n"
    (STRATEGY_DIR / "__init__.py").write_text(text_content, encoding="utf-8")


def main():
    logger.info("=" * 70)
    logger.info("홍인기 파라미터 최적화 V3")
    logger.info(f"모델: {OPENAI_MODEL}, 최대 {MAX_ROUNDS}라운드/전략")
    logger.info("=" * 70)

    # 데이터 로드
    data = load_intraday_data()
    is_data, oos_data, all_dates = split_data(data)

    # 일별 컨텍스트
    codes = list(data.keys())
    daily_context = DailyContextLoader().load(codes, min(all_dates), max(all_dates))

    strat_nums = [1, 2, 3, 4, 6, 8]

    # Phase A: 그리드 서치
    grid_results = {}
    for sn in strat_nums:
        grid_best = grid_search(sn, is_data, oos_data, daily_context)
        grid_results[sn] = grid_best

    # Phase B: GPT 미세조정
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    gpt_results = {}
    for sn in strat_nums:
        result = gpt_finetune(sn, client, is_data, oos_data, daily_context, grid_results.get(sn))
        gpt_results[sn] = result

    # __init__.py 재생성
    generate_init_file()

    # 최종 합산
    logger.info(f"\n{'=' * 70}")
    logger.info("★★★ 최종 합산 결과 (전체 데이터) ★★★")
    logger.info(f"{'=' * 70}")

    engine = IntradayBacktestEngineV2(CONFIG)
    total_return = 0

    for sn in strat_nums:
        fp = STRATEGY_DIR / f"intraday_strategy_{sn}.py"
        if not fp.exists():
            continue
        strategy = load_strategy_from_file(fp)
        metrics, _ = engine.run(strategy, data, show_progress=False, daily_context=daily_context)
        m = metrics.to_dict()
        total_return += m["total_return_pct"]
        logger.info(f"  전략 {sn} ({strategy.name}): 승률={m['win_rate']:.1f}%, 수익률={m['total_return_pct']:+.2f}%, 거래={m['total_trades']}건")

    logger.info(f"\n  ★★★ 합산 수익률: {total_return:+.2f}% ★★★")

    # 결과 저장
    result = {
        "timestamp": datetime.now().isoformat(),
        "model": OPENAI_MODEL,
        "grid_results": {str(k): v for k, v in grid_results.items() if v},
        "gpt_results": {str(k): v for k, v in gpt_results.items() if v},
        "combined_return": total_return,
    }

    report_path = project_root / "reports" / "optimization_hong_v3_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info(f"\n결과 저장: {report_path}")


if __name__ == "__main__":
    main()
