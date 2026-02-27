#!/usr/bin/env python3
"""3차 최적화 - 전략 조합 + 진입 필터 강화로 WR 70% 도전

1차/2차: SL/TP 조정으로 최대 60.2% → 부족
3차: 전략 자체를 바꿔야 함
  - 갭 전략 단독 (WR 62%+)
  - 갭 + 경윤만 (경윤 WR 70%)
  - modified_rsi 제거 (WR 53%가 전체를 끌어내림)
  - 갭 전략 진입 필터 강화 (confidence, 시간대)
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


CONFIGS = [
    # ── 전략 조합 변경 ──
    {
        "name": "R0: 기준선 (1차 최적)",
        "desc": "SL5%/TP3.5%, 전략1제거",
        "override_sl": 0.05, "override_tp": 0.035,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R1: 갭+경윤만 (전략3 제거)",
        "desc": "modified_rsi도 제거, 갭+경윤만",
        "override_sl": 0.05, "override_tp": 0.035,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R2: 갭만 단독",
        "desc": "갭 전략만 (WR 62%+ 기대)",
        "override_sl": 0.05, "override_tp": 0.035,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
        "skip_v6": True,
    },
    {
        "name": "R3: 갭만 SL3%/TP3%",
        "desc": "갭 단독 + 타이트 SL/TP",
        "override_sl": 0.03, "override_tp": 0.03,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
        "skip_v6": True,
    },
    {
        "name": "R4: 갭만 SL4%/TP3%",
        "desc": "갭 단독 + 넓은SL 빠른TP",
        "override_sl": 0.04, "override_tp": 0.03,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
        "skip_v6": True,
    },
    {
        "name": "R5: 갭만 SL5%/TP2.5%",
        "desc": "갭 단독 + 극한 빠른TP",
        "override_sl": 0.05, "override_tp": 0.025,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
        "skip_v6": True,
    },
    {
        "name": "R6: 갭만 SL5%/TP2% 50%",
        "desc": "갭 단독 + 극극한TP + 집중배팅",
        "override_sl": 0.05, "override_tp": 0.02,
        "DD_POSITION_PCT": 0.50, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
        "skip_v6": True,
    },
    {
        "name": "R7: 갭+경윤 SL5%/TP2.5%",
        "desc": "갭+경윤 + 극한 빠른TP",
        "override_sl": 0.05, "override_tp": 0.025,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R8: 갭+경윤 SL5%/TP2%",
        "desc": "갭+경윤 + 극극한TP",
        "override_sl": 0.05, "override_tp": 0.02,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
    {
        "name": "R9: 갭+경윤 SL7%/TP2%",
        "desc": "갭+경윤 + 극넓은SL + 극극한TP",
        "override_sl": 0.07, "override_tp": 0.02,
        "DD_POSITION_PCT": 0.40, "MAX_POSITIONS": 3,
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "FORCE_CLOSE_TIME": time(15, 20),
    },
]


def run_one(cfg, intraday_data, daily_by_date, daily_context):
    """단일 설정으로 시뮬레이션 실행."""
    sim.DD_POSITION_PCT = cfg["DD_POSITION_PCT"]
    sim.MAX_POSITIONS = cfg["MAX_POSITIONS"]
    sim.FORCE_CLOSE_TIME = cfg["FORCE_CLOSE_TIME"]
    sim.SLIPPAGE = 0.001

    # v6 스킵 처리: V6_MIN_CONFIDENCE를 99로 올려서 사실상 비활성화
    orig_v6_conf = sim.V6_MIN_CONFIDENCE
    if cfg.get("skip_v6"):
        sim.V6_MIN_CONFIDENCE = 99.0

    try:
        cap, trades, daily, rem = sim.run_simulation(
            intraday_data, daily_by_date, daily_context, n_days=None,
            override_sl=cfg["override_sl"],
            override_tp=cfg["override_tp"],
            skip_strategies=cfg.get("skip_strategies"),
        )
    finally:
        sim.V6_MIN_CONFIDENCE = orig_v6_conf

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
    print("  3차 최적화 - 전략 조합 변경 + 진입 필터 강화 (WR 70% 목표)")
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
        sl_str = f"SL{cfg['override_sl']*100:.0f}%" if cfg['override_sl'] else "기본"
        tp_str = f"TP{cfg['override_tp']*100:.1f}%" if cfg['override_tp'] else "기본"
        v6_str = "v6OFF" if cfg.get("skip_v6") else ""
        print(f"  [{i+1:2d}/10] {cfg['name']:30s} {sl_str}/{tp_str} {v6_str:6s} ", end="", flush=True)

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

        for sname in sorted(result["strat_stats"].keys()):
            s = result["strat_stats"][sname]
            swr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
            print(f"        {sname:30s} {s['trades']:3d}건 WR {swr:5.1f}% {s['pnl']:>+10,.0f}원")

    # 비교 테이블
    print(f"\n{'━' * 90}")
    print(f"  3차 최적화 최종 비교")
    print(f"{'━' * 90}")
    print(f"  {'#':2s} {'설정':30s} {'수익률':>8s} {'승률':>7s} {'거래':>5s} {'MDD':>7s} {'PnL':>13s}")
    print(f"  {'─' * 85}")

    for i, r in enumerate(results):
        marker = "★★★" if r["wr"] >= 70 else ("★★" if r["wr"] >= 65 else ("★" if r["wr"] >= 60 else "  "))
        print(f"  {i:2d} {r['name']:30s} {r['return']:>+7.1f}% {r['wr']:>6.1f}% "
              f"{r['trades']:>4d}건 {r['mdd']:>6.1f}% {r['pnl']:>+12,.0f}원 {marker}")

    best_wr = max(results, key=lambda x: x["wr"])
    best_ret = max(results, key=lambda x: x["return"])
    # WR 65%+ 중 수익률 최고
    wr65 = [r for r in results if r["wr"] >= 65]
    best_bal = max(wr65, key=lambda x: x["return"]) if wr65 else best_ret

    print(f"\n  최고 승률:   {best_wr['name']} → WR {best_wr['wr']:.1f}%, {best_wr['return']:+.1f}%")
    print(f"  최고 수익:   {best_ret['name']} → {best_ret['return']:+.1f}%, WR {best_ret['wr']:.1f}%")
    if wr65:
        print(f"  최적 균형:   {best_bal['name']} → WR {best_bal['wr']:.1f}%, {best_bal['return']:+.1f}%")

    # 70% 미달 시 4차 극한 탐색
    if best_wr["wr"] < 70:
        print(f"\n  70% 미달 → 4차 극한 탐색 (갭전략 SL/TP 미세 그리드)...")
        run_phase4(best_wr["config"], intraday_data, daily_by_date, daily_context, results)
    else:
        cfg = best_wr["config"]
        print(f"\n  ★★★ 70% 달성!")
        print(f"  SL={cfg['override_sl']}, TP={cfg['override_tp']}")
        print(f"  skip={cfg.get('skip_strategies', [])}")


def run_phase4(base_cfg, intraday_data, daily_by_date, daily_context, prev_results):
    """4차: 갭전략 중심 SL/TP 미세 그리드."""
    phase4 = []
    for sl in [0.04, 0.05, 0.06, 0.07, 0.08]:
        for tp in [0.015, 0.02, 0.025]:
            cfg = dict(base_cfg)
            cfg["override_sl"] = sl
            cfg["override_tp"] = tp
            cfg["name"] = f"G: SL{sl*100:.0f}%/TP{tp*100:.1f}%"
            phase4.append(cfg)

    results4 = []
    for i, cfg in enumerate(phase4):
        print(f"  [4차 {i+1:2d}/{len(phase4)}] {cfg['name']:25s} ", end="", flush=True)
        t0 = time_module.time()
        result = run_one(cfg, intraday_data, daily_by_date, daily_context)
        elapsed = time_module.time() - t0
        result["name"] = cfg["name"]
        result["config"] = cfg
        results4.append(result)
        marker = " ★★★" if result["wr"] >= 70 else (" ★★" if result["wr"] >= 65 else "")
        print(f"→ WR {result['wr']:5.1f}% 수익 {result['return']:+7.1f}% "
              f"거래 {result['trades']:3d}건 ({elapsed:.0f}초){marker}")

    print(f"\n{'━' * 85}")
    print(f"  4차 극한 탐색 결과 (상위 10)")
    print(f"{'━' * 85}")
    sorted4 = sorted(results4, key=lambda x: -x["wr"])
    for r in sorted4[:10]:
        marker = "★★★" if r["wr"] >= 70 else ("★★" if r["wr"] >= 65 else "")
        print(f"  {r['name']:25s} {r['return']:>+7.1f}% WR {r['wr']:>5.1f}% "
              f"{r['trades']:>4d}건 MDD {r['mdd']:>5.1f}% {r['pnl']:>+11,.0f}원 {marker}")

    all_r = prev_results + results4
    best = max(all_r, key=lambda x: x["wr"])
    best_bal = max([r for r in all_r if r["wr"] >= 65], key=lambda x: x["return"]) if any(r["wr"] >= 65 for r in all_r) else best

    print(f"\n  전체 최고 승률: {best['name']} → WR {best['wr']:.1f}%, {best['return']:+.1f}%")
    if best_bal["name"] != best["name"]:
        print(f"  최적 균형:      {best_bal['name']} → WR {best_bal['wr']:.1f}%, {best_bal['return']:+.1f}%")

    cfg = best["config"]
    print(f"\n  [최종 추천 파라미터]")
    print(f"  SL = {cfg['override_sl']}")
    print(f"  TP = {cfg['override_tp']}")
    print(f"  DD_POSITION_PCT = {cfg['DD_POSITION_PCT']}")
    print(f"  MAX_POSITIONS = {cfg['MAX_POSITIONS']}")
    print(f"  skip_strategies = {cfg.get('skip_strategies', [])}")
    print(f"  skip_v6 = {cfg.get('skip_v6', False)}")


if __name__ == "__main__":
    main()
