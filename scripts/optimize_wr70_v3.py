#!/usr/bin/env python3
"""진입 품질 강화 15회 최적화 - TP 5% 유지하면서 WR 70% 도전

SL/TP만 조정하면 승률↑ 수익률↓ 트레이드오프.
해법: TP 5% 유지 + 진입 필터 강화 → 나쁜 진입을 걸러서 승률+수익 동시 상승.

조정 변수:
  - gap_min/gap_max: 갭 범위 (현재 -5%~-0.3%)
  - vol_ratio_min: 거래량 배수 (현재 1x)
  - exit_time: 시간청산 (현재 11:30)
  - max_entry_bar: 진입 허용 봉 (현재 bar 1~2)
  - SL/TP: 최종 미세 조정
  - 전략 조합 (갭+경윤 vs 갭단독)
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
    # ── R0: 기준선 ──
    {
        "name": "R00: 기준선 (갭+경윤 TP5%)",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {},
    },
    # ── 갭 범위 조정 ──
    {
        "name": "R01: 갭 -3%~-0.5%",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"gap_min": -0.03, "gap_max": -0.005},
    },
    {
        "name": "R02: 갭 -3%~-1%",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"gap_min": -0.03, "gap_max": -0.01},
    },
    {
        "name": "R03: 갭 -2.5%~-0.5%",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"gap_min": -0.025, "gap_max": -0.005},
    },
    # ── 거래량 필터 강화 ──
    {
        "name": "R04: 거래량 1.5x+",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"vol_ratio_min": 1.5},
    },
    {
        "name": "R05: 거래량 2x+",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"vol_ratio_min": 2.0},
    },
    # ── 시간 청산 조정 ──
    {
        "name": "R06: 10:30 청산",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"exit_time": time(10, 30)},
    },
    {
        "name": "R07: 11:00 청산",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"exit_time": time(11, 0)},
    },
    # ── 복합 조합 ──
    {
        "name": "R08: 갭-3~-0.5 + 볼1.5x",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"gap_min": -0.03, "gap_max": -0.005, "vol_ratio_min": 1.5},
    },
    {
        "name": "R09: 갭-3~-1 + 볼1.5x",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {"gap_min": -0.03, "gap_max": -0.01, "vol_ratio_min": 1.5},
    },
    {
        "name": "R10: 갭-3~-0.5+볼1.5+11시",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {
            "gap_min": -0.03, "gap_max": -0.005,
            "vol_ratio_min": 1.5, "exit_time": time(11, 0),
        },
    },
    {
        "name": "R11: 갭-3~-1+볼2x+11시",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {
            "gap_min": -0.03, "gap_max": -0.01,
            "vol_ratio_min": 2.0, "exit_time": time(11, 0),
        },
    },
    {
        "name": "R12: 갭-2.5~-0.5+볼1.5+11시",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "gap_params": {
            "gap_min": -0.025, "gap_max": -0.005,
            "vol_ratio_min": 1.5, "exit_time": time(11, 0),
        },
    },
    # ── SL 미세 조정 (최적 진입 기반) ──
    {
        "name": "R13: R10+SL2.5%",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "override_sl": 0.025,
        "gap_params": {
            "gap_min": -0.03, "gap_max": -0.005,
            "vol_ratio_min": 1.5, "exit_time": time(11, 0),
        },
    },
    {
        "name": "R14: R10+SL4%",
        "skip_strategies": ["morning_rsi_neutral_atr", "modified_rsi_neutral_atr"],
        "override_sl": 0.04,
        "gap_params": {
            "gap_min": -0.03, "gap_max": -0.005,
            "vol_ratio_min": 1.5, "exit_time": time(11, 0),
        },
    },
]


def run_one(cfg, intraday_data, daily_by_date, daily_context):
    """단일 설정 시뮬레이션."""
    sim.DD_POSITION_PCT = cfg.get("DD_POSITION_PCT", 0.40)
    sim.MAX_POSITIONS = cfg.get("MAX_POSITIONS", 3)
    sim.FORCE_CLOSE_TIME = cfg.get("FORCE_CLOSE_TIME", time(15, 20))
    sim.SLIPPAGE = 0.001

    # v6 비활성화
    orig_v6_conf = sim.V6_MIN_CONFIDENCE
    if cfg.get("skip_v6"):
        sim.V6_MIN_CONFIDENCE = 99.0

    try:
        cap, trades, daily, rem = sim.run_simulation(
            intraday_data, daily_by_date, daily_context, n_days=None,
            override_sl=cfg.get("override_sl"),
            override_tp=cfg.get("override_tp"),
            skip_strategies=cfg.get("skip_strategies"),
            gap_params=cfg.get("gap_params"),
        )
    finally:
        sim.V6_MIN_CONFIDENCE = orig_v6_conf

    rem_val = sum(p.entry_price * p.quantity for p in rem.values())
    equity = cap + rem_val
    ret = (equity / sim.INITIAL_CAPITAL - 1) * 100
    n = len(trades)
    w = sum(1 for t in trades if t.pnl > 0)
    wr = w / n * 100 if n else 0

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
        "equity": equity, "return": ret, "trades": n,
        "wins": w, "wr": wr, "mdd": mdd,
        "pnl": equity - sim.INITIAL_CAPITAL,
        "strat_stats": dict(strat_stats),
        "reason_stats": dict(reason_stats),
    }


def main():
    print("=" * 90)
    print("  진입 품질 강화 15회 최적화 (TP 5% 유지 + 필터 강화)")
    print("  목표: 승률 70%+ AND 수익률 60%+")
    print("=" * 90)

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
        gp = cfg.get("gap_params", {})
        gap_str = f"갭{gp.get('gap_min',-.05)*100:.0f}~{gp.get('gap_max',-.003)*100:.1f}%" if gp.get("gap_min") or gp.get("gap_max") else "갭기본"
        vol_str = f"볼{gp.get('vol_ratio_min',1.0):.1f}x" if gp.get("vol_ratio_min") else ""
        exit_str = f"~{gp['exit_time'].strftime('%H:%M')}" if gp.get("exit_time") else ""
        sl_str = f"SL{cfg['override_sl']*100:.1f}%" if cfg.get("override_sl") else ""

        print(f"  [{i+1:2d}/15] {cfg['name']:32s} ", end="", flush=True)

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

    # ══════════════════════════════════════════════════════
    #  최종 비교
    # ══════════════════════════════════════════════════════
    print(f"\n{'━' * 95}")
    print(f"  15회 최적화 최종 비교")
    print(f"{'━' * 95}")
    print(f"  {'#':3s} {'설정':32s} {'수익률':>8s} {'승률':>7s} {'거래':>5s} {'MDD':>7s} {'PnL':>13s}")
    print(f"  {'─' * 90}")

    for i, r in enumerate(results):
        marker = "★★★" if r["wr"] >= 70 else ("★★" if r["wr"] >= 65 else ("★" if r["wr"] >= 60 else "  "))
        print(f"  {i:3d} {r['name']:32s} {r['return']:>+7.1f}% {r['wr']:>6.1f}% "
              f"{r['trades']:>4d}건 {r['mdd']:>6.1f}% {r['pnl']:>+12,.0f}원 {marker}")

    best_wr = max(results, key=lambda x: x["wr"])
    best_ret = max(results, key=lambda x: x["return"])
    # WR 65%+ 중 수익률 최고 = 최적 균형
    wr65 = [r for r in results if r["wr"] >= 65]
    best_bal = max(wr65, key=lambda x: x["return"]) if wr65 else best_ret
    # WR 70%+ 중 수익률 최고
    wr70 = [r for r in results if r["wr"] >= 70]
    best_70 = max(wr70, key=lambda x: x["return"]) if wr70 else None

    print(f"\n  최고 승률:    {best_wr['name']} → WR {best_wr['wr']:.1f}%, {best_wr['return']:+.1f}%")
    print(f"  최고 수익:    {best_ret['name']} → {best_ret['return']:+.1f}%, WR {best_ret['wr']:.1f}%")
    if wr65:
        print(f"  최적 균형:    {best_bal['name']} → WR {best_bal['wr']:.1f}%, {best_bal['return']:+.1f}%")
    if best_70:
        print(f"  ★ 70%+ 최적: {best_70['name']} → WR {best_70['wr']:.1f}%, {best_70['return']:+.1f}%")

    # 2차 미세 조정 (상위 3개 기반)
    top3 = sorted(results, key=lambda x: (-x["wr"], -x["return"]))[:3]
    print(f"\n  상위 3개 기반 2차 미세 조정...")
    run_fine_tune(top3, intraday_data, daily_by_date, daily_context, results)


def run_fine_tune(top3, intraday_data, daily_by_date, daily_context, prev_results):
    """상위 3개 설정 기반 미세 조정."""
    fine_configs = []

    for base in top3:
        base_cfg = base["config"]
        base_gp = base_cfg.get("gap_params", {})

        # SL 변형
        for sl in [0.02, 0.025, 0.03, 0.035, 0.04]:
            cfg = dict(base_cfg)
            cfg["override_sl"] = sl
            cfg["gap_params"] = dict(base_gp)
            cfg["name"] = f"FT: {base['name'][:15]}+SL{sl*100:.0f}%"
            fine_configs.append(cfg)

        # 포지션 사이즈 변형
        for pct in [0.35, 0.50]:
            cfg = dict(base_cfg)
            cfg["DD_POSITION_PCT"] = pct
            cfg["gap_params"] = dict(base_gp)
            cfg["name"] = f"FT: {base['name'][:15]}+{pct*100:.0f}%배팅"
            fine_configs.append(cfg)

    fine_results = []
    for i, cfg in enumerate(fine_configs):
        print(f"  [FT {i+1:2d}/{len(fine_configs)}] {cfg['name']:35s} ", end="", flush=True)
        t0 = time_module.time()
        result = run_one(cfg, intraday_data, daily_by_date, daily_context)
        elapsed = time_module.time() - t0
        result["name"] = cfg["name"]
        result["config"] = cfg
        fine_results.append(result)
        marker = " ★★★" if result["wr"] >= 70 else (" ★★" if result["wr"] >= 65 else "")
        print(f"→ WR {result['wr']:5.1f}% 수익 {result['return']:+7.1f}% "
              f"거래 {result['trades']:3d}건 ({elapsed:.0f}초){marker}")

    # 최종 결과
    all_r = prev_results + fine_results
    print(f"\n{'━' * 95}")
    print(f"  전체 최종 결과 (상위 15)")
    print(f"{'━' * 95}")
    print(f"  {'설정':35s} {'수익률':>8s} {'승률':>7s} {'거래':>5s} {'MDD':>7s} {'PnL':>13s}")
    print(f"  {'─' * 80}")

    sorted_all = sorted(all_r, key=lambda x: (-x["wr"], -x["return"]))
    for r in sorted_all[:15]:
        marker = "★★★" if r["wr"] >= 70 else ("★★" if r["wr"] >= 65 else "")
        print(f"  {r['name']:35s} {r['return']:>+7.1f}% {r['wr']:>6.1f}% "
              f"{r['trades']:>4d}건 {r['mdd']:>6.1f}% {r['pnl']:>+12,.0f}원 {marker}")

    best = sorted_all[0]
    # WR 65%+ 중 수익률 최고
    wr65 = [r for r in sorted_all if r["wr"] >= 65]
    best_bal = max(wr65, key=lambda x: x["return"]) if wr65 else best

    print(f"\n  ★ 전체 최고 승률: {best['name']} → WR {best['wr']:.1f}%, {best['return']:+.1f}%")
    if best_bal["name"] != best["name"]:
        print(f"  ★ WR65%+ 최고수익: {best_bal['name']} → WR {best_bal['wr']:.1f}%, {best_bal['return']:+.1f}%")

    cfg = best["config"]
    gp = cfg.get("gap_params", {})
    print(f"\n  [최종 추천 파라미터]")
    print(f"  SL = {cfg.get('override_sl', '기본(전략값)')}")
    print(f"  TP = {cfg.get('override_tp', '기본(5%)')}")
    print(f"  갭 범위 = {gp.get('gap_min', -0.05)} ~ {gp.get('gap_max', -0.003)}")
    print(f"  거래량 = {gp.get('vol_ratio_min', 1.0)}x+")
    print(f"  시간청산 = {gp.get('exit_time', '11:30')}")
    print(f"  포지션 = {cfg.get('DD_POSITION_PCT', 0.40)*100:.0f}%")
    print(f"  전략 = 갭+경윤 (전략1,3 제거)")


if __name__ == "__main__":
    main()
