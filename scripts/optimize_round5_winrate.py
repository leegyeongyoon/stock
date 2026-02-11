#!/usr/bin/env python3
"""Round 5 최적화: 승률(Win Rate) 중심 개선 + 수익률 유지.

기존 6개 전략의 승률을 최대한 올리되, 수익률은 반드시 유지.
채택 기준: 승률 1%p+ 개선 AND 수익률 유지(-0.5% 이내)
10라운드/전략, 5회 연속 미개선 시 조기종료.
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

MAX_ROUNDS = 10
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"
CONFIG = IntradayBacktestConfig(initial_capital=5_000_000, max_positions=3, position_size=0.3)
EARLY_STOP_THRESHOLD = 5  # 5회 연속 미개선 시 조기종료

# Round 4에서 실패한 시도들 (GPT가 같은 실수를 반복하지 않도록)
ROUND4_FAILURES = {
    1: "R4: ATR 0.0045 + vol 1.2x 적용 완료. 추가 개선은 다른 방향으로.",
    2: "R4: RSI/거래량 변경 시 모두 마이너스(-2.74%~-3.34%). 기존 조건 유지하되 추가 필터 방식으로.",
    3: "R4: GPT가 동일 코드 반복 생성. VWAP 이격도/ATR 외 새로운 필터 필요.",
    4: "R4: 모든 제안이 마이너스(-2.1%~-9.46%). 기존 조건은 유지, 필터만 추가.",
    6: "R4: OOS 악화 또는 수익 하락. ATR범위/RSI 변경보다 새로운 필터 추가 필요.",
    8: "R4: GPT가 동일 코드 반복(+9.04%). 기존 조건 유지, 새로운 접근 필요.",
}

STRATEGY_CONSTRAINTS = {
    1: {
        "name": "MorningRSINeutralATR",
        "time_window": "9:30-11시 (오전)",
        "desc": "장 초반, ATR>=0.0045, RSI 40-60, 2연속 양봉, VWAP 위, vol>=1.2x avg",
        "wr_hints": [
            "RSI 범위를 42-58로 좁히기 (극단 거래 제거)",
            "VWAP 이격도 추가 (close > VWAP * 1.001~1.003)",
            "3연속 양봉으로 강화 (더 확실한 상승 추세만)",
            "직전 bar의 몸통 비율 필터 (long body만 진입)",
            "ATR 상한 추가 (너무 높은 변동성 = 위험)",
            "당일 시가 대비 현재가 위치 필터 (시가보다 일정% 위)",
        ],
        "forbidden": [
            "시간대 변경 금지 (9:30-11시 유지)",
            "vol 필터 제거 금지",
            "2연속 양봉을 1연속으로 약화 금지",
        ],
    },
    2: {
        "name": "LunchRSINeutralATRVolume",
        "time_window": "11-13시 (점심)",
        "desc": "점심, ATR>=0.005389, RSI 40-60, vol_ratio>=1.17, 1연속 양봉",
        "wr_hints": [
            "2연속 양봉으로 강화 (가장 효과적인 승률 개선)",
            "VWAP 위 조건 추가 (상승 추세 확인)",
            "RSI 42-56으로 좁히기 (중립 영역 더 보수적)",
            "vol_ratio를 1.25~1.35로 올리기 (더 확실한 거래량 급증)",
            "직전 bar 거래량도 평균 이상 요구",
            "ATR 상한 추가 (0.005~0.008 범위 필터)",
        ],
        "forbidden": [
            "시간대 변경 금지",
            "거래량 필터 제거 금지",
            "RSI 필터 제거 금지",
        ],
    },
    3: {
        "name": "ModifiedRSINeutralATR",
        "time_window": "9-14시 (와이드)",
        "desc": "넓은 시간, ATR>=0.005, RSI 40-60, VWAP*1.002, 2연속 양봉",
        "wr_hints": [
            "VWAP 이격도 상향 (1.003~1.005): 더 확실한 상승 추세",
            "거래량 조건 추가 (vol > avg_vol_10 * 1.2)",
            "3연속 양봉으로 강화",
            "특정 시간대 제외 (12-13시 점심 시간 피하기)",
            "ATR 상한 추가 (0.005~0.008 범위)",
            "RSI 42-58로 좁히기",
        ],
        "forbidden": [
            "시간대를 14시 이후로 확장 금지",
            "VWAP 이격도 하향 또는 제거 금지",
            "2연속 양봉을 1연속으로 약화 금지",
        ],
    },
    4: {
        "name": "AfternoonRSINeutralATR",
        "time_window": "13-15시 (오후)",
        "desc": "오후, ATR>=0.005, RSI 40-60, 2연속 양봉, VWAP 위",
        "wr_hints": [
            "VWAP 이격도 추가 (close > VWAP * 1.001~1.003)",
            "거래량 조건 추가 (vol > avg_vol * 1.2)",
            "3연속 양봉으로 강화",
            "RSI 42-58로 좁히기 (더 보수적인 진입)",
            "ATR 상한 추가 (변동성 너무 높으면 위험)",
            "시간을 13:30-14:30으로 좁히기 (가장 안정적 구간)",
        ],
        "forbidden": [
            "시간대를 13시 이전으로 확장 금지",
            "2연속 양봉을 1연속으로 약화 금지",
        ],
    },
    6: {
        "name": "AfternoonRSINeutralATRVolume",
        "time_window": "13-14:30시 (오후 좁은)",
        "desc": "오후, ATR 0.004-0.006, RSI 40-55, 1연속 양봉, VWAP 위, vol 1.3x",
        "wr_hints": [
            "2연속 양봉으로 강화 (이전 라운드에서 1연속→2연속이 승률 개선)",
            "RSI 42-53으로 더 좁히기",
            "vol 배수 1.4~1.6으로 올리기 (더 확실한 거래량)",
            "VWAP 이격도 추가 (close > VWAP * 1.001)",
            "ATR 범위 0.0042~0.0058로 좁히기",
            "직전 bar가 양봉이면서 몸통 > 꼬리 조건",
        ],
        "forbidden": [
            "시간대 변경 금지",
            "거래량 필터 제거 금지",
            "ATR 범위 필터를 단일 임계값으로 변경 금지",
        ],
    },
    8: {
        "name": "MorningWideRSINeutralATR",
        "time_window": "9:30-12시 (오전 와이드)",
        "desc": "오전 와이드, ATR>=0.005, RSI 40-60, VWAP*1.002, 2연속 양봉",
        "wr_hints": [
            "거래량 조건 추가 (vol > avg_vol_10 * 1.2, 전략1에서 효과 확인됨)",
            "VWAP 이격도 상향 (1.003~1.005)",
            "3연속 양봉으로 강화",
            "RSI 42-58로 좁히기",
            "ATR 상한 추가 (0.005~0.008 범위)",
            "시간을 9:30-11:30으로 좁히기 (점심 직전 제외)",
        ],
        "forbidden": [
            "시간대를 12시 이후로 확장 금지",
            "VWAP 이격도 하향 또는 제거 금지",
            "2연속 양봉을 1연속으로 약화 금지",
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
    return is_data, oos_data


def load_strategy_from_file(filepath):
    module_name = f"r5_{filepath.stem}_{datetime.now().strftime('%H%M%S%f')}"
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
        m = metrics.to_dict()
        return {
            "success": True,
            "return": m["total_return_pct"],
            "win_rate": m["win_rate"],
            "total_trades": m["total_trades"],
            "avg_pnl_pct": m.get("avg_pnl_pct", 0),
            "metrics": m,
            "trades_detail": [
                {"code": t.code, "pnl_pct": round(t.pnl_pct, 2), "exit_reason": t.exit_reason}
                for t in trades
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "return": -999, "win_rate": 0}


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
    text_out = '"""Data-driven intraday strategies designed by OpenAI."""\n\n'
    text_out += "\n".join(imports)
    text_out += "\n\n\ndef get_data_driven_strategies() -> list:\n"
    text_out += '    """Get instances of all data-driven strategies."""\n'
    text_out += "    return [\n"
    for cls in classes:
        text_out += f"        {cls}(),\n"
    text_out += "    ]\n\n\n"
    text_out += "__all__ = [\n"
    for cls in classes:
        text_out += f'    "{cls}",\n'
    text_out += '    "get_data_driven_strategies",\n'
    text_out += "]\n"
    (STRATEGY_DIR / "__init__.py").write_text(text_out, encoding="utf-8")


def build_winrate_prompt(strat_num, code, is_result, oos_result, round_num, history):
    """승률 중심 개선 프롬프트."""
    c = STRATEGY_CONSTRAINTS.get(strat_num, {})

    is_ret = is_result["return"]
    is_wr = is_result["win_rate"]
    is_trades = is_result["total_trades"]
    oos_ret = oos_result["return"]
    oos_wr = oos_result["win_rate"]

    trades = is_result.get("trades_detail", [])
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]

    avg_win = sum(t["pnl_pct"] for t in wins) / max(len(wins), 1)
    avg_loss = sum(t["pnl_pct"] for t in losses) / max(len(losses), 1)

    # 청산 이유별 분석
    exit_stats = {}
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        if reason not in exit_stats:
            exit_stats[reason] = {"count": 0, "wins": 0, "total_pnl": 0.0}
        exit_stats[reason]["count"] += 1
        exit_stats[reason]["total_pnl"] += t["pnl_pct"]
        if t["pnl_pct"] > 0:
            exit_stats[reason]["wins"] += 1

    exit_analysis = ""
    for reason, d in sorted(exit_stats.items(), key=lambda x: -x[1]["count"]):
        wr = d["wins"] / d["count"] * 100 if d["count"] > 0 else 0
        avg = d["total_pnl"] / d["count"]
        exit_analysis += f"  - {reason}: {d['count']}건, 승률={wr:.0f}%, 평균={avg:+.2f}%\n"

    # 패배 거래 분석
    loss_trades = sorted([t for t in trades if t["pnl_pct"] <= 0], key=lambda t: t["pnl_pct"])
    worst_text = "\n".join(
        f"  - {t['code']}: {t['pnl_pct']:+.2f}% ({t.get('exit_reason', '?')})"
        for t in loss_trades[:8]
    )

    # 패배 거래의 PnL 분포
    loss_pnls = [t["pnl_pct"] for t in loss_trades]
    if loss_pnls:
        sl_hits = len([p for p in loss_pnls if p <= -2.5])
        small_losses = len([p for p in loss_pnls if -2.5 < p <= -1.0])
        tiny_losses = len([p for p in loss_pnls if -1.0 < p <= 0])
        loss_dist = f"  - 대손실(-2.5%이하): {sl_hits}건, 중손실(-2.5~-1%): {small_losses}건, 소손실(-1~0%): {tiny_losses}건"
    else:
        loss_dist = "  - 손실 없음"

    # 히스토리
    history_text = ""
    if history:
        history_text = "\n### 이전 라운드 결과 (이 라운드):\n"
        for h in history[-8:]:
            status = "채택" if h["accepted"] else "거부"
            history_text += (
                f"- R{h['round']}: 승률={h['wr']:.1f}%, 수익={h['ret']:+.2f}% → {status}"
                f" ({h.get('reason', '')})\n"
            )
        history_text += "\n**위와 완전히 다른 접근이 필요합니다. 같은 변경을 반복하지 마세요!**\n"

    # Round 4 실패 이력
    r4_text = ROUND4_FAILURES.get(strat_num, "")

    hints = "\n".join(f"  - {h}" for h in c.get("wr_hints", []))
    forbidden = "\n".join(f"  - {f}" for f in c.get("forbidden", []))

    # 라운드별 다른 접근 제안
    approach_suggestions = [
        "RSI 범위를 좁혀서 더 보수적으로 진입하세요 (예: 42-58 또는 43-57)",
        "거래량 필터를 추가하거나 강화하세요 (avg_vol * 1.2~1.5)",
        "VWAP 이격도를 추가하거나 높이세요 (close > VWAP * 1.002~1.004)",
        "연속 양봉 조건을 3개로 강화하세요",
        "ATR 상한을 추가하세요 (너무 높은 변동성 = 위험한 진입)",
        "직전 bar의 몸통이 꼬리보다 긴 조건 추가 (강한 양봉만)",
        "당일 시가 대비 현재가가 일정% 이상 조건 추가",
        "이전 5bar 중 양봉 비율이 60% 이상인 조건 추가",
        "종가가 직전 N bar 최고가 대비 일정 범위 내 조건",
        "check_exit_fast에서 RSI>70일 때 청산 조건 추가",
    ]
    approach_idx = (round_num - 1) % len(approach_suggestions)
    current_approach = approach_suggestions[approach_idx]

    return f"""당신은 한국 주식 5분봉 단타 전략 **승률 개선** 전문가입니다.

## 전략 {strat_num}: {c.get('name', '')} (라운드 {round_num}/{MAX_ROUNDS})
- 시간대: {c.get('time_window', '')}
- 설명: {c.get('desc', '')}

### 현재 성과:
- **IS (44일)**: 수익률={is_ret:+.2f}%, 승률={is_wr:.1f}%, 거래={is_trades}건
- **OOS (15일)**: 수익률={oos_ret:+.2f}%, 승률={oos_wr:.1f}%

### 패배 거래 분석 (IS):
- 총 {is_trades}건: 승 {len(wins)}건 (평균 {avg_win:+.2f}%), 패 {len(losses)}건 (평균 {avg_loss:+.2f}%)
- 손실 분포:
{loss_dist}
- 청산 이유별:
{exit_analysis}
- 최악 거래 TOP 8:
{worst_text}

### Round 4 이력:
{r4_text}
{history_text}

### 현재 코드:
```python
{code}
```

## ★★★ 핵심 목표: 승률 최대화! ★★★

**현재 승률 {is_wr:.1f}% → 목표: {is_wr + 3:.1f}%+**

승률을 올리려면 "패배 거래를 제거"해야 합니다:
1. **진입 조건 강화**: 더 까다로운 필터를 추가해서 '약한 신호'를 걸러내세요
2. **불리한 상황 회피**: 손실이 큰 패턴을 감지하여 진입을 피하세요
3. **수익률은 반드시 유지!**: 수익률이 떨어지면 거부됩니다. 승률을 올리면서 수익률도 유지하세요

### 이번 라운드 시도 방향:
**→ {current_approach}**

### 승률 개선 아이디어:
{hints}

### ★ 금지 사항 ★
{forbidden}

### ★★★ 절대 규칙 ★★★
- **SL=3%, TP=5% 반드시 유지!**
- **RSI 중립 필터 반드시 유지! (범위는 미세 조정 가능, 35-65 이내)**
- **import: `from src.strategies.intraday.base import IntradayStrategy` 만 사용**
- 다른 import는 `import numpy as np` 그리고 `from src.strategies.intraday.base import IntradayStrategy, rolling_mean_np, rsi_np, vwap_np` 허용
- 클래스명 변경 금지!
- 작은 변경만! 한 번에 1-2가지만 변경!
- 거래가 40건 미만이면 실패 (과적합)
- position은 객체: position.entry_price (O), position["entry_price"] (X)
- check_exit_fast에서 position.entry_bar_idx (int) 사용 가능

**반드시 이전 라운드와 다른 변경을 하세요. 동일 코드 제출은 무조건 거부됩니다.**

**개선된 전체 코드만 반환. 마크다운 코드블록 없이 순수 Python만. 설명 금지.**"""


def optimize_strategy(client, strat_num, data, is_data, oos_data):
    """하나의 전략을 10라운드 승률 중심 최적화."""
    filepath = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
    if not filepath.exists():
        return None

    c = STRATEGY_CONSTRAINTS.get(strat_num, {})
    logger.info(f"\n{'=' * 70}")
    logger.info(f"전략 {strat_num}: {c.get('name', '')} ({c.get('time_window', '')})")
    logger.info(f"{'=' * 70}")

    current_code = filepath.read_text(encoding="utf-8")

    # 베이스라인
    strategy = load_strategy_from_file(filepath)
    is_base = run_backtest(strategy, is_data)
    oos_base = run_backtest(strategy, oos_data)
    full_base = run_backtest(strategy, data)

    if not is_base["success"] or not oos_base["success"] or not full_base["success"]:
        logger.error(f"  베이스라인 실패")
        return None

    logger.info(
        f"  베이스라인: Full 수익={full_base['return']:+.2f}%, 승률={full_base['win_rate']:.1f}%, "
        f"거래={full_base['total_trades']}건"
    )
    logger.info(
        f"  IS: 수익={is_base['return']:+.2f}%, 승률={is_base['win_rate']:.1f}% | "
        f"OOS: 수익={oos_base['return']:+.2f}%, 승률={oos_base['win_rate']:.1f}%"
    )

    best_code = current_code
    best_is = is_base
    best_oos = oos_base
    best_full = full_base
    history = []
    no_improve = 0
    prev_code_hash = None  # 동일 코드 감지

    for round_num in range(1, MAX_ROUNDS + 1):
        # temperature: 라운드가 진행될수록 높아지되, 실패 횟수에 따라 더 빠르게
        temp = 0.4 + (round_num - 1) * 0.08 + no_improve * 0.05
        temp = min(temp, 1.2)
        logger.info(f"\n  라운드 {round_num}/{MAX_ROUNDS} (temp={temp:.2f})")

        prompt = build_winrate_prompt(strat_num, best_code, best_is, best_oos, round_num, history)

        try:
            raw = call_openai(client, prompt, temperature=temp)
            code = clean_code(raw)

            # 동일 코드 감지
            code_hash = hash(code.strip())
            if code_hash == prev_code_hash:
                logger.warning(f"    동일 코드 반복 → 건너뜀")
                no_improve += 1
                history.append({
                    "round": round_num, "ret": 0, "wr": 0,
                    "accepted": False, "reason": "동일코드반복"
                })
                if no_improve >= EARLY_STOP_THRESHOLD:
                    logger.info(f"    {EARLY_STOP_THRESHOLD}회 연속 미개선 → 조기 종료")
                    break
                continue
            prev_code_hash = code_hash

            # 문법 확인
            try:
                compile(code, "<opt>", "exec")
            except SyntaxError as e:
                logger.warning(f"    문법 에러: {e}")
                history.append({"round": round_num, "ret": 0, "wr": 0, "accepted": False, "reason": "문법에러"})
                continue

            # import 수정
            if "from src.strategies.intraday.base import" not in code:
                if "from base import" in code:
                    code = code.replace("from base import IntradayStrategy",
                                       "from src.strategies.intraday.base import IntradayStrategy")
                else:
                    logger.warning(f"    import 누락")
                    history.append({"round": round_num, "ret": 0, "wr": 0, "accepted": False, "reason": "import누락"})
                    continue

            # 임시 파일 테스트
            tmp_path = STRATEGY_DIR / f"_tmp_r5_{strat_num}.py"
            tmp_path.write_text(code, encoding="utf-8")

            try:
                strategy = load_strategy_from_file(tmp_path)
            except Exception as e:
                logger.warning(f"    로드 에러: {e}")
                tmp_path.unlink(missing_ok=True)
                history.append({"round": round_num, "ret": 0, "wr": 0, "accepted": False, "reason": "로드에러"})
                continue

            # IS 백테스트
            is_result = run_backtest(strategy, is_data)
            if not is_result["success"]:
                logger.warning(f"    IS 에러: {is_result.get('error', '')}")
                tmp_path.unlink(missing_ok=True)
                continue

            # OOS 백테스트
            oos_result = run_backtest(strategy, oos_data)
            if not oos_result["success"]:
                logger.warning(f"    OOS 에러: {oos_result.get('error', '')}")
                tmp_path.unlink(missing_ok=True)
                continue

            # Full 백테스트
            full_result = run_backtest(strategy, data)
            tmp_path.unlink(missing_ok=True)

            if not full_result["success"]:
                continue

            new_ret = full_result["return"]
            new_wr = full_result["win_rate"]
            new_trades = full_result["total_trades"]
            new_oos_ret = oos_result["return"]

            logger.info(
                f"    Full: 수익={new_ret:+.2f}%, 승률={new_wr:.1f}%, 거래={new_trades}건"
            )
            logger.info(
                f"    IS: 수익={is_result['return']:+.2f}%, 승률={is_result['win_rate']:.1f}% | "
                f"OOS: 수익={new_oos_ret:+.2f}%, 승률={oos_result['win_rate']:.1f}%"
            )

            # ★ 승률 중심 채택 기준 (수익률 유지 필수) ★
            wr_improved = new_wr >= best_full["win_rate"] + 1.0  # 승률 1%p 이상 개선
            ret_acceptable = new_ret >= best_full["return"] - 0.5  # 수익률 -0.5% 이내 (거의 유지)
            oos_ok = new_oos_ret >= best_oos["return"] * 0.65  # OOS 35% 이상 하락 방지
            enough_trades = new_trades >= 40
            is_positive = is_result["return"] > 0  # IS에서 양수 유지

            # 보너스 1: 승률 3%p+ 이상이면 수익률 -1.0%까지 허용
            if new_wr >= best_full["win_rate"] + 3.0:
                ret_acceptable = new_ret >= best_full["return"] - 1.0

            # 보너스 2: 수익률도 올랐으면 승률 0.5%p 이상이면 채택
            if new_ret >= best_full["return"]:
                wr_improved = new_wr >= best_full["win_rate"] + 0.5

            # 보너스 3: 승률+수익률 동시 개선이면 무조건 채택
            both_improved = (new_wr > best_full["win_rate"]) and (new_ret >= best_full["return"])
            if both_improved and enough_trades and oos_ok:
                wr_improved = True
                ret_acceptable = True

            accepted = wr_improved and ret_acceptable and oos_ok and enough_trades and is_positive

            reason = ""
            if not wr_improved:
                reason = f"승률 미개선({best_full['win_rate']:.1f}→{new_wr:.1f}, 필요:{best_full['win_rate']+1:.1f}+)"
            elif not ret_acceptable:
                reason = f"수익 과다하락({best_full['return']:+.2f}→{new_ret:+.2f})"
            elif not oos_ok:
                reason = f"OOS 악화({best_oos['return']:+.2f}→{new_oos_ret:+.2f})"
            elif not enough_trades:
                reason = f"거래부족({new_trades}건)"
            elif not is_positive:
                reason = f"IS 마이너스({is_result['return']:+.2f})"

            history.append({
                "round": round_num,
                "ret": new_ret,
                "wr": new_wr,
                "accepted": accepted,
                "reason": reason if not accepted else "채택",
            })

            if accepted:
                logger.info(
                    f"    ★★ 채택! 승률: {best_full['win_rate']:.1f}→{new_wr:.1f}% (+{new_wr - best_full['win_rate']:.1f}), "
                    f"수익: {best_full['return']:+.2f}→{new_ret:+.2f}%"
                )
                best_code = code
                best_is = is_result
                best_oos = oos_result
                best_full = full_result
                no_improve = 0
            else:
                no_improve += 1
                logger.info(f"    거부: {reason} (미개선 {no_improve}회)")
                if no_improve >= EARLY_STOP_THRESHOLD:
                    logger.info(f"    {EARLY_STOP_THRESHOLD}회 연속 미개선 → 조기 종료")
                    break

        except Exception as e:
            logger.error(f"    에러: {e}")
            traceback.print_exc()

    # 결과
    result = {
        "strategy": strat_num,
        "name": c.get("name", ""),
        "base_return": full_base["return"],
        "base_win_rate": full_base["win_rate"],
        "base_trades": full_base["total_trades"],
        "final_return": best_full["return"],
        "final_win_rate": best_full["win_rate"],
        "final_trades": best_full["total_trades"],
        "wr_improved": best_full["win_rate"] > full_base["win_rate"],
        "rounds": history,
    }

    # 승률이 올랐으면 적용 (수익률이 약간 내려가도)
    if best_full["win_rate"] > full_base["win_rate"]:
        filepath.write_text(best_code, encoding="utf-8")
        logger.info(
            f"\n  ★ 전략 {strat_num} 적용: "
            f"승률 {full_base['win_rate']:.1f}%→{best_full['win_rate']:.1f}% "
            f"(+{best_full['win_rate'] - full_base['win_rate']:.1f}), "
            f"수익 {full_base['return']:+.2f}%→{best_full['return']:+.2f}%"
        )
    else:
        logger.info(f"\n  전략 {strat_num}: 승률 개선 없음, 원본 유지")

    return result


def main():
    logger.info("=" * 70)
    logger.info(f"Round 5 최적화: 승률(Win Rate) 중심 개선 ({MAX_ROUNDS}라운드/전략)")
    logger.info(f"모델: {OPENAI_MODEL}, 전략 6개 x {MAX_ROUNDS}라운드")
    logger.info(f"채택 기준: 승률 1%p+ 개선 AND 수익률 유지(-0.5% 이내)")
    logger.info("=" * 70)

    data = load_intraday_data()
    is_data, oos_data = split_data(data)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # 전체 전략 베이스라인
    logger.info("\n--- 최적화 전 베이스라인 ---")
    base_total_ret = 0
    base_wr_sum = 0
    base_count = 0
    for strat_num in [1, 2, 3, 4, 6, 8]:
        fp = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
        if fp.exists():
            strategy = load_strategy_from_file(fp)
            r = run_backtest(strategy, data)
            if r["success"]:
                base_total_ret += r["return"]
                base_wr_sum += r["win_rate"]
                base_count += 1
                logger.info(
                    f"  전략 {strat_num}: 수익={r['return']:+.2f}%, 승률={r['win_rate']:.1f}%, 거래={r['total_trades']}건"
                )
    base_avg_wr = base_wr_sum / max(base_count, 1)
    logger.info(f"  합산 수익: {base_total_ret:+.2f}%, 평균 승률: {base_avg_wr:.1f}%")

    # 6개 전략 순차 최적화
    all_results = {}
    for strat_num in [1, 2, 3, 4, 6, 8]:
        result = optimize_strategy(client, strat_num, data, is_data, oos_data)
        if result:
            all_results[strat_num] = result

    # __init__.py 재생성
    generate_init_file()

    # 최종 합산
    logger.info(f"\n{'=' * 70}")
    logger.info("★★★ Round 5 최종 결과 (승률 중심) ★★★")
    logger.info(f"{'=' * 70}")

    total_return = 0
    total_trades = 0
    total_wr_sum = 0
    total_count = 0

    for strat_num in [1, 2, 3, 4, 6, 8]:
        fp = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
        if not fp.exists():
            continue
        try:
            strategy = load_strategy_from_file(fp)
            r = run_backtest(strategy, data)
            if r["success"]:
                total_return += r["return"]
                total_trades += r["total_trades"]
                total_wr_sum += r["win_rate"]
                total_count += 1

                base_r = all_results.get(strat_num, {})
                base_ret = base_r.get("base_return", r["return"])
                base_wr = base_r.get("base_win_rate", r["win_rate"])
                delta_ret = r["return"] - base_ret
                delta_wr = r["win_rate"] - base_wr

                mark = "★" if delta_wr > 0 else " "
                logger.info(
                    f"  {mark} 전략 {strat_num} ({strategy.name}): "
                    f"승률={r['win_rate']:.1f}% ({delta_wr:+.1f}), "
                    f"수익={r['return']:+.2f}% ({delta_ret:+.2f}), "
                    f"거래={r['total_trades']}건"
                )
        except Exception as e:
            logger.error(f"  전략 {strat_num}: 에러 - {e}")

    final_avg_wr = total_wr_sum / max(total_count, 1)
    logger.info(f"\n  합산 수익률: {base_total_ret:+.2f}% → {total_return:+.2f}% ({total_return - base_total_ret:+.2f}%)")
    logger.info(f"  평균 승률: {base_avg_wr:.1f}% → {final_avg_wr:.1f}% ({final_avg_wr - base_avg_wr:+.1f}%)")
    logger.info(f"  총 거래: {total_trades}건")

    # 결과 저장
    report = {
        "timestamp": datetime.now().isoformat(),
        "round": "5_winrate",
        "model": OPENAI_MODEL,
        "max_rounds": MAX_ROUNDS,
        "base_combined_return": round(base_total_ret, 2),
        "final_combined_return": round(total_return, 2),
        "return_change": round(total_return - base_total_ret, 2),
        "base_avg_win_rate": round(base_avg_wr, 2),
        "final_avg_win_rate": round(final_avg_wr, 2),
        "wr_change": round(final_avg_wr - base_avg_wr, 2),
        "strategies": {str(k): v for k, v in all_results.items()},
    }

    report_path = project_root / "reports" / "round5_winrate_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info(f"\n결과 저장: {report_path}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
