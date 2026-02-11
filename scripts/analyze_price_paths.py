#!/usr/bin/env python3
"""진입 후 가격 경로(MAE/MFE) 분석 + 최적 손절/익절 역산.

2-pass 접근:
  Pass 1: 피처 분포(백분위) 계산
  Pass 2: 의미있는 조합별 가격 경로 추적 + SL/TP 그리드 서치

Output: reports/price_path_analysis.json
"""

import json
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.database.connection import get_backtest_engine as get_engine
from src.utils.logger import get_logger

logger = get_logger(__name__)

FORWARD_BARS = 24
MIN_HISTORY = 20
SL_GRID = [0.002, 0.003, 0.005, 0.007, 0.01, 0.012, 0.015, 0.02, 0.025, 0.03]
TP_GRID = [0.003, 0.005, 0.007, 0.01, 0.012, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]


def load_data():
    engine = get_engine()
    logger.info("분봉 데이터 로드...")
    with engine.connect() as conn:
        df = pd.read_sql(text(
            "SELECT code, datetime, open, high, low, close, volume "
            "FROM ohlcv_intraday ORDER BY code, datetime"
        ), conn)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    logger.info(f"완료: {len(df):,}건, {df['code'].nunique()}종목")
    return df


def compute_features(opens, highs, lows, closes, volumes, hours, minutes, n):
    """핵심 피처 벡터화 계산."""
    feats = {}
    hl = highs - lows

    d0 = opens[0]
    feats["pos_vs_day_open"] = (closes - d0) / d0 if d0 > 0 else np.zeros(n)

    mfo = (hours - 9) * 60 + minutes
    feats["minutes_from_open"] = mfo.astype(float)
    feats["hours"] = hours.astype(float)

    # avg_bar_range_10
    avg_br = np.full(n, np.nan)
    if n >= 10:
        cs = np.cumsum(hl)
        pcs = np.concatenate([[0], cs])
        ws = pcs[10:] - pcs[:n - 9]
        safe_c = np.where(closes[9:] > 0, closes[9:], 1.0)
        avg_br[9:] = ws / 10 / safe_c
    feats["avg_bar_range_10"] = avg_br

    # atr_10
    atr = np.full(n, np.nan)
    tr = np.zeros(n)
    tr[0] = hl[0]
    if n > 1:
        tr[1:] = np.maximum(hl[1:], np.maximum(
            np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])
        ))
    if n >= 10:
        tr_cs = np.cumsum(tr)
        ptr = np.concatenate([[0], tr_cs])
        wtr = ptr[10:] - ptr[:n - 9]
        safe_c = np.where(closes[9:] > 0, closes[9:], 1.0)
        atr[9:] = wtr / 10 / safe_c
    feats["atr_10"] = atr

    # vol_ratio_avg20
    vr = np.full(n, np.nan)
    if n >= 20:
        vcs = np.cumsum(volumes)
        pvcs = np.concatenate([[0], vcs])
        wv = pvcs[20:] - pvcs[:n - 19]
        avg_v = wv / 20
        safe_v = np.where(avg_v > 0, avg_v, 1.0)
        vr[19:] = volumes[19:] / safe_v
    feats["vol_ratio_avg20"] = vr

    # body_ratio
    safe_hl = np.where(hl > 0, hl, 1.0)
    feats["body_ratio"] = np.where(hl > 0, np.abs(closes - opens) / safe_hl, 0.0)

    # is_bullish
    feats["is_bullish"] = (closes > opens).astype(float)

    # vwap
    tp = (highs + lows + closes) / 3
    cv = np.cumsum(volumes)
    ctv = np.cumsum(tp * volumes)
    vwap = np.where(cv > 0, ctv / cv, closes)
    feats["above_vwap"] = (closes > vwap).astype(float)
    feats["vwap_deviation"] = np.where(vwap > 0, (closes - vwap) / vwap, 0.0)

    # rsi_14
    rsi = np.full(n, np.nan)
    if n > 14:
        deltas = np.diff(closes)
        gains = np.maximum(deltas, 0)
        losses_arr = np.maximum(-deltas, 0)
        gcs = np.cumsum(gains)
        lcs = np.cumsum(losses_arr)
        pg = np.concatenate([[0], gcs])
        pl = np.concatenate([[0], lcs])
        ag = (pg[14:n] - pg[:n - 14]) / 14
        al = (pl[14:n] - pl[:n - 14]) / 14
        safe_al = np.where(al > 0, al, 1e-10)
        rs = ag / safe_al
        rsi[14:n] = np.where(al > 0, 100 - 100 / (1 + rs), 100.0)
    feats["rsi_14"] = rsi

    return feats


def extract_group_arrays(group):
    n = len(group)
    return (
        group["open"].values, group["high"].values, group["low"].values,
        group["close"].values, group["volume"].values,
        group["datetime"].dt.hour.values, group["datetime"].dt.minute.values, n,
    )


def grid_search(running_mins, running_maxs, last_returns, n_bars_arr):
    """벡터화 SL/TP 그리드 서치."""
    n = len(running_mins)
    if n < 30:
        return []

    max_nb = int(n_bars_arr.max())
    rm = np.zeros((n, max_nb))
    rx = np.zeros((n, max_nb))
    for i in range(n):
        nb = n_bars_arr[i]
        rm[i, :nb] = running_mins[i]
        rx[i, :nb] = running_maxs[i]

    results = []
    for sl in SL_GRID:
        for tp in TP_GRID:
            sl_hit = rm <= -sl
            tp_hit = rx >= tp
            sl_any = sl_hit.any(axis=1)
            tp_any = tp_hit.any(axis=1)
            sl_first = np.where(sl_any, np.argmax(sl_hit, axis=1), max_nb + 1)
            tp_first = np.where(tp_any, np.argmax(tp_hit, axis=1), max_nb + 1)

            outcomes = np.copy(last_returns)
            outcomes[tp_first < sl_first] = tp
            outcomes[sl_first < tp_first] = -sl

            wins = (outcomes > 0).sum()
            losses_count = (outcomes <= 0).sum()
            wr = wins / n
            aw = float(np.mean(outcomes[outcomes > 0])) if wins > 0 else 0
            al_val = float(np.mean(outcomes[outcomes <= 0])) if losses_count > 0 else 0
            ev = wr * aw + (1 - wr) * al_val
            pf = abs(aw * wins / (al_val * losses_count)) if al_val != 0 and losses_count > 0 else 0

            results.append({
                "stop_loss": sl, "take_profit": tp,
                "win_rate": round(wr, 4),
                "avg_return_pct": round(float(np.mean(outcomes)) * 100, 4),
                "avg_win_pct": round(aw * 100, 4),
                "avg_loss_pct": round(al_val * 100, 4),
                "expected_value_pct": round(ev * 100, 4),
                "profit_factor": round(pf, 3),
                "n_trades": n,
            })
    results.sort(key=lambda x: x["expected_value_pct"], reverse=True)
    return results


def compute_path_stats(rms_list, rxs_list, nbs_list, n_paths):
    """경로 통계 (MAE/MFE 분포)."""
    stats = {"avg_mae": [], "avg_mfe": [], "mae": {}, "mfe": {}}
    for k in ["p10", "p25", "p50", "p75", "p90"]:
        stats["mae"][k] = []
        stats["mfe"][k] = []

    for offset in range(FORWARD_BARS):
        rm_vals, rx_vals = [], []
        for i in range(n_paths):
            if nbs_list[i] > offset:
                rm_vals.append(rms_list[i][offset])
                rx_vals.append(rxs_list[i][offset])
        if len(rm_vals) < 10:
            break
        arr_rm = np.array(rm_vals)
        arr_rx = np.array(rx_vals)
        stats["avg_mae"].append(round(float(np.mean(arr_rm)) * 100, 4))
        stats["avg_mfe"].append(round(float(np.mean(arr_rx)) * 100, 4))
        for pct, key in [(10, "p10"), (25, "p25"), (50, "p50"), (75, "p75"), (90, "p90")]:
            stats["mae"][key].append(round(float(np.percentile(arr_rm, pct)) * 100, 4))
            stats["mfe"][key].append(round(float(np.percentile(arr_rx, 100 - pct)) * 100, 4))
    return stats


def main():
    logger.info("=" * 70)
    logger.info("가격 경로(MAE/MFE) 분석 시작 - 2-pass")
    logger.info("=" * 70)

    df = load_data()
    grouped = df.groupby(["code", "date"])
    total_groups = len(grouped)

    # ========== Pass 1: 피처 백분위 계산 ==========
    logger.info(f"\n[Pass 1] 피처 분포 계산 ({total_groups:,}개 그룹)...")
    sampled = {"atr_10": [], "vol_ratio_avg20": [], "avg_bar_range_10": [], "body_ratio": []}
    rng = np.random.RandomState(42)

    for idx, ((code, date), group) in enumerate(grouped):
        if idx % 10000 == 0 and idx > 0:
            logger.info(f"  Pass 1: {idx:,}/{total_groups:,}")
        group = group.sort_values("datetime").reset_index(drop=True)
        n = len(group)
        if n < MIN_HISTORY:
            continue
        opens, highs, lows, closes, volumes, hours, mins, n = extract_group_arrays(group)
        feats = compute_features(opens, highs, lows, closes, volumes, hours, mins, n)
        for key in sampled:
            vals = feats[key]
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                # 25% 샘플링 (속도)
                sample = valid[rng.random(len(valid)) < 0.25]
                sampled[key].extend(sample.tolist())

    percentiles = {}
    for key, vals in sampled.items():
        arr = np.array(vals)
        percentiles[key] = {
            "p50": round(float(np.percentile(arr, 50)), 6),
            "p75": round(float(np.percentile(arr, 75)), 6),
            "p80": round(float(np.percentile(arr, 80)), 6),
            "p90": round(float(np.percentile(arr, 90)), 6),
        }
        logger.info(f"  {key}: p50={percentiles[key]['p50']:.5f}, p75={percentiles[key]['p75']:.5f}, p80={percentiles[key]['p80']:.5f}")

    # ========== 조합 정의 ==========
    COMBOS = [
        {
            "name": "morning_10_11_high_atr",
            "desc": "10-11시 + ATR 상위 25%",
            "conditions": {"hours": ("range", 10, 11), "atr_10": (">=", percentiles["atr_10"]["p75"])},
        },
        {
            "name": "morning_09_10_high_atr",
            "desc": "9-10시 + ATR 상위 25%",
            "conditions": {"hours": ("range", 9, 10), "atr_10": (">=", percentiles["atr_10"]["p75"])},
        },
        {
            "name": "afternoon_high_atr",
            "desc": "13-15시 + ATR 상위 25%",
            "conditions": {"hours": ("range", 13, 16), "atr_10": (">=", percentiles["atr_10"]["p75"])},
        },
        {
            "name": "vol_surge_high_atr",
            "desc": "거래량 상위 25% + ATR 상위 25%",
            "conditions": {
                "vol_ratio_avg20": (">=", percentiles["vol_ratio_avg20"]["p75"]),
                "atr_10": (">=", percentiles["atr_10"]["p75"]),
            },
        },
        {
            "name": "morning_vol_atr_triple",
            "desc": "10-11시 + 거래량 상위 25% + ATR 상위 25%",
            "conditions": {
                "hours": ("range", 10, 11),
                "vol_ratio_avg20": (">=", percentiles["vol_ratio_avg20"]["p75"]),
                "atr_10": (">=", percentiles["atr_10"]["p75"]),
            },
        },
        {
            "name": "strong_bullish_candle",
            "desc": "양봉 + 몸통 상위 25% + 거래량 상위 25%",
            "conditions": {
                "is_bullish": (">=", 1.0),
                "body_ratio": (">=", percentiles["body_ratio"]["p75"]),
                "vol_ratio_avg20": (">=", percentiles["vol_ratio_avg20"]["p75"]),
            },
        },
        {
            "name": "above_vwap_high_atr",
            "desc": "VWAP 위 + ATR 상위 25%",
            "conditions": {
                "above_vwap": (">=", 1.0),
                "atr_10": (">=", percentiles["atr_10"]["p75"]),
            },
        },
        {
            "name": "below_vwap_high_atr",
            "desc": "VWAP 아래 + ATR 상위 25% (역추세)",
            "conditions": {
                "above_vwap": ("<=", 0.0),
                "atr_10": (">=", percentiles["atr_10"]["p75"]),
            },
        },
        {
            "name": "atr_top10_any_time",
            "desc": "ATR 상위 10% (시간 무관)",
            "conditions": {"atr_10": (">=", percentiles["atr_10"]["p90"])},
        },
        {
            "name": "morning_rsi_neutral_atr",
            "desc": "9-11시 + RSI 40-60 + ATR 상위 25%",
            "conditions": {
                "hours": ("range", 9, 11),
                "rsi_14": ("range_val", 40, 60),
                "atr_10": (">=", percentiles["atr_10"]["p75"]),
            },
        },
    ]

    logger.info(f"\n정의된 조합: {len(COMBOS)}개")
    for c in COMBOS:
        logger.info(f"  {c['name']}: {c['desc']}")

    # ========== Pass 2: 경로 추적 ==========
    logger.info(f"\n[Pass 2] 가격 경로 추적 ({total_groups:,}개 그룹)...")

    combo_rms = [[] for _ in COMBOS]
    combo_rxs = [[] for _ in COMBOS]
    combo_lrs = [[] for _ in COMBOS]
    combo_nbs = [[] for _ in COMBOS]
    combo_hours_list = [[] for _ in COMBOS]
    bl_rms, bl_rxs, bl_lrs, bl_nbs = [], [], [], []

    for idx, ((code, date), group) in enumerate(grouped):
        if idx % 10000 == 0 and idx > 0:
            logger.info(f"  Pass 2: {idx:,}/{total_groups:,}")
        group = group.sort_values("datetime").reset_index(drop=True)
        n = len(group)
        if n < MIN_HISTORY + 6:
            continue

        opens, highs, lows, closes, volumes, hours_arr, mins_arr, n = extract_group_arrays(group)
        feats = compute_features(opens, highs, lows, closes, volumes, hours_arr, mins_arr, n)

        for c_idx, combo in enumerate(COMBOS):
            mask = np.ones(n, dtype=bool)
            mask[:MIN_HISTORY] = False
            mask[n - 6:] = False

            for feat_key, cond in combo["conditions"].items():
                vals = feats.get(feat_key)
                if vals is None:
                    mask[:] = False
                    break
                if cond[0] == ">=":
                    mask &= ~np.isnan(vals) & (vals >= cond[1])
                elif cond[0] == "<=":
                    mask &= ~np.isnan(vals) & (vals <= cond[1])
                elif cond[0] == "range":
                    mask &= (vals >= cond[1]) & (vals < cond[2])
                elif cond[0] == "range_val":
                    mask &= ~np.isnan(vals) & (vals >= cond[1]) & (vals <= cond[2])

            for bi in np.where(mask)[0]:
                entry = closes[bi]
                if entry <= 0:
                    continue
                end = min(bi + FORWARD_BARS + 1, n)
                fh = highs[bi + 1:end]
                fl = lows[bi + 1:end]
                fc = closes[bi + 1:end]
                nb = len(fh)
                if nb < 1:
                    continue
                combo_rms[c_idx].append(np.minimum.accumulate((fl - entry) / entry))
                combo_rxs[c_idx].append(np.maximum.accumulate((fh - entry) / entry))
                combo_lrs[c_idx].append((fc[-1] - entry) / entry)
                combo_nbs[c_idx].append(nb)
                combo_hours_list[c_idx].append(hours_arr[bi])

        # 베이스라인 (5% 랜덤)
        if rng.random() < 0.05:
            bi = rng.randint(MIN_HISTORY, max(MIN_HISTORY + 1, n - 6))
            entry = closes[bi]
            if entry > 0:
                end = min(bi + FORWARD_BARS + 1, n)
                fh, fl, fc = highs[bi+1:end], lows[bi+1:end], closes[bi+1:end]
                nb = len(fh)
                if nb >= 1:
                    bl_rms.append(np.minimum.accumulate((fl - entry) / entry))
                    bl_rxs.append(np.maximum.accumulate((fh - entry) / entry))
                    bl_lrs.append((fc[-1] - entry) / entry)
                    bl_nbs.append(nb)

    # ========== 분석 ==========
    logger.info("\n[분석] 결과 계산 중...")
    results = {
        "timestamp": datetime.now().isoformat(),
        "percentiles": percentiles,
        "combinations": [],
        "baseline": None,
    }

    for c_idx, combo in enumerate(COMBOS):
        n_paths = len(combo_rms[c_idx])
        logger.info(f"\n  {combo['name']}: {n_paths:,}건 신호")

        if n_paths < 50:
            logger.info(f"    건너뜀 (신호 부족)")
            results["combinations"].append({
                "name": combo["name"], "desc": combo["desc"],
                "total_signals": n_paths, "skipped": True,
            })
            continue

        path_stats = compute_path_stats(
            combo_rms[c_idx], combo_rxs[c_idx], combo_nbs[c_idx], n_paths
        )

        # 시간대 분포
        hrs = np.array(combo_hours_list[c_idx])
        time_dist = {}
        for label, h1, h2 in [("09-10", 9, 10), ("10-11", 10, 11),
                               ("11-13", 11, 13), ("13-15", 13, 16)]:
            time_dist[label] = int(((hrs >= h1) & (hrs < h2)).sum())

        # 그리드 서치
        nbs_arr = np.array(combo_nbs[c_idx])
        valid = nbs_arr >= 6
        if valid.sum() >= 30:
            v_rms = [combo_rms[c_idx][i] for i in range(n_paths) if valid[i]]
            v_rxs = [combo_rxs[c_idx][i] for i in range(n_paths) if valid[i]]
            v_lrs = np.array([combo_lrs[c_idx][i] for i in range(n_paths) if valid[i]])
            v_nbs = nbs_arr[valid]
            grid = grid_search(v_rms, v_rxs, v_lrs, v_nbs)
        else:
            grid = []

        opt = grid[0] if grid else None
        if opt:
            logger.info(
                f"    최적: SL={opt['stop_loss']*100:.1f}%/TP={opt['take_profit']*100:.1f}% "
                f"→ 승률={opt['win_rate']:.1%}, EV={opt['expected_value_pct']:+.3f}%"
            )

        results["combinations"].append({
            "name": combo["name"], "desc": combo["desc"],
            "conditions": {k: str(v) for k, v in combo["conditions"].items()},
            "total_signals": n_paths,
            "signals_per_day": round(n_paths / 60, 1),
            "time_distribution": time_dist,
            "price_path": path_stats,
            "optimal_sl_tp": opt,
            "grid_top5": grid[:5],
        })

    # 베이스라인
    n_bl = len(bl_rms)
    logger.info(f"\n  베이스라인: {n_bl:,}건")
    if n_bl >= 50:
        bl_nbs_arr = np.array(bl_nbs)
        bl_valid = bl_nbs_arr >= 6
        if bl_valid.sum() >= 30:
            bl_grid = grid_search(
                [bl_rms[i] for i in range(n_bl) if bl_valid[i]],
                [bl_rxs[i] for i in range(n_bl) if bl_valid[i]],
                np.array([bl_lrs[i] for i in range(n_bl) if bl_valid[i]]),
                bl_nbs_arr[bl_valid],
            )
            bl_path = compute_path_stats(bl_rms, bl_rxs, bl_nbs, n_bl)
            results["baseline"] = {
                "total_signals": n_bl, "price_path": bl_path,
                "optimal_sl_tp": bl_grid[0] if bl_grid else None,
                "grid_top5": bl_grid[:5],
            }

    # 저장
    out_path = project_root / "reports" / "price_path_analysis.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"\n결과 저장: {out_path}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
