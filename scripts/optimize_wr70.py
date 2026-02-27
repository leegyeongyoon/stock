#!/usr/bin/env python3
"""10회 반복 알고리즘 최적화 - 승률 70% + 수익률 극대화

매 반복마다 SL/TP/전략/포지션 등을 변경하고 시뮬 실행.
전략 인스턴스의 stop_loss_pct/take_profit_pct를 직접 패치.
"""

import sys
import time as time_module
from collections import defaultdict
from datetime import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

import scripts.simulate_combined_v2 as sim


# ══════════════════════════════════════════════════════
#  10가지 알고리즘 설정
# ══════════════════════════════════════════════════════

CONFIGS = [
    {
        "name": "R0: 기준선",
        "desc": "SL3%/TP5%, 전략1+3+갭+경윤",
        "override_sl": None, "override_tp": None,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": [],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R1: 전략1 제거",
        "desc": "morning_rsi 제거 (WR 41.7% 전략 삭제)",
        "override_sl": None, "override_tp": None,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R2: TP 4%",
        "desc": "전략1 제거 + TP 5%→4% (빠른 익절)",
        "override_sl": None, "override_tp": 0.04,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R3: TP 3.5%",
        "desc": "전략1 제거 + TP 3.5% (더 빠른 익절)",
        "override_sl": None, "override_tp": 0.035,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R4: SL4% + TP4%",
        "desc": "전략1 제거 + 넓은SL + 빠른TP",
        "override_sl": 0.04, "override_tp": 0.04,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R5: SL5% + TP3.5%",
        "desc": "전략1 제거 + 매우넓은SL + 빠른TP (WR극대화)",
        "override_sl": 0.05, "override_tp": 0.035,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R6: SL5% + TP3%",
        "desc": "전략1 제거 + SL5%/TP3% (극한 WR)",
        "override_sl": 0.05, "override_tp": 0.03,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R7: SL5%+TP3%+50%배팅",
        "desc": "R6 + 포지션 50% (집중 배팅)",
        "override_sl": 0.05, "override_tp": 0.03,
        "DD_POSITION_PCT": 0.50,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R8: SL5%+TP3%+2종목",
        "desc": "R6 + 최대 2종목 (최고 품질만)",
        "override_sl": 0.05, "override_tp": 0.03,
        "DD_POSITION_PCT": 0.45,
        "MAX_POSITIONS": 2,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R9: SL6%+TP3%",
        "desc": "전략1 제거 + SL6%/TP3% (극극한 WR)",
        "override_sl": 0.06, "override_tp": 0.03,
        "DD_POSITION_PCT": 0.40,
        "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
]


def run_one(cfg, intraday_data, daily_by_date, daily_context):
    """단일 설정으로 시뮬레이션 실행."""
    # 글로벌 오버라이드
    sim.DD_POSITION_PCT = cfg["DD_POSITION_PCT"]
    sim.MAX_POSITIONS = cfg["MAX_POSITIONS"]
    sim.FORCE_CLOSE_TIME = cfg["FORCE_CLOSE_TIME"]
    sim.SLIPPAGE = 0.001

    cap, trades, daily, rem = sim.run_simulation(
        intraday_data, daily_by_date, daily_context, n_days=None,
        override_sl=cfg["override_sl"],
        override_tp=cfg["override_tp"],
        skip_strategies=cfg.get("skip_strategies"),
    )

    rem_val = sum(p.entry_price * p.quantity for p in rem.values())
    equity = cap + rem_val
    ret = (equity / sim.INITIAL_CAPITAL - 1) * 100
    n_trades = len(trades)
    n_wins = sum(1 for t in trades if t.pnl > 0)
    wr = n_wins / n_trades * 100 if n_trades else 0

    peak = sim.INITIAL_CAPITAL
    mdd = 0
    for d in daily:
        peak = max(peak, d["equity"])
        dd = (d["equity"] - peak) / peak * 100
        mdd = min(mdd, dd)

    strat_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        s = strat_stats[t.strategy_name]
        s["trades"] += 1
        if t.pnl > 0:
            s["wins"] += 1
        s["pnl"] += t.pnl

    reason_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for t in trades:
        reason_stats[t.exit_reason]["count"] += 1
        reason_stats[t.exit_reason]["pnl"] += t.pnl

    return {
        "equity": equity, "return": ret, "trades": n_trades,
        "wins": n_wins, "wr": wr, "mdd": mdd,
        "pnl": equity - sim.INITIAL_CAPITAL,
        "strat_stats": dict(strat_stats),
        "reason_stats": dict(reason_stats),
    }


def main():
    print("=" * 85)
    print("  10회 반복 알고리즘 최적화 - 승률 70% + 수익률 극대화")
    print("=" * 85)

    print("\n  데이터 로딩...")
    t0 = time_module.time()
    intraday_data, daily_by_date, all_dates = sim.load_all_data()
    codes = list(intraday_data.keys())
    from src.strategies.data_driven.daily_context import DailyContextLoader
    loader = DailyContextLoader()
    daily_context = loader.load(codes, min(all_dates), max(all_dates))
    print(f"  {len(intraday_data)}종목, {len(all_dates)}일, {time_module.time() - t0:.1f}초\n")

    results = []

    for i, cfg in enumerate(CONFIGS):
        sl_str = f"SL{cfg['override_sl']*100:.0f}%" if cfg['override_sl'] else "SL기본"
        tp_str = f"TP{cfg['override_tp']*100:.1f}%" if cfg['override_tp'] else "TP기본"
        print(f"  [{i+1:2d}/10] {cfg['name']:30s} {sl_str} {tp_str} "
              f"pos={cfg['DD_POSITION_PCT']*100:.0f}% max={cfg['MAX_POSITIONS']} ", end="", flush=True)

        t0 = time_module.time()
        result = run_one(cfg, intraday_data, daily_by_date, daily_context)
        elapsed = time_module.time() - t0

        result["name"] = cfg["name"]
        result["config"] = cfg
        results.append(result)

        marker = " ★★★" if result["wr"] >= 70 else (" ★★" if result["wr"] >= 65 else (" ★" if result["wr"] >= 60 else ""))
        print(f"→ WR {result['wr']:5.1f}% 수익 {result['return']:+7.1f}% "
              f"거래 {result['trades']:3d}건 MDD {result['mdd']:5.1f}% "
              f"PnL {result['pnl']:>+11,.0f}원 ({elapsed:.0f}초){marker}")

        # 전략별 요약
        for sname in sorted(result["strat_stats"].keys()):
            s = result["strat_stats"][sname]
            swr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
            print(f"        {sname:30s} {s['trades']:3d}건 WR {swr:5.1f}% {s['pnl']:>+10,.0f}원")

    # ══════════════════════════════════════════════════════
    #  최종 비교
    # ══════════════════════════════════════════════════════
    print(f"\n{'━' * 85}")
    print(f"  최종 비교 테이블")
    print(f"{'━' * 85}")
    print(f"  {'#':2s} {'설정':28s} {'수익률':>8s} {'승률':>7s} {'거래':>5s} {'MDD':>7s} {'PnL':>13s}")
    print(f"  {'─' * 80}")

    for i, r in enumerate(results):
        marker = "★★★" if r["wr"] >= 70 else ("★★" if r["wr"] >= 65 else ("★" if r["wr"] >= 60 else "  "))
        print(f"  {i:2d} {r['name']:28s} {r['return']:>+7.1f}% {r['wr']:>6.1f}% "
              f"{r['trades']:>4d}건 {r['mdd']:>6.1f}% {r['pnl']:>+12,.0f}원 {marker}")

    best_wr = max(results, key=lambda x: x["wr"])
    best_ret = max(results, key=lambda x: x["return"])
    # WR 60%+ 중 수익률 최고
    wr60 = [r for r in results if r["wr"] >= 60]
    best_bal = max(wr60, key=lambda x: x["return"]) if wr60 else best_ret

    print(f"\n  최고 승률:   {best_wr['name']} → WR {best_wr['wr']:.1f}%, {best_wr['return']:+.1f}%")
    print(f"  최고 수익:   {best_ret['name']} → {best_ret['return']:+.1f}%, WR {best_ret['wr']:.1f}%")
    if wr60:
        print(f"  최적 균형:   {best_bal['name']} → WR {best_bal['wr']:.1f}%, {best_bal['return']:+.1f}%")

    # 70% 미달 시 2차 탐색
    if best_wr["wr"] < 70:
        print(f"\n  70% 미달 → 2차 미세 조정 ({best_wr['name']} 기반)...")
        run_phase2(best_wr["config"], intraday_data, daily_by_date, daily_context, results)
    else:
        print(f"\n  ★★★ 70% 달성! {best_wr['name']}")
        cfg = best_wr["config"]
        print(f"\n  [적용 파라미터]")
        print(f"  SL = {cfg['override_sl']}")
        print(f"  TP = {cfg['override_tp']}")
        print(f"  skip = {cfg.get('skip_strategies', [])}")


def run_phase2(base_cfg, intraday_data, daily_by_date, daily_context, phase1_results):
    """2차 미세 최적화: 1차 최고 승률 기반으로 SL/TP 미세 조정."""
    base_sl = base_cfg.get("override_sl") or 0.03
    base_tp = base_cfg.get("override_tp") or 0.05

    phase2 = []
    # SL 확대 시리즈
    for sl in [base_sl + 0.01, base_sl + 0.02, base_sl + 0.03]:
        for tp in [base_tp, base_tp - 0.005, base_tp - 0.01]:
            if tp < 0.02:
                continue
            cfg = dict(base_cfg)
            cfg["override_sl"] = sl
            cfg["override_tp"] = tp
            cfg["name"] = f"P2: SL{sl*100:.0f}%/TP{tp*100:.1f}%"
            cfg["desc"] = ""
            phase2.append(cfg)

    results2 = []
    for i, cfg in enumerate(phase2):
        print(f"  [2차 {i+1:2d}/{len(phase2)}] {cfg['name']:25s} ", end="", flush=True)
        t0 = time_module.time()
        result = run_one(cfg, intraday_data, daily_by_date, daily_context)
        elapsed = time_module.time() - t0
        result["name"] = cfg["name"]
        result["config"] = cfg
        results2.append(result)
        marker = " ★★★" if result["wr"] >= 70 else (" ★★" if result["wr"] >= 65 else "")
        print(f"→ WR {result['wr']:5.1f}% 수익 {result['return']:+7.1f}% "
              f"거래 {result['trades']:3d}건 ({elapsed:.0f}초){marker}")

    print(f"\n{'━' * 85}")
    print(f"  2차 결과")
    print(f"{'━' * 85}")
    print(f"  {'설정':25s} {'수익률':>8s} {'승률':>7s} {'거래':>5s} {'MDD':>7s} {'PnL':>13s}")
    print(f"  {'─' * 70}")
    for r in sorted(results2, key=lambda x: -x["wr"]):
        marker = "★★★" if r["wr"] >= 70 else ("★★" if r["wr"] >= 65 else "")
        print(f"  {r['name']:25s} {r['return']:>+7.1f}% {r['wr']:>6.1f}% "
              f"{r['trades']:>4d}건 {r['mdd']:>6.1f}% {r['pnl']:>+12,.0f}원 {marker}")

    all_r = phase1_results + results2
    best = max(all_r, key=lambda x: x["wr"])
    print(f"\n  전체 최고: {best['name']} → WR {best['wr']:.1f}%, 수익률 {best['return']:+.1f}%")
    cfg = best["config"]
    print(f"\n  [추천 파라미터]")
    print(f"  override_sl = {cfg.get('override_sl')}")
    print(f"  override_tp = {cfg.get('override_tp')}")
    print(f"  DD_POSITION_PCT = {cfg['DD_POSITION_PCT']}")
    print(f"  MAX_POSITIONS = {cfg['MAX_POSITIONS']}")
    print(f"  skip_strategies = {cfg.get('skip_strategies', [])}")


if __name__ == "__main__":
    main()
