#!/usr/bin/env python3
"""Round 4 최적화: +66.21% → 더 높은 수익률 + 승률 개선 목표.

6개 전략 모두 5라운드씩 GPT-4o와 대화하며 최적화.
채택 조건: 수익률 개선 AND 승률 개선 (둘 다 올라야 반영)
IS/OOS 검증 필수.
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

MAX_ROUNDS = 5
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
STRATEGY_DIR = project_root / "src" / "strategies" / "data_driven"
CONFIG = IntradayBacktestConfig(initial_capital=5_000_000, max_positions=3, position_size=0.3)

# 6개 전략 모두에 대한 제약조건
STRATEGY_CONSTRAINTS = {
    1: {
        "name": "MorningRSINeutralATR",
        "time_window": "9:30-11시 (오전)",
        "desc": "장 초반 모멘텀, ATR>=0.005, RSI 40-60, 2연속 양봉, VWAP 위",
        "hints": [
            "ATR 임계값 미세조정 (0.0045~0.006)",
            "VWAP 이격도 추가 (close > VWAP * 1.001~1.003)",
            "RSI 범위 미세 조정 (38-62 또는 42-58)",
            "거래량 조건 추가 (vol > N * avg_vol)",
            "3연속 양봉으로 강화 (승률 올라감, 거래 줄어듬 주의)",
        ],
        "forbidden": [
            "시간대를 11시 이후로 확장 금지",
            "2연속 양봉을 1연속으로 약화 금지",
        ],
    },
    2: {
        "name": "LunchRSINeutralATRVolume",
        "time_window": "11-13시 (점심)",
        "desc": "점심시간, ATR>=0.005389, RSI 40-60, vol_ratio>=1.17, 1연속 양봉",
        "hints": [
            "vol_ratio 임계값 조정 (1.10~1.30)",
            "ATR 범위 조정 (0.005~0.006)",
            "VWAP 위 조건 추가",
            "2연속 양봉으로 강화하여 승률 개선",
            "RSI 범위를 42-58로 좁히기 시도",
        ],
        "forbidden": [
            "시간대를 11시 이전으로 확장 금지",
            "거래량 필터 제거 금지",
        ],
    },
    3: {
        "name": "ModifiedRSINeutralATR",
        "time_window": "9-14시 (와이드)",
        "desc": "넓은 시간대, ATR>=0.005, RSI 40-60, VWAP*1.002 위, 2연속 양봉",
        "hints": [
            "VWAP 이격도 미세 조정 (1.001~1.005)",
            "ATR 임계값 미세 조정 (0.0048~0.006)",
            "거래량 조건 추가",
            "3연속 양봉으로 강화",
            "특정 시간대 제외 (예: 12-13시 점심 제외)",
        ],
        "forbidden": [
            "VWAP 이격도 조건 제거 금지",
            "2연속 양봉을 1연속으로 약화 금지",
            "시간대를 14시 이후로 확장 금지",
        ],
    },
    4: {
        "name": "AfternoonRSINeutralATR",
        "time_window": "13-15시 (오후)",
        "desc": "오후 시간, ATR>=0.005, RSI 40-60, 2연속 양봉, VWAP 위",
        "hints": [
            "시간을 13:30-14:30으로 좁히기 (더 집중된 윈도우)",
            "VWAP 이격도 추가 (close > VWAP * 1.001~1.003)",
            "ATR 임계값 미세 조정",
            "거래량 조건 추가",
            "RSI 범위를 42-58로 좁히기",
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
        "hints": [
            "ATR 범위 미세 조정 (상한/하한 ±0.0005)",
            "RSI 상한을 55→52 또는 55→58로 조정",
            "거래량 배수 조정 (1.2~1.5)",
            "VWAP 이격도 추가 (close > VWAP * 1.001)",
            "2연속 양봉으로 강화하여 승률 개선",
        ],
        "forbidden": [
            "시간대를 13시 이전으로 확장 금지",
            "거래량 필터 제거 금지",
            "ATR 범위 필터를 단일 임계값으로 바꾸지 말것",
        ],
    },
    8: {
        "name": "MorningWideRSINeutralATR",
        "time_window": "9:30-12시 (오전 와이드)",
        "desc": "오전 와이드, ATR>=0.005, RSI 40-60, VWAP*1.002 위, 2연속 양봉",
        "hints": [
            "VWAP 이격도 미세 조정 (1.001~1.005)",
            "ATR 임계값 미세 조정 (0.0048~0.006)",
            "시간을 9:30-11:30으로 좁히기",
            "거래량 조건 추가",
            "3연속 양봉으로 강화",
        ],
        "forbidden": [
            "VWAP 이격도 조건 제거 금지",
            "시간대를 12시 이후로 확장 금지",
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
    module_name = f"r4_{filepath.stem}_{datetime.now().strftime('%H%M%S%f')}"
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


def build_prompt(strat_num, code, is_result, oos_result, round_num, history):
    """승률+수익률 동시 개선 목표 프롬프트."""
    c = STRATEGY_CONSTRAINTS.get(strat_num, {})

    is_ret = is_result["return"]
    is_wr = is_result["win_rate"]
    is_trades = is_result["total_trades"]
    oos_ret = oos_result["return"]
    oos_wr = oos_result["win_rate"]
    oos_trades = oos_result["total_trades"]

    # 거래 상세 분석
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

    # 패배 거래의 패턴
    worst5 = sorted(trades, key=lambda t: t["pnl_pct"])[:5]
    worst_text = "\n".join(f"  - {t['code']}: {t['pnl_pct']:+.2f}% ({t.get('exit_reason', '?')})" for t in worst5)

    # 히스토리
    history_text = ""
    if history:
        history_text = "\n### 이전 라운드 결과:\n"
        for h in history[-5:]:
            status = "채택" if h["accepted"] else "거부"
            history_text += (
                f"- R{h['round']}: 수익={h['ret']:+.2f}%, 승률={h['wr']:.1f}% → {status}"
                f" ({h.get('reason', '')})\n"
            )
        history_text += "\n**이전과 다른 접근으로 시도해주세요!**\n"

    hints = "\n".join(f"  - {h}" for h in c.get("hints", []))
    forbidden = "\n".join(f"  - {f}" for f in c.get("forbidden", []))

    return f"""당신은 한국 주식 5분봉 단타 전략 최적화 전문가입니다.

## 전략 {strat_num}: {c.get('name', '')} (라운드 {round_num}/{MAX_ROUNDS})
- 시간대: {c.get('time_window', '')}
- 설명: {c.get('desc', '')}

### 현재 성과:
- **IS (44일)**: 수익률={is_ret:+.2f}%, 승률={is_wr:.1f}%, 거래={is_trades}건
- **OOS (15일)**: 수익률={oos_ret:+.2f}%, 승률={oos_wr:.1f}%, 거래={oos_trades}건

### 거래 상세 분석 (IS):
- 총 {is_trades}건: 승 {len(wins)}건 (평균 {avg_win:+.2f}%), 패 {len(losses)}건 (평균 {avg_loss:+.2f}%)
- 청산 이유별:
{exit_analysis}
- 최악 거래 TOP 5:
{worst_text}

{history_text}

### 현재 코드:
```python
{code}
```

## ★★★ 목표: 수익률 AND 승률 모두 개선! ★★★

승률을 높이려면:
1. **패배 거래 줄이기**: 진입 조건을 더 엄격하게 (추가 필터)
2. **불리한 상황 회피**: 특정 패턴 감지 시 진입 금지
3. **승리 확률 높은 조건 집중**: 위 청산 이유 분석에서 승률 낮은 유형 개선

수익률을 높이려면:
1. **더 좋은 진입 타이밍**: 조건을 더 정밀하게
2. **손실 줄이기**: 추가 exit 조건 (트레일링, RSI 과매수 청산 등)

### 개선 방향 제안:
{hints}

### ★ 금지 사항 ★
{forbidden}

### ★★★ 절대 규칙 ★★★
- **SL=3%, TP=5% 반드시 유지!**
- **RSI 중립 필터 반드시 유지! (범위는 미세 조정 가능)**
- **import: `from src.strategies.intraday.base import IntradayStrategy` 만 사용**
- 다른 import는 `import numpy as np` 만 허용
- 클래스명 변경 금지!
- 작은 변경만! 한 번에 1-2가지만 변경!
- 거래가 50건 미만이면 실패 (과적합)
- position은 객체: position.entry_price (O), position["entry_price"] (X)
- check_exit_fast에서 position.entry_bar_idx (int) 사용 가능

**개선된 전체 코드만 반환. 마크다운 코드블록 없이 순수 Python만. 설명 금지.**"""


def optimize_strategy(client, strat_num, data, is_data, oos_data):
    """하나의 전략을 5라운드 최적화."""
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

    for round_num in range(1, MAX_ROUNDS + 1):
        temp = 0.4 + (round_num - 1) * 0.15  # 0.4 → 1.0
        temp = min(temp, 1.0)
        logger.info(f"\n  라운드 {round_num}/{MAX_ROUNDS} (temp={temp:.2f})")

        prompt = build_prompt(strat_num, best_code, best_is, best_oos, round_num, history)

        try:
            raw = call_openai(client, prompt, temperature=temp)
            code = clean_code(raw)

            # 문법 확인
            try:
                compile(code, "<opt>", "exec")
            except SyntaxError as e:
                logger.warning(f"    문법 에러: {e}")
                history.append({"round": round_num, "ret": 0, "wr": 0, "accepted": False, "reason": f"문법에러"})
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
            tmp_path = STRATEGY_DIR / f"_tmp_r4_{strat_num}.py"
            tmp_path.write_text(code, encoding="utf-8")

            try:
                strategy = load_strategy_from_file(tmp_path)
            except Exception as e:
                logger.warning(f"    로드 에러: {e}")
                tmp_path.unlink(missing_ok=True)
                history.append({"round": round_num, "ret": 0, "wr": 0, "accepted": False, "reason": f"로드에러"})
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
            new_is_ret = is_result["return"]
            new_is_wr = is_result["win_rate"]
            new_oos_ret = oos_result["return"]
            new_oos_wr = oos_result["win_rate"]

            logger.info(
                f"    Full: 수익={new_ret:+.2f}%, 승률={new_wr:.1f}%, 거래={new_trades}건"
            )
            logger.info(
                f"    IS: 수익={new_is_ret:+.2f}%, 승률={new_is_wr:.1f}% | "
                f"OOS: 수익={new_oos_ret:+.2f}%, 승률={new_oos_wr:.1f}%"
            )

            # ★ 채택 기준: 수익률 + 승률 모두 개선 ★
            ret_improved = new_ret > best_full["return"]
            wr_improved = new_wr >= best_full["win_rate"]  # 승률은 최소 유지 이상
            oos_ok = new_oos_ret >= best_oos["return"] * 0.7  # OOS 30% 이상 하락 방지
            enough_trades = new_trades >= 50
            is_positive = new_is_ret > 0

            # 보너스: 승률이 2%p 이상 올랐으면 수익률 약간 줄어도 OK
            wr_bonus = new_wr >= best_full["win_rate"] + 2.0
            if wr_bonus and new_ret >= best_full["return"] * 0.95:
                ret_improved = True

            # 보너스: 수익률이 크게 올랐으면 (2%+) 승률 약간 줄어도 OK
            ret_bonus = new_ret >= best_full["return"] + 2.0
            if ret_bonus and new_wr >= best_full["win_rate"] - 1.0:
                wr_improved = True

            accepted = ret_improved and wr_improved and oos_ok and enough_trades and is_positive

            reason = ""
            if not ret_improved and not wr_bonus:
                reason = f"수익 미개선({best_full['return']:+.2f}→{new_ret:+.2f})"
            elif not wr_improved and not ret_bonus:
                reason = f"승률 하락({best_full['win_rate']:.1f}→{new_wr:.1f})"
            elif not oos_ok:
                reason = f"OOS 악화({best_oos['return']:+.2f}→{new_oos_ret:+.2f})"
            elif not enough_trades:
                reason = f"거래부족({new_trades}건)"
            elif not is_positive:
                reason = f"IS 마이너스({new_is_ret:+.2f})"

            history.append({
                "round": round_num,
                "ret": new_ret,
                "wr": new_wr,
                "accepted": accepted,
                "reason": reason if not accepted else "채택",
            })

            if accepted:
                logger.info(
                    f"    ★★ 채택! 수익: {best_full['return']:+.2f}→{new_ret:+.2f}%, "
                    f"승률: {best_full['win_rate']:.1f}→{new_wr:.1f}%"
                )
                best_code = code
                best_is = is_result
                best_oos = oos_result
                best_full = full_result
                no_improve = 0
            else:
                no_improve += 1
                logger.info(f"    거부: {reason} (미개선 {no_improve}회)")
                if no_improve >= 3:
                    logger.info(f"    3회 연속 미개선 → 조기 종료")
                    break

        except Exception as e:
            logger.error(f"    에러: {e}")
            traceback.print_exc()

    # 결과 적용
    result = {
        "strategy": strat_num,
        "name": c.get("name", ""),
        "base_return": full_base["return"],
        "base_win_rate": full_base["win_rate"],
        "base_trades": full_base["total_trades"],
        "final_return": best_full["return"],
        "final_win_rate": best_full["win_rate"],
        "final_trades": best_full["total_trades"],
        "improved": best_full["return"] > full_base["return"],
        "rounds": history,
    }

    if best_full["return"] > full_base["return"]:
        filepath.write_text(best_code, encoding="utf-8")
        logger.info(
            f"\n  ★ 전략 {strat_num} 개선 적용: "
            f"수익 {full_base['return']:+.2f}%→{best_full['return']:+.2f}%, "
            f"승률 {full_base['win_rate']:.1f}%→{best_full['win_rate']:.1f}%"
        )
    else:
        logger.info(f"\n  전략 {strat_num}: 개선 없음, 원본 유지")

    return result


def main():
    logger.info("=" * 70)
    logger.info(f"Round 4 최적화: 수익률 + 승률 동시 개선 (5라운드/전략)")
    logger.info(f"모델: {OPENAI_MODEL}, 전략 6개 x {MAX_ROUNDS}라운드")
    logger.info("=" * 70)

    data = load_intraday_data()
    is_data, oos_data = split_data(data)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # 전체 전략 베이스라인
    logger.info("\n--- 최적화 전 베이스라인 ---")
    base_total_ret = 0
    for strat_num in [1, 2, 3, 4, 6, 8]:
        fp = STRATEGY_DIR / f"intraday_strategy_{strat_num}.py"
        if fp.exists():
            strategy = load_strategy_from_file(fp)
            r = run_backtest(strategy, data)
            if r["success"]:
                base_total_ret += r["return"]
                logger.info(
                    f"  전략 {strat_num}: 수익={r['return']:+.2f}%, 승률={r['win_rate']:.1f}%, 거래={r['total_trades']}건"
                )
    logger.info(f"  합산: {base_total_ret:+.2f}%")

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
    logger.info("★★★ Round 4 최종 결과 ★★★")
    logger.info(f"{'=' * 70}")

    total_return = 0
    total_trades = 0

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

                # 개선 여부 표시
                base_r = all_results.get(strat_num, {})
                base_ret = base_r.get("base_return", r["return"])
                base_wr = base_r.get("base_win_rate", r["win_rate"])
                delta_ret = r["return"] - base_ret
                delta_wr = r["win_rate"] - base_wr

                mark = "★" if delta_ret > 0 else " "
                logger.info(
                    f"  {mark} 전략 {strat_num} ({strategy.name}): "
                    f"수익={r['return']:+.2f}% ({delta_ret:+.2f}), "
                    f"승률={r['win_rate']:.1f}% ({delta_wr:+.1f}), "
                    f"거래={r['total_trades']}건"
                )
        except Exception as e:
            logger.error(f"  전략 {strat_num}: 에러 - {e}")

    logger.info(f"\n  합산 수익률: {base_total_ret:+.2f}% → {total_return:+.2f}% ({total_return - base_total_ret:+.2f}%)")
    logger.info(f"  총 거래: {total_trades}건")

    # 결과 저장
    report = {
        "timestamp": datetime.now().isoformat(),
        "model": OPENAI_MODEL,
        "max_rounds": MAX_ROUNDS,
        "base_combined_return": round(base_total_ret, 2),
        "final_combined_return": round(total_return, 2),
        "improvement": round(total_return - base_total_ret, 2),
        "strategies": {str(k): v for k, v in all_results.items()},
    }

    report_path = project_root / "reports" / "round4_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info(f"\n결과 저장: {report_path}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
