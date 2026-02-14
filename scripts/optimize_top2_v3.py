#!/usr/bin/env python3
"""TOP 2 전략 GPT 고도화 V3 - 승리/패배 패턴 분석 기반

기존 V2와의 차이:
1. 승리/패배 트레이드의 공통 패턴 분석 (시간, RSI, ATR, 거래량 등)
2. GPT에게 단순 수치 변경이 아니라 새 조건 추가도 허용
3. 홍인기 필터 컨텍스트 포함
4. 포트폴리오 시뮬레이션으로 최종 검증
5. 라운드별 실패 분석 → 다음 라운드에 피드백

실행:
  python scripts/optimize_top2_v3.py           # 5라운드 (기본)
  python scripts/optimize_top2_v3.py --rounds 3  # 3라운드
"""

import importlib
import importlib.util
import json
import os
import sys
import traceback
from datetime import datetime, time as dt_time
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
from src.strategies.data_driven.daily_context import DailyContextLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"
MAX_ROUNDS = 5

# 백테스트 설정 (개별 전략 평가용)
BT_CONFIG = IntradayBacktestConfig(
    initial_capital=5_000_000,
    max_positions=3,
    position_size=0.30,
    commission_rate=0.00015,
    tax_rate=0.0023,
    force_close_time=dt_time(15, 20),
)

# 전략별 제약조건
STRATEGY_CONSTRAINTS = {
    1: {
        "name": "Morning RSI Neutral ATR",
        "time_window": "9:30-11시 (오전)",
        "core_logic": "RSI 40-60 + ATR>=0.45% + VWAP 위 + 직전 2양봉 + 거래량 1.2x",
        "forbidden": [
            "시간을 11시 이후로 확장 금지",
            "RSI 범위를 35-65 이상으로 넓히지 말것",
            "SL/TP 변경 절대 금지 (SL=3%, TP=5%)",
        ],
    },
    3: {
        "name": "Modified RSI Neutral ATR (Wide)",
        "time_window": "9-14시 (종일)",
        "core_logic": "RSI 40-60 + ATR>=0.5% + VWAP*1.002 위 + 직전 2양봉 + 홍인기(신고가/전고점돌파만)",
        "forbidden": [
            "시간을 14시 이후로 확장 금지",
            "VWAP 조건 제거 금지",
            "2양봉 조건을 1양봉으로 약화 금지",
            "SL/TP 변경 절대 금지 (SL=3%, TP=5%)",
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

    return is_data, oos_data, len(is_dates), len(oos_dates)


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


def run_backtest(strategy, data, daily_context=None):
    engine = IntradayBacktestEngineV2(BT_CONFIG)
    try:
        metrics, trades = engine.run(strategy, data, show_progress=False, daily_context=daily_context)
        return {
            "success": True,
            "metrics": metrics.to_dict(),
            "trades": trades,
            "trades_detail": [
                {
                    "code": t.code, "pnl_pct": round(t.pnl_pct, 3),
                    "exit_reason": t.exit_reason,
                    "entry_bar": getattr(t, "entry_bar_idx", 0),
                    "hold_bars": getattr(t, "hold_bars", 0),
                }
                for t in trades
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_trade_patterns(trades, data):
    """승리/패배 트레이드의 공통 패턴을 분석."""
    if not trades:
        return "거래 없음"

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]

    analysis = []
    analysis.append(f"## 트레이드 패턴 분석 (총 {len(trades)}건)")
    analysis.append(f"- 승: {len(wins)}건 (평균 +{np.mean([t.pnl_pct for t in wins]):.2f}%)")
    analysis.append(f"- 패: {len(losses)}건 (평균 {np.mean([t.pnl_pct for t in losses]):.2f}%)")

    # 1. 시간대별 승률
    analysis.append("\n### 시간대별 승률:")
    hour_stats = {}
    for t in trades:
        h = t.entry_time.hour if hasattr(t.entry_time, 'hour') else 0
        if h not in hour_stats:
            hour_stats[h] = {"win": 0, "total": 0, "pnl_sum": 0}
        hour_stats[h]["total"] += 1
        hour_stats[h]["pnl_sum"] += t.pnl_pct
        if t.pnl_pct > 0:
            hour_stats[h]["win"] += 1

    for h in sorted(hour_stats.keys()):
        s = hour_stats[h]
        wr = s["win"] / s["total"] * 100 if s["total"] else 0
        avg = s["pnl_sum"] / s["total"]
        analysis.append(f"  {h}시: {s['total']}건, WR={wr:.0f}%, 평균={avg:+.2f}%")

    # 2. 청산사유별
    analysis.append("\n### 청산사유별:")
    reason_stats = {}
    for t in trades:
        r = t.exit_reason
        if r not in reason_stats:
            reason_stats[r] = {"count": 0, "pnl_sum": 0, "wins": 0}
        reason_stats[r]["count"] += 1
        reason_stats[r]["pnl_sum"] += t.pnl_pct
        if t.pnl_pct > 0:
            reason_stats[r]["wins"] += 1
    for r, s in reason_stats.items():
        wr = s["wins"] / s["count"] * 100
        avg = s["pnl_sum"] / s["count"]
        analysis.append(f"  {r}: {s['count']}건, WR={wr:.0f}%, 평균={avg:+.2f}%")

    # 3. 보유시간별 승률
    analysis.append("\n### 보유시간(봉 수)별:")
    hold_bins = {"1-3봉": (1, 3), "4-10봉": (4, 10), "11-30봉": (11, 30), "31봉+": (31, 999)}
    for label, (lo, hi) in hold_bins.items():
        subset = [t for t in trades if lo <= getattr(t, "hold_bars", 0) <= hi]
        if subset:
            wr = sum(1 for t in subset if t.pnl_pct > 0) / len(subset) * 100
            avg = np.mean([t.pnl_pct for t in subset])
            analysis.append(f"  {label}: {len(subset)}건, WR={wr:.0f}%, 평균={avg:+.2f}%")

    # 4. 승리 vs 패배 거래의 진입 패턴 차이
    analysis.append("\n### 승리 vs 패배 진입시간 분포:")
    if wins:
        win_hours = [t.entry_time.hour for t in wins if hasattr(t.entry_time, 'hour')]
        if win_hours:
            analysis.append(f"  승리 평균 진입시간: {np.mean(win_hours):.1f}시")
    if losses:
        loss_hours = [t.entry_time.hour for t in losses if hasattr(t.entry_time, 'hour')]
        if loss_hours:
            analysis.append(f"  패배 평균 진입시간: {np.mean(loss_hours):.1f}시")

    # 5. 장마감 청산의 손익 분포
    close_trades = [t for t in trades if "장마감" in t.exit_reason]
    if close_trades:
        close_wins = sum(1 for t in close_trades if t.pnl_pct > 0)
        close_avg = np.mean([t.pnl_pct for t in close_trades])
        analysis.append(f"\n### 장마감 청산 (수수료 차감 전): {len(close_trades)}건, WR={close_wins/len(close_trades)*100:.0f}%, 평균={close_avg:+.2f}%")

    # 6. 최악의 거래 5건
    worst = sorted(trades, key=lambda t: t.pnl_pct)[:5]
    analysis.append("\n### 최악의 거래 TOP 5:")
    for t in worst:
        entry_h = t.entry_time.hour if hasattr(t.entry_time, 'hour') else '?'
        analysis.append(f"  {t.code} {entry_h}시: {t.pnl_pct:+.2f}% ({t.exit_reason})")

    # 7. 최고의 거래 5건
    best = sorted(trades, key=lambda t: t.pnl_pct, reverse=True)[:5]
    analysis.append("\n### 최고의 거래 TOP 5:")
    for t in best:
        entry_h = t.entry_time.hour if hasattr(t.entry_time, 'hour') else '?'
        analysis.append(f"  {t.code} {entry_h}시: {t.pnl_pct:+.2f}% ({t.exit_reason})")

    return "\n".join(analysis)


def build_optimization_prompt(strat_num, code, is_result, oos_result, pattern_analysis, round_num, history):
    """패턴 분석 기반 최적화 프롬프트."""
    constraints = STRATEGY_CONSTRAINTS.get(strat_num, {})

    is_m = is_result["metrics"]
    oos_m = oos_result["metrics"]

    forbidden = "\n".join(f"- {f}" for f in constraints.get("forbidden", []))

    # 이전 라운드 히스토리
    history_text = ""
    if history:
        history_text = "\n### 이전 라운드 결과:\n"
        for h in history[-5:]:
            status = "채택" if h["accepted"] else "거부"
            history_text += f"- R{h['round']}: IS={h['is_ret']:+.2f}%, OOS={h['oos_ret']:+.2f}%, WR={h.get('is_wr',0):.1f}% → {status} ({h.get('reason', '')})\n"
            if h.get("change_desc"):
                history_text += f"  변경: {h['change_desc']}\n"
        history_text += "\n**이전에 시도했던 것과 완전히 다른 접근을 해주세요!**\n"

    return f"""당신은 한국 주식 5분봉 단타 전략 최적화 전문가입니다.

## 전략 {strat_num}: {constraints.get('name', '')} (라운드 {round_num}/{MAX_ROUNDS})
- 시간대: {constraints.get('time_window', '')}
- 핵심 로직: {constraints.get('core_logic', '')}

### 현재 성과:
- **IS ({is_m['total_trades']}건)**: 승률={is_m['win_rate']:.1f}%, 수익률={is_m['total_return_pct']:+.2f}%
- **OOS ({oos_m['total_trades']}건)**: 승률={oos_m['win_rate']:.1f}%, 수익률={oos_m['total_return_pct']:+.2f}%

{pattern_analysis}
{history_text}

### 현재 코드:
```python
{code}
```

## 개선 요청

위 트레이드 패턴 분석을 참고하여 전략을 개선해주세요.

### 허용되는 개선 방법 (단순 수치 변경뿐 아니라 새 조건도 추가 가능!):
1. **새 지표/조건 추가**: 예) 이전 N봉 고점 돌파, 거래량 가속도, 가격 모멘텀, 봉 크기 비율 등
2. **기존 조건 강화/완화**: 임계값 미세 조정 (작은 변경만!)
3. **시간대 미세 조정**: 패턴 분석에서 승률 낮은 시간 제외
4. **패턴 필터 추가**: 장마감 청산에서 지는 패턴 제거
5. **precompute_day에 새 지표 추가 후 check_entry_fast에서 활용**

### ★★★ 핵심: numpy 배열 기반으로 precompute_day에서 계산하고 check_entry_fast에서 조건으로 사용 ★★★

### ★ 절대 금지 ★
{forbidden}
- **클래스명 변경 금지!**
- **import: `from src.strategies.intraday.base import IntradayStrategy` 유지**
- **import: `from src.strategies.data_driven.hong_filter_mixin import HongFilterMixin` 유지**
- **HongFilterMixin 상속 유지 (class ...Strategy(HongFilterMixin, IntradayStrategy))**
- **passes_hong_filter(), passes_intraday_value_filter() 호출 유지**
- **hong_confidence_boost() 호출 유지**
- **거래대금 지표 (cum_trading_value, bar_trading_value) 유지**
- **거래가 IS 기준 50건 미만이면 실패!**
- **check_exit_fast는 None 반환 유지 (절대 변경 금지)**

**반드시 전체 완전한 Python 코드만 반환. 마크다운 코드블록(```) 없이 순수 Python만. 설명/주석 최소화.**"""


def call_openai(client, prompt, temperature=0.5):
    model = OPENAI_MODEL
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if model.startswith("gpt-5"):
        kwargs["max_completion_tokens"] = 8000
    else:
        kwargs["max_tokens"] = 8000

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


def optimize_strategy(client, strat_num, data, is_data, oos_data, daily_context):
    """한 전략을 MAX_ROUNDS 만큼 최적화."""
    filepath = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
    if not filepath.exists():
        logger.error(f"전략 {strat_num} 파일 없음")
        return None

    current_code = filepath.read_text(encoding="utf-8")
    original_code = current_code

    # 베이스라인
    strategy = load_strategy_from_file(filepath)
    is_baseline = run_backtest(strategy, is_data, daily_context)
    oos_baseline = run_backtest(strategy, oos_data, daily_context)

    if not is_baseline["success"] or not oos_baseline["success"]:
        logger.error(f"  베이스라인 실패")
        return None

    is_base = is_baseline["metrics"]
    oos_base = oos_baseline["metrics"]
    logger.info(f"  베이스라인: IS={is_base['total_return_pct']:+.2f}% WR={is_base['win_rate']:.1f}% ({is_base['total_trades']}건)")
    logger.info(f"             OOS={oos_base['total_return_pct']:+.2f}% WR={oos_base['win_rate']:.1f}% ({oos_base['total_trades']}건)")

    # 패턴 분석 (IS 트레이드 기반)
    pattern_analysis = analyze_trade_patterns(is_baseline["trades"], is_data)

    best_code = current_code
    best_is = is_baseline
    best_oos = oos_baseline
    history = []
    applied_count = 0

    for round_num in range(1, MAX_ROUNDS + 1):
        temp = 0.4 + (round_num - 1) * 0.15  # 0.4 → 1.0
        temp = min(temp, 1.2)
        logger.info(f"\n  ── 라운드 {round_num}/{MAX_ROUNDS} (temp={temp:.2f}) ──")

        prompt = build_optimization_prompt(
            strat_num, best_code, best_is, best_oos,
            pattern_analysis, round_num, history,
        )

        try:
            raw = call_openai(client, prompt, temperature=temp)
            code = clean_code(raw)

            # 문법 확인
            try:
                compile(code, "<opt>", "exec")
            except SyntaxError as e:
                logger.warning(f"    문법 에러: {e}")
                history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "is_wr": 0, "accepted": False, "reason": f"문법에러"})
                continue

            # import 수정
            if "from base import" in code:
                code = code.replace("from base import IntradayStrategy",
                                    "from src.strategies.intraday.base import IntradayStrategy")

            # 필수 요소 확인
            if "HongFilterMixin" not in code:
                logger.warning(f"    HongFilterMixin 누락")
                history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "is_wr": 0, "accepted": False, "reason": "HongFilterMixin 누락"})
                continue

            if "passes_hong_filter" not in code:
                logger.warning(f"    passes_hong_filter 누락")
                history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "is_wr": 0, "accepted": False, "reason": "hong_filter 누락"})
                continue

            # 임시 파일 테스트
            tmp_path = STRATEGY_DIR / f"_tmp_strategy_{strat_num}.py"
            tmp_path.write_text(code, encoding="utf-8")

            try:
                strategy = load_strategy_from_file(tmp_path)
            except Exception as e:
                logger.warning(f"    로드 에러: {e}")
                tmp_path.unlink(missing_ok=True)
                history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "is_wr": 0, "accepted": False, "reason": f"로드에러: {str(e)[:50]}"})
                continue

            # IS 백테스트
            is_result = run_backtest(strategy, is_data, daily_context)
            if not is_result["success"]:
                logger.warning(f"    IS 에러: {is_result['error']}")
                tmp_path.unlink(missing_ok=True)
                continue

            new_is = is_result["metrics"]

            # OOS 백테스트
            oos_result = run_backtest(strategy, oos_data, daily_context)
            tmp_path.unlink(missing_ok=True)

            if not oos_result["success"]:
                logger.warning(f"    OOS 에러: {oos_result['error']}")
                continue

            new_oos = oos_result["metrics"]

            logger.info(f"    IS: {new_is['total_return_pct']:+.2f}% WR={new_is['win_rate']:.1f}% ({new_is['total_trades']}건)")
            logger.info(f"    OOS: {new_oos['total_return_pct']:+.2f}% WR={new_oos['win_rate']:.1f}% ({new_oos['total_trades']}건)")

            # 판단 기준
            old_is_ret = best_is["metrics"]["total_return_pct"]
            old_oos_ret = best_oos["metrics"]["total_return_pct"]
            old_is_wr = best_is["metrics"]["win_rate"]

            is_improved = new_is["total_return_pct"] > old_is_ret
            oos_not_worse = new_oos["total_return_pct"] >= old_oos_ret * 0.7
            enough_trades = new_is["total_trades"] >= 50 and new_oos["total_trades"] >= 10
            wr_not_crashed = new_is["win_rate"] >= old_is_wr - 5  # WR 5%p 이상 하락 금지

            # 종합 점수 (IS 60% + OOS 40%)
            old_combined = old_is_ret * 0.6 + old_oos_ret * 0.4
            new_combined = new_is["total_return_pct"] * 0.6 + new_oos["total_return_pct"] * 0.4
            combined_improved = new_combined > old_combined

            accepted = is_improved and oos_not_worse and enough_trades and wr_not_crashed and combined_improved

            reason = ""
            if not enough_trades:
                reason = f"거래 부족(IS:{new_is['total_trades']},OOS:{new_oos['total_trades']})"
            elif not is_improved:
                reason = f"IS 미개선({old_is_ret:+.1f}→{new_is['total_return_pct']:+.1f})"
            elif not oos_not_worse:
                reason = f"OOS 악화({old_oos_ret:+.1f}→{new_oos['total_return_pct']:+.1f})"
            elif not wr_not_crashed:
                reason = f"WR 급락({old_is_wr:.1f}→{new_is['win_rate']:.1f})"
            elif not combined_improved:
                reason = f"종합 미개선({old_combined:+.1f}→{new_combined:+.1f})"

            # 코드 차이 요약 (간단히)
            old_lines = set(best_code.strip().split("\n"))
            new_lines = set(code.strip().split("\n"))
            added = new_lines - old_lines
            change_desc = f"{len(added)}줄 변경/추가" if added else "변경 없음"

            history.append({
                "round": round_num,
                "is_ret": new_is["total_return_pct"],
                "oos_ret": new_oos["total_return_pct"],
                "is_wr": new_is["win_rate"],
                "accepted": accepted,
                "reason": reason if not accepted else "채택",
                "change_desc": change_desc,
            })

            if accepted:
                logger.info(f"    ★ 채택! IS: {old_is_ret:+.2f}→{new_is['total_return_pct']:+.2f}%, OOS: {old_oos_ret:+.2f}→{new_oos['total_return_pct']:+.2f}%")
                best_code = code
                best_is = is_result
                best_oos = oos_result
                applied_count += 1
                # 새 패턴 분석
                pattern_analysis = analyze_trade_patterns(is_result["trades"], is_data)
            else:
                logger.info(f"    ✗ 거부: {reason}")

        except Exception as e:
            logger.error(f"    에러: {e}")
            traceback.print_exc()
            history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "is_wr": 0, "accepted": False, "reason": f"에러: {str(e)[:50]}"})

    # 최종 적용
    final_is = best_is["metrics"]["total_return_pct"]
    final_oos = best_oos["metrics"]["total_return_pct"]
    base_is = is_base["total_return_pct"]
    base_oos = oos_base["total_return_pct"]

    if final_is > base_is:
        filepath.write_text(best_code, encoding="utf-8")
        logger.info(f"\n  ★★ 전략 {strat_num} 최종 적용: IS {base_is:+.2f}→{final_is:+.2f}%, OOS {base_oos:+.2f}→{final_oos:+.2f}%")
        return {
            "improved": True,
            "is_before": base_is, "is_after": final_is,
            "oos_before": base_oos, "oos_after": final_oos,
            "wr_before": is_base["win_rate"], "wr_after": best_is["metrics"]["win_rate"],
            "rounds_applied": applied_count,
        }
    else:
        logger.info(f"\n  전략 {strat_num}: {MAX_ROUNDS}라운드 후 개선 없음, 원본 유지")
        filepath.write_text(original_code, encoding="utf-8")
        return {
            "improved": False,
            "is_before": base_is, "is_after": base_is,
            "oos_before": base_oos, "oos_after": base_oos,
            "wr_before": is_base["win_rate"], "wr_after": is_base["win_rate"],
            "rounds_applied": 0,
        }


def run_portfolio_validation(data, daily_context):
    """포트폴리오 시뮬레이션으로 최종 검증."""
    import copy
    from scripts.simulate_portfolio import run_portfolio_simulation, print_simulation_result, INITIAL_CAPITAL
    from src.strategies.data_driven import get_data_driven_strategies

    strategies = get_data_driven_strategies()
    cap, trades, daily = run_portfolio_simulation(
        strategies, data, daily_context=daily_context, hong_enabled=True, label="최종검증",
    )
    print_simulation_result(cap, trades, daily, "최종 포트폴리오 (홍인기 ON)")
    return cap


def main():
    global MAX_ROUNDS
    rounds = MAX_ROUNDS
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--rounds" and i < len(sys.argv) - 1:
            rounds = int(sys.argv[i + 1])

    MAX_ROUNDS = rounds

    print("=" * 70)
    print(f"  TOP 2 전략 GPT 고도화 V3")
    print(f"  모델: {OPENAI_MODEL}, {MAX_ROUNDS}라운드/전략")
    print(f"  패턴 분석 기반 + 새 조건 추가 허용")
    print("=" * 70)

    # 데이터 로드
    data = load_intraday_data()
    all_dates = sorted(set(d for df in data.values() for d in df.index.date))
    print(f"\n  데이터: {len(data)}종목, {len(all_dates)}거래일")

    is_data, oos_data, is_days, oos_days = split_data(data)
    print(f"  IS: {is_days}일, OOS: {oos_days}일")

    # 일별 컨텍스트
    codes = list(data.keys())
    print(f"  일별 컨텍스트 로딩 중...")
    loader = DailyContextLoader()
    daily_context = loader.load(codes, min(all_dates), max(all_dates))
    print(f"  컨텍스트: {sum(len(v) for v in daily_context.values())}건")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # 포트폴리오 시뮬 (BEFORE)
    print(f"\n{'=' * 70}")
    print(f"  [BEFORE] 최적화 전 포트폴리오")
    print(f"{'=' * 70}")
    before_cap = run_portfolio_validation(data, daily_context)

    # 전략 최적화
    results = {}
    for strat_num in [1, 3]:
        print(f"\n{'=' * 70}")
        print(f"  전략 {strat_num} 최적화 시작")
        print(f"{'=' * 70}")
        result = optimize_strategy(client, strat_num, data, is_data, oos_data, daily_context)
        if result:
            results[strat_num] = result

    # __init__.py 재생성
    from scripts.optimize_with_ai_rounds_v2 import generate_init_file
    generate_init_file()

    # 포트폴리오 시뮬 (AFTER)
    print(f"\n{'=' * 70}")
    print(f"  [AFTER] 최적화 후 포트폴리오")
    print(f"{'=' * 70}")
    after_cap = run_portfolio_validation(data, daily_context)

    # 최종 요약
    print(f"\n{'━' * 70}")
    print(f"  최종 요약")
    print(f"{'━' * 70}")
    for sn, r in results.items():
        status = "★개선" if r["improved"] else "유지"
        print(f"  전략 {sn}: [{status}] IS {r['is_before']:+.2f}→{r['is_after']:+.2f}%, "
              f"OOS {r['oos_before']:+.2f}→{r['oos_after']:+.2f}%, "
              f"WR {r['wr_before']:.1f}→{r['wr_after']:.1f}%")

    before_ret = (before_cap / 10_000_000 - 1) * 100
    after_ret = (after_cap / 10_000_000 - 1) * 100
    print(f"\n  포트폴리오: {before_ret:+.2f}% → {after_ret:+.2f}% (차이: {after_ret - before_ret:+.2f}%p)")

    # 결과 저장
    report = {
        "timestamp": datetime.now().isoformat(),
        "model": OPENAI_MODEL,
        "rounds": MAX_ROUNDS,
        "strategies": {str(k): v for k, v in results.items()},
        "portfolio_before": before_ret,
        "portfolio_after": after_ret,
    }
    report_path = project_root / "reports" / "optimize_top2_v3_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  결과 저장: {report_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
