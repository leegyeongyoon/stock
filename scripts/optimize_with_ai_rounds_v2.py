#!/usr/bin/env python3
"""GPT-4o와 함께 라운드를 돌면서 전략을 개선하는 스크립트 V2.

V1 대비 개선점:
1. OOS 검증 필수 - IS에서 개선되어도 OOS에서 나빠지면 거부
2. 전략별 맞춤 제약조건 - 각 전략의 특성에 맞는 프롬프트
3. 온도 다양성 - 라운드별 temperature 조절
4. 새 전략 추가 기능 - 기존 전략을 기반으로 신규 변형 생성
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
from src.database.connection import get_engine
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ROUNDS = 10
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"

# 전략별 맞춤 제약조건
STRATEGY_CONSTRAINTS = {
    1: {
        "name": "Morning RSI Neutral ATR",
        "time_window": "9-11시 (오전)",
        "core_filters": "RSI 40-60, ATR 필터, 양봉 확인",
        "optimization_hints": [
            "오전 장초반은 변동성이 크므로 ATR 임계값 조절 가능 (0.004~0.006 범위)",
            "직전 2bar 양봉 확인은 유지 (현재 핵심 필터)",
            "시간 윈도우를 9:30-11:00으로 좁혀서 장초반 노이즈 제거 시도 가능",
            "VWAP 위 조건 추가하면 승률 상승할 수 있음",
        ],
        "forbidden": [
            "시간 윈도우를 11시 이후로 확장 금지 (전략 2와 겹침)",
            "RSI 범위를 35-65 이상으로 넓히지 말것 (핵심 필터 약화)",
        ],
    },
    2: {
        "name": "Lunch RSI Neutral ATR Volume",
        "time_window": "11-13시 (점심)",
        "core_filters": "RSI 40-60, ATR >= 0.005389, 거래량비율 >= 1.17, 양봉 확인",
        "optimization_hints": [
            "점심시간은 거래량이 적어 vol_ratio 임계값 조절 가능 (1.1~1.3 범위)",
            "연속 양봉 조건 추가 (직전 2bar) 시도 가능",
            "ATR 임계값: 0.005~0.006 범위에서 조절",
            "check_exit_fast에서 RSI 75+ 조기 익절 시도 가능",
        ],
        "forbidden": [
            "시간 윈도우를 11시 이전으로 확장 금지 (전략 1과 겹침)",
            "거래량 필터 제거 금지 (점심시간대 핵심 필터)",
            "RSI 범위를 42-58로 좁히지 말것 (거래 수 급감, 과적합 위험!)",
        ],
    },
    3: {
        "name": "Modified RSI Neutral ATR (Wide Window)",
        "time_window": "9-14시 (전 시간)",
        "core_filters": "RSI 40-60, ATR >= 0.005389, VWAP 위, 연속 2양봉",
        "optimization_hints": [
            "VWAP 이격도 조건 추가 가능 (close > vwap * 1.002 등)",
            "연속 양봉 패턴을 3연속으로 강화하면 승률 올라갈 수 있음 (거래 감소 주의)",
            "ATR 임계값 약간 조절 가능 (0.005~0.006)",
            "시간대별 필터 추가: 장초반(9-10시)과 점심(12-13시)에 추가 조건",
        ],
        "forbidden": [
            "VWAP 위 조건 제거 금지 (전략 3의 고유 차별점)",
            "연속 2양봉 조건을 1양봉으로 약화 금지",
            "시간 윈도우를 14시 이후로 확장 금지 (장마감 위험)",
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


def run_backtest(strategy, data):
    config = IntradayBacktestConfig(initial_capital=5_000_000, max_positions=3, position_size=0.3)
    engine = IntradayBacktestEngineV2(config)
    try:
        metrics, trades = engine.run(strategy, data, show_progress=False)
        return {
            "success": True,
            "metrics": metrics.to_dict(),
            "trades_detail": [
                {"code": t.code, "pnl_pct": round(t.pnl_pct, 2), "exit_reason": t.exit_reason,
                 "entry_bar": getattr(t, "entry_bar_idx", 0), "hold_bars": getattr(t, "hold_bars", 0)}
                for t in trades
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def build_optimization_prompt(strat_num, code, is_metrics, is_trades, oos_metrics, round_num, history):
    """전략별 맞춤 최적화 프롬프트."""
    constraints = STRATEGY_CONSTRAINTS.get(strat_num, {})

    is_wr = is_metrics.get("win_rate", 0)
    is_ret = is_metrics.get("total_return_pct", 0)
    is_trades_count = is_metrics.get("total_trades", 0)
    oos_wr = oos_metrics.get("win_rate", 0)
    oos_ret = oos_metrics.get("total_return_pct", 0)
    oos_trades_count = oos_metrics.get("total_trades", 0)

    # 거래 상세 분석
    wins = [t for t in is_trades if t["pnl_pct"] > 0]
    losses = [t for t in is_trades if t["pnl_pct"] <= 0]

    exit_reasons = {}
    for t in is_trades:
        reason = t.get("exit_reason", "unknown")
        if reason not in exit_reasons:
            exit_reasons[reason] = {"count": 0, "total_pnl": 0.0}
        exit_reasons[reason]["count"] += 1
        exit_reasons[reason]["total_pnl"] += t["pnl_pct"]

    trade_analysis = f"### 거래 통계 (IS)\n"
    trade_analysis += f"- 총 {is_trades_count}건: 승 {len(wins)}건 (평균 {sum(t['pnl_pct'] for t in wins)/max(len(wins),1):+.2f}%), 패 {len(losses)}건 (평균 {sum(t['pnl_pct'] for t in losses)/max(len(losses),1):+.2f}%)\n\n"
    trade_analysis += "### 청산 이유별:\n"
    for reason, d in sorted(exit_reasons.items(), key=lambda x: x[1]["total_pnl"]):
        avg = d["total_pnl"] / d["count"]
        trade_analysis += f"- {reason}: {d['count']}건, 평균 {avg:+.2f}%\n"

    worst = sorted(is_trades, key=lambda t: t["pnl_pct"])[:5]
    trade_analysis += "\n### 최악의 거래 TOP 5:\n"
    for t in worst:
        trade_analysis += f"- {t['code']}: {t['pnl_pct']:+.2f}% ({t.get('exit_reason', '?')})\n"

    # 전략별 맞춤 제약조건
    hints = "\n".join(f"- {h}" for h in constraints.get("optimization_hints", []))
    forbidden = "\n".join(f"- {f}" for f in constraints.get("forbidden", []))

    # 이전 라운드 히스토리
    history_text = ""
    if history:
        history_text = "\n### 이전 라운드 결과:\n"
        for h in history[-5:]:
            status = "채택" if h["accepted"] else "거부"
            history_text += f"- R{h['round']}: IS={h['is_ret']:+.2f}%, OOS={h['oos_ret']:+.2f}% → {status} ({h.get('reason', '')})\n"
        history_text += "\n**이전에 시도했던 접근과 다른 방향으로 시도해주세요!**\n"

    return f"""당신은 한국 주식 5분봉 단타 전략 최적화 전문가입니다.

## 전략 {strat_num}: {constraints.get('name', '')} (라운드 {round_num}/{MAX_ROUNDS})
- 시간대: {constraints.get('time_window', '')}
- 핵심 필터: {constraints.get('core_filters', '')}

### 현재 성과:
- **IS (44일)**: 승률={is_wr:.1f}%, 수익률={is_ret:+.2f}%, 거래={is_trades_count}건
- **OOS (15일)**: 승률={oos_wr:.1f}%, 수익률={oos_ret:+.2f}%, 거래={oos_trades_count}건

{trade_analysis}
{history_text}

### 현재 코드:
```python
{code}
```

## 개선 요청

이 전략을 **더 높은 수익률**로 개선해주세요. IS와 OOS 모두 개선되어야 합니다.

### 이 전략에 적합한 개선 방향:
{hints}

### ★ 절대 금지 ★
{forbidden}

### ★★★ 공통 절대 규칙 ★★★
- **SL=3%, TP=5% 반드시 유지!**
- **RSI 40-60 중립 필터 반드시 유지!**
- **import: `from src.strategies.intraday.base import IntradayStrategy` 만 사용**
- 클래스명 변경 금지!
- 작은 변경만! 한 번에 1-2가지만 변경!
- 거래가 50건 미만이면 실패!

**개선된 전체 코드만 반환. 마크다운 코드블록 없이 순수 Python만. 설명 금지.**"""


def build_new_strategy_prompt(strat_num, winning_code, winning_name, time_window, special_condition):
    """새 전략 생성용 프롬프트."""
    return f"""당신은 한국 주식 5분봉 단타 전략 설계 전문가입니다.

## 성공한 기존 전략 코드:
```python
{winning_code}
```

이 전략은 +수익을 기록했습니다. 이 코드를 기반으로 **새로운 변형 전략**을 만들어주세요.

## 새 전략 요구사항:
- 전략 번호: {strat_num}
- 시간대: {time_window}
- 특별 조건: {special_condition}
- 클래스명: 이 전략에 맞는 영어 클래스명 (IntradayStrategy 상속)
- SL=3%, TP=5% 필수!
- RSI 40-60 중립 필터 필수!
- ATR 필터 필수! (임계값: 0.004~0.006 사이)
- check_entry_fast()와 check_exit_fast() 구현

### 기반 전략({winning_name})과의 차별점:
- 시간대가 다름: {time_window}
- 추가 조건: {special_condition}
- 기존 전략과 겹치는 신호는 최소화

### ★★★ 절대 규칙 ★★★
- **import: `from src.strategies.intraday.base import IntradayStrategy` 만 사용**
- 다른 import는 numpy만 허용
- IntradayStrategy를 상속해야 함
- super().__init__(name="전략이름") 호출
- self.min_bars, self.stop_loss_pct, self.take_profit_pct 설정
- precompute_day(), check_entry_fast(), check_exit_fast(), check_entry(), check_exit() 모두 구현

**전체 Python 코드만 반환. 마크다운 코드블록 없이 순수 Python만. 설명 금지.**"""


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


def generate_init_file():
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    imports, classes = [], []
    for i in range(1, 10):  # Support up to 9 strategies
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


def optimize_existing_strategies(client, data, is_data, oos_data):
    """기존 전략 최적화 라운드."""
    logger.info("\n" + "=" * 70)
    logger.info("Phase 1: 기존 전략 최적화 (OOS 검증 포함)")
    logger.info("=" * 70)

    improvements = {}

    for strat_num in [1, 2, 3]:
        filepath = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
        if not filepath.exists():
            continue

        logger.info(f"\n{'=' * 60}")
        logger.info(f"전략 {strat_num}: {filepath.name}")
        logger.info(f"{'=' * 60}")

        current_code = filepath.read_text(encoding="utf-8")

        # 베이스라인 (IS + OOS)
        strategy = load_strategy_from_file(filepath)
        is_baseline = run_backtest(strategy, is_data)
        oos_baseline = run_backtest(strategy, oos_data)

        if not is_baseline["success"] or not oos_baseline["success"]:
            logger.error(f"  베이스라인 실패")
            continue

        is_base_ret = is_baseline["metrics"]["total_return_pct"]
        oos_base_ret = oos_baseline["metrics"]["total_return_pct"]
        logger.info(
            f"  베이스라인: IS={is_base_ret:+.2f}%, OOS={oos_base_ret:+.2f}%, "
            f"IS거래={is_baseline['metrics']['total_trades']}건"
        )

        best_code = current_code
        best_is_metrics = is_baseline["metrics"]
        best_oos_metrics = oos_baseline["metrics"]
        best_is_ret = is_base_ret
        best_oos_ret = oos_base_ret
        best_is_trades = is_baseline["trades_detail"]
        no_improve_count = 0
        history = []

        for round_num in range(1, MAX_ROUNDS + 1):
            # 라운드별 temperature 조절 (다양성 확보)
            temp = 0.4 + (round_num - 1) * 0.08  # 0.4 → 1.12
            temp = min(temp, 1.2)
            logger.info(f"\n  라운드 {round_num}/{MAX_ROUNDS} (temp={temp:.2f})")

            prompt = build_optimization_prompt(
                strat_num, best_code, best_is_metrics, best_is_trades,
                best_oos_metrics, round_num, history,
            )

            try:
                raw = call_openai(client, prompt, temperature=temp)
                code = clean_code(raw)

                try:
                    compile(code, "<opt>", "exec")
                except SyntaxError as e:
                    logger.warning(f"    문법 에러: {e}")
                    history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "accepted": False, "reason": f"문법에러: {e}"})
                    continue

                # 임시 파일 테스트
                tmp_path = STRATEGY_DIR / f"_tmp_strategy_{strat_num}.py"
                tmp_path.write_text(code, encoding="utf-8")

                try:
                    strategy = load_strategy_from_file(tmp_path)
                except Exception as e:
                    logger.warning(f"    로드 에러: {e}")
                    tmp_path.unlink(missing_ok=True)
                    history.append({"round": round_num, "is_ret": 0, "oos_ret": 0, "accepted": False, "reason": f"로드에러: {e}"})
                    continue

                # IS 백테스트
                is_result = run_backtest(strategy, is_data)
                if not is_result["success"]:
                    logger.warning(f"    IS 에러: {is_result['error']}")
                    tmp_path.unlink(missing_ok=True)
                    continue

                new_is_ret = is_result["metrics"]["total_return_pct"]
                new_is_trades = is_result["metrics"]["total_trades"]

                # OOS 백테스트 (핵심! 과적합 방지)
                oos_result = run_backtest(strategy, oos_data)
                tmp_path.unlink(missing_ok=True)

                if not oos_result["success"]:
                    logger.warning(f"    OOS 에러: {oos_result['error']}")
                    continue

                new_oos_ret = oos_result["metrics"]["total_return_pct"]
                new_oos_trades = oos_result["metrics"]["total_trades"]

                logger.info(
                    f"    결과: IS={new_is_ret:+.2f}% (거래 {new_is_trades}건), "
                    f"OOS={new_oos_ret:+.2f}% (거래 {new_oos_trades}건)"
                )

                # ★ 개선 판단: IS 개선 + OOS도 나빠지지 않아야 함
                is_improved = new_is_ret > best_is_ret
                oos_not_worse = new_oos_ret >= best_oos_ret * 0.7  # OOS가 30% 이상 하락하면 거부
                enough_trades = new_is_trades >= 50 and new_oos_trades >= 10
                # 종합 수익 (IS + OOS 가중 평균) 도 개선되어야 함
                old_combined = best_is_ret * 0.6 + best_oos_ret * 0.4
                new_combined = new_is_ret * 0.6 + new_oos_ret * 0.4
                combined_improved = new_combined > old_combined

                accepted = is_improved and oos_not_worse and enough_trades and combined_improved

                reason = ""
                if not is_improved:
                    reason = f"IS 미개선({best_is_ret:+.2f}%→{new_is_ret:+.2f}%)"
                elif not oos_not_worse:
                    reason = f"OOS 악화({best_oos_ret:+.2f}%→{new_oos_ret:+.2f}%)"
                elif not enough_trades:
                    reason = f"거래 부족(IS:{new_is_trades},OOS:{new_oos_trades})"
                elif not combined_improved:
                    reason = f"종합 미개선({old_combined:+.2f}%→{new_combined:+.2f}%)"

                history.append({
                    "round": round_num,
                    "is_ret": new_is_ret,
                    "oos_ret": new_oos_ret,
                    "accepted": accepted,
                    "reason": reason if not accepted else "개선 채택",
                })

                if accepted:
                    logger.info(
                        f"    ★ 채택! IS: {best_is_ret:+.2f}%→{new_is_ret:+.2f}%, "
                        f"OOS: {best_oos_ret:+.2f}%→{new_oos_ret:+.2f}%"
                    )
                    best_code = code
                    best_is_metrics = is_result["metrics"]
                    best_oos_metrics = oos_result["metrics"]
                    best_is_ret = new_is_ret
                    best_oos_ret = new_oos_ret
                    best_is_trades = is_result["trades_detail"]
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
        if best_is_ret > is_base_ret:
            filepath.write_text(best_code, encoding="utf-8")
            logger.info(
                f"\n  ★ 전략 {strat_num} 개선 적용: "
                f"IS {is_base_ret:+.2f}%→{best_is_ret:+.2f}%, "
                f"OOS {oos_base_ret:+.2f}%→{best_oos_ret:+.2f}%"
            )
            improvements[strat_num] = {
                "is_before": is_base_ret, "is_after": best_is_ret,
                "oos_before": oos_base_ret, "oos_after": best_oos_ret,
            }
        else:
            logger.info(f"\n  전략 {strat_num}: 개선 없음, 원본 유지")
            improvements[strat_num] = {
                "is_before": is_base_ret, "is_after": is_base_ret,
                "oos_before": oos_base_ret, "oos_after": oos_base_ret,
            }

    return improvements


def create_new_strategies(client, data, is_data, oos_data, start_num=4, count=3):
    """새 전략을 GPT에게 요청하여 생성."""
    logger.info("\n" + "=" * 70)
    logger.info(f"Phase 2: 새 전략 생성 (전략 {start_num}~{start_num + count - 1})")
    logger.info("=" * 70)

    # 최고 성과 전략 코드 읽기
    best_code = None
    best_ret = -999
    for i in range(1, start_num):
        fp = STRATEGY_DIR / f"intraday_strategy_{i}.py"
        if fp.exists():
            strategy = load_strategy_from_file(fp)
            result = run_backtest(strategy, data)
            if result["success"]:
                ret = result["metrics"]["total_return_pct"]
                if ret > best_ret:
                    best_ret = ret
                    best_code = fp.read_text(encoding="utf-8")
                    best_name = strategy.name

    if best_code is None:
        logger.error("기반 전략 없음!")
        return {}

    logger.info(f"기반 전략: {best_name} ({best_ret:+.2f}%)")

    # 새 전략 변형 정의
    new_strategies = [
        {
            "num": start_num,
            "time_window": "10-12시 (오전 후반~점심 초반)",
            "special_condition": "RSI 40-55 (약간 좁은 중립 하단) + 거래량 20일 평균 대비 1.5배 이상 + VWAP 위",
        },
        {
            "num": start_num + 1,
            "time_window": "9-11시 (오전)",
            "special_condition": "RSI 45-60 (중립 상단) + ATR 상위 15% + 직전 3bar 연속 양봉 + 시가 대비 1% 이상 상승",
        },
        {
            "num": start_num + 2,
            "time_window": "13-14시30분 (오후)",
            "special_condition": "RSI 40-55 + ATR 필터 + VWAP 위 + 거래량 급증(1.3배+) + 직전 2연속 양봉",
        },
    ]

    created = {}

    for strat_def in new_strategies[:count]:
        num = strat_def["num"]
        filepath = STRATEGY_DIR / f"intraday_strategy_{num}.py"

        logger.info(f"\n{'=' * 60}")
        logger.info(f"신규 전략 {num}: {strat_def['time_window']}")
        logger.info(f"{'=' * 60}")

        accepted = False
        for attempt in range(5):
            temp = 0.5 + attempt * 0.15
            logger.info(f"  시도 {attempt + 1}/5 (temp={temp:.2f})")

            prompt = build_new_strategy_prompt(
                num, best_code, best_name,
                strat_def["time_window"],
                strat_def["special_condition"],
            )

            try:
                raw = call_openai(client, prompt, temperature=temp)
                code = clean_code(raw)

                # 문법 확인
                try:
                    compile(code, "<new>", "exec")
                except SyntaxError as e:
                    logger.warning(f"    문법 에러: {e}")
                    continue

                # import 수정 (GPT가 종종 잘못 생성)
                if "from base import" in code:
                    code = code.replace("from base import IntradayStrategy",
                                       "from src.strategies.intraday.base import IntradayStrategy")

                filepath.write_text(code, encoding="utf-8")

                try:
                    strategy = load_strategy_from_file(filepath)
                except Exception as e:
                    logger.warning(f"    로드 에러: {e}")
                    filepath.unlink(missing_ok=True)
                    continue

                # IS 백테스트
                is_result = run_backtest(strategy, is_data)
                if not is_result["success"]:
                    logger.warning(f"    IS 에러: {is_result['error']}")
                    filepath.unlink(missing_ok=True)
                    continue

                is_ret = is_result["metrics"]["total_return_pct"]
                is_trades = is_result["metrics"]["total_trades"]

                # OOS 백테스트
                oos_result = run_backtest(strategy, oos_data)
                if not oos_result["success"]:
                    logger.warning(f"    OOS 에러: {oos_result['error']}")
                    filepath.unlink(missing_ok=True)
                    continue

                oos_ret = oos_result["metrics"]["total_return_pct"]
                oos_trades = oos_result["metrics"]["total_trades"]

                logger.info(
                    f"    결과: IS={is_ret:+.2f}% ({is_trades}건), "
                    f"OOS={oos_ret:+.2f}% ({oos_trades}건)"
                )

                # 양수 수익 + 충분한 거래
                if is_ret > 0 and oos_ret > -2 and is_trades >= 30:
                    # 전체 데이터 검증
                    full_result = run_backtest(strategy, data)
                    if full_result["success"]:
                        full_ret = full_result["metrics"]["total_return_pct"]
                        full_trades = full_result["metrics"]["total_trades"]
                        logger.info(f"    ★ 전체 데이터: {full_ret:+.2f}% ({full_trades}건)")

                        if full_ret > 0:
                            logger.info(f"    ★★ 전략 {num} 채택!")
                            created[num] = {
                                "is_return": is_ret,
                                "oos_return": oos_ret,
                                "full_return": full_ret,
                                "total_trades": full_trades,
                                "name": strategy.name,
                            }
                            accepted = True
                            break

                filepath.unlink(missing_ok=True)

            except Exception as e:
                logger.error(f"    에러: {e}")
                traceback.print_exc()

        if not accepted:
            logger.info(f"  전략 {num}: 5회 시도 후 실패")
            filepath.unlink(missing_ok=True)

    return created


def main():
    logger.info("=" * 70)
    logger.info("GPT-4o 라운드 최적화 V2 시작")
    logger.info(f"모델: {OPENAI_MODEL}, 최대 {MAX_ROUNDS}라운드/전략")
    logger.info("=" * 70)

    data = load_intraday_data()
    is_data, oos_data = split_data(data)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Phase 1: 기존 전략 최적화
    opt_results = optimize_existing_strategies(client, data, is_data, oos_data)

    # Phase 2: 새 전략 생성
    new_results = create_new_strategies(client, data, is_data, oos_data)

    # __init__.py 재생성
    generate_init_file()

    # 최종 합산
    logger.info(f"\n{'=' * 70}")
    logger.info("★★★ 최종 합산 결과 (전체 데이터) ★★★")
    logger.info(f"{'=' * 70}")

    config = IntradayBacktestConfig(initial_capital=5_000_000, max_positions=3, position_size=0.3)
    engine_v2 = IntradayBacktestEngineV2(config)
    total_return = 0

    for i in range(1, 10):
        fp = STRATEGY_DIR / f"intraday_strategy_{i}.py"
        if not fp.exists():
            continue
        strategy = load_strategy_from_file(fp)
        metrics, _ = engine_v2.run(strategy, data, show_progress=False)
        m = metrics.to_dict()
        total_return += m["total_return_pct"]
        logger.info(
            f"  전략 {i} ({strategy.name}): "
            f"승률={m['win_rate']:.1f}%, 수익률={m['total_return_pct']:+.2f}%, 거래={m['total_trades']}건"
        )

    logger.info(f"\n  ★★★ 합산 수익률: {total_return:+.2f}% ★★★")

    # 결과 저장
    result = {
        "timestamp": datetime.now().isoformat(),
        "model": OPENAI_MODEL,
        "optimization_results": {str(k): v for k, v in opt_results.items()},
        "new_strategies": {str(k): v for k, v in new_results.items()},
        "combined_return": total_return,
    }

    report_path = project_root / "reports" / "optimization_v2_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"\n결과 저장: {report_path}")
    logger.info(f"{'=' * 70}")


if __name__ == "__main__":
    main()
