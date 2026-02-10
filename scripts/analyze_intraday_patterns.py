#!/usr/bin/env python3
"""분봉 데이터 패턴 마이닝 - 급등 직전 신호 탐색.

ohlcv_intraday 테이블의 5분봉 데이터(~190만건, 462종목, 60거래일)에서
급등 구간(일중 3%+ 상승) 직전에 나타나는 피처를 추출하고 예측력을 측정한다.

Output: reports/intraday_pattern_analysis.json
"""

import json
import sys
from datetime import datetime
from itertools import combinations
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import text

from src.database.connection import get_engine
from src.utils.logger import get_logger

logger = get_logger(__name__)

# --- Configuration ---
SURGE_THRESHOLD = 0.03       # 3% 일중 상승 = "급등"
LOOKBACK_BARS = 10           # 급등 직전 분석 구간
FORWARD_BARS = 6             # 미래 30분 (5분봉 6개)
MIN_BARS_PER_DAY = 20        # 최소 바 수 (유효 거래일)
HIT_RATE_THRESHOLD = 0.55    # 히트율 필터
AVG_RETURN_THRESHOLD = 0.005 # 평균수익률 필터 (0.5%)
MIN_OCCURRENCES = 200        # 최소 발생 건수


def load_all_intraday_data() -> pd.DataFrame:
    """DB에서 전체 분봉 데이터 로드 (단일 쿼리)."""
    engine = get_engine()
    logger.info("전체 분봉 데이터 로드 중...")

    query = text("""
        SELECT code, datetime, open, high, low, close, volume
        FROM ohlcv_intraday
        ORDER BY code, datetime
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    logger.info(
        f"로드 완료: {len(df):,}건, {df['code'].nunique()}종목, "
        f"{df['date'].nunique()}거래일"
    )
    return df


def identify_surge_bars(group: pd.DataFrame) -> list[int]:
    """종목-일자 그룹에서 급등 시작 bar 인덱스 식별.

    급등 정의: bar의 close가 당일 시가 대비 SURGE_THRESHOLD% 이상 상승하되,
    직전 bar까지는 아직 그 수준에 도달하지 않았던 '최초 돌파' 시점.
    """
    if len(group) < MIN_BARS_PER_DAY:
        return []

    opens = group["open"].values
    closes = group["close"].values
    day_open = opens[0]

    if day_open == 0:
        return []

    returns_from_open = (closes - day_open) / day_open
    surge_indices = []

    for i in range(1, len(returns_from_open)):
        if returns_from_open[i] >= SURGE_THRESHOLD and returns_from_open[i - 1] < SURGE_THRESHOLD:
            if i >= LOOKBACK_BARS:
                surge_indices.append(i)

    return surge_indices


def compute_features(group: pd.DataFrame, bar_idx: int) -> dict:
    """급등 직전 bar_idx 위치에서 30+ 피처 추출."""
    opens = group["open"].values.astype(float)
    highs = group["high"].values.astype(float)
    lows = group["low"].values.astype(float)
    closes = group["close"].values.astype(float)
    volumes = group["volume"].values.astype(float)
    timestamps = group["datetime"].values

    i = bar_idx
    day_open = opens[0]

    features = {}

    # === 가격 피처 ===

    # 직전 N bars 수익률
    for n in [1, 3, 5, 10]:
        if i >= n:
            features[f"return_{n}bar"] = (closes[i] - closes[i - n]) / closes[i - n]
        else:
            features[f"return_{n}bar"] = 0.0

    # 당일 시가 대비 위치
    features["pos_vs_day_open"] = (closes[i] - day_open) / day_open if day_open > 0 else 0.0

    # 캔들 몸통비율 (직전 bar)
    bar_range = highs[i] - lows[i]
    body = abs(closes[i] - opens[i])
    features["body_ratio"] = body / bar_range if bar_range > 0 else 0.0

    # 상하 꼬리 비율
    if bar_range > 0:
        upper_wick = highs[i] - max(closes[i], opens[i])
        lower_wick = min(closes[i], opens[i]) - lows[i]
        features["upper_wick_ratio"] = upper_wick / bar_range
        features["lower_wick_ratio"] = lower_wick / bar_range
    else:
        features["upper_wick_ratio"] = 0.0
        features["lower_wick_ratio"] = 0.0

    # 양봉 여부
    features["is_bullish"] = 1.0 if closes[i] > opens[i] else 0.0

    # 연속 양봉 수
    consecutive_bull = 0
    for j in range(i, max(i - 10, -1), -1):
        if closes[j] > opens[j]:
            consecutive_bull += 1
        else:
            break
    features["consecutive_bullish"] = float(consecutive_bull)

    # 연속 음봉 수
    consecutive_bear = 0
    for j in range(i, max(i - 10, -1), -1):
        if closes[j] < opens[j]:
            consecutive_bear += 1
        else:
            break
    features["consecutive_bearish"] = float(consecutive_bear)

    # 최근 10bars 고가/저가 대비 위치
    if i >= 10:
        recent_high = np.max(highs[i - 10:i + 1])
        recent_low = np.min(lows[i - 10:i + 1])
        price_range = recent_high - recent_low
        features["pos_in_range_10"] = (closes[i] - recent_low) / price_range if price_range > 0 else 0.5
    else:
        features["pos_in_range_10"] = 0.5

    # === 거래량 피처 ===

    # 당일 20바 평균 대비
    vol_window = min(20, i + 1)
    avg_vol_20 = np.mean(volumes[max(0, i - vol_window + 1):i + 1])
    features["vol_ratio_avg20"] = volumes[i] / avg_vol_20 if avg_vol_20 > 0 else 1.0

    # 직전 bar 대비
    if i >= 1:
        features["vol_ratio_prev"] = volumes[i] / volumes[i - 1] if volumes[i - 1] > 0 else 1.0
    else:
        features["vol_ratio_prev"] = 1.0

    # 거래량 연속 증가 bars 수
    vol_increase_count = 0
    for j in range(i, max(i - 10, 0), -1):
        if j >= 1 and volumes[j] > volumes[j - 1]:
            vol_increase_count += 1
        else:
            break
    features["vol_consecutive_increase"] = float(vol_increase_count)

    # 거래량 급증 여부 (2x 이상)
    features["vol_surge_2x"] = 1.0 if features["vol_ratio_avg20"] >= 2.0 else 0.0
    features["vol_surge_3x"] = 1.0 if features["vol_ratio_avg20"] >= 3.0 else 0.0

    # === VWAP 피처 ===
    typical_prices = (highs[:i + 1] + lows[:i + 1] + closes[:i + 1]) / 3.0
    cum_vol = np.cumsum(volumes[:i + 1])
    cum_tp_vol = np.cumsum(typical_prices * volumes[:i + 1])
    vwap = cum_tp_vol[-1] / cum_vol[-1] if cum_vol[-1] > 0 else closes[i]

    features["vwap_deviation"] = (closes[i] - vwap) / vwap if vwap > 0 else 0.0
    features["above_vwap"] = 1.0 if closes[i] > vwap else 0.0

    # === 변동성 피처 ===

    # 직전 10bars 고가-저가 범위
    if i >= 10:
        hl_ranges = highs[i - 9:i + 1] - lows[i - 9:i + 1]
        features["avg_bar_range_10"] = np.mean(hl_ranges) / closes[i] if closes[i] > 0 else 0.0
    else:
        hl_ranges = highs[:i + 1] - lows[:i + 1]
        features["avg_bar_range_10"] = np.mean(hl_ranges) / closes[i] if closes[i] > 0 else 0.0

    # ATR(10bars)
    if i >= 10:
        tr_values = []
        for j in range(max(1, i - 9), i + 1):
            tr = max(
                highs[j] - lows[j],
                abs(highs[j] - closes[j - 1]),
                abs(lows[j] - closes[j - 1]),
            )
            tr_values.append(tr)
        features["atr_10"] = np.mean(tr_values) / closes[i] if closes[i] > 0 else 0.0
    else:
        features["atr_10"] = features["avg_bar_range_10"]

    # 변동성 추세: 최근 5bars vs 이전 5bars ATR 비교
    if i >= 10:
        recent_ranges = highs[i - 4:i + 1] - lows[i - 4:i + 1]
        older_ranges = highs[i - 9:i - 4] - lows[i - 9:i - 4]
        recent_avg = np.mean(recent_ranges)
        older_avg = np.mean(older_ranges)
        features["volatility_expansion"] = recent_avg / older_avg if older_avg > 0 else 1.0
    else:
        features["volatility_expansion"] = 1.0

    # === 시간 피처 ===
    ts = pd.Timestamp(timestamps[i])
    hour = ts.hour
    minute = ts.minute
    minutes_from_open = (hour - 9) * 60 + minute  # 9시 기준

    features["time_hour"] = float(hour)
    features["minutes_from_open"] = float(minutes_from_open)

    # 시간대 원핫
    features["time_0900_1000"] = 1.0 if 0 <= minutes_from_open < 60 else 0.0
    features["time_1000_1100"] = 1.0 if 60 <= minutes_from_open < 120 else 0.0
    features["time_1100_1200"] = 1.0 if 120 <= minutes_from_open < 180 else 0.0
    features["time_1200_1300"] = 1.0 if 180 <= minutes_from_open < 240 else 0.0
    features["time_1300_1400"] = 1.0 if 240 <= minutes_from_open < 300 else 0.0
    features["time_1400_1530"] = 1.0 if minutes_from_open >= 300 else 0.0

    # === RSI 간이 계산 (14-bar) ===
    if i >= 14:
        deltas = np.diff(closes[max(0, i - 14):i + 1])
        gains = np.mean(np.maximum(deltas, 0))
        losses_val = np.mean(np.maximum(-deltas, 0))
        if losses_val > 0:
            rs = gains / losses_val
            features["rsi_14"] = 100 - (100 / (1 + rs))
        else:
            features["rsi_14"] = 100.0
    else:
        features["rsi_14"] = 50.0

    # === 가격 모멘텀 가속도 ===
    if i >= 5:
        recent_ret = (closes[i] - closes[i - 3]) / closes[i - 3] if closes[i - 3] > 0 else 0
        older_ret = (closes[i - 3] - closes[i - 6]) / closes[i - 6] if i >= 6 and closes[i - 6] > 0 else 0
        features["momentum_acceleration"] = recent_ret - older_ret
    else:
        features["momentum_acceleration"] = 0.0

    return features


def compute_forward_return(group: pd.DataFrame, bar_idx: int) -> float:
    """bar_idx 이후 FORWARD_BARS(30분) 수익률 계산."""
    closes = group["close"].values.astype(float)
    end_idx = min(bar_idx + FORWARD_BARS, len(closes) - 1)
    if end_idx <= bar_idx:
        return 0.0
    return (closes[end_idx] - closes[bar_idx]) / closes[bar_idx]


def extract_all_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """전체 데이터에서 급등/일반 구간 피처 추출.

    Returns:
        (surge_features_df, normal_features_df)
    """
    surge_records = []
    normal_records = []
    total_surge_count = 0

    grouped = df.groupby(["code", "date"])
    total_groups = len(grouped)
    logger.info(f"종목-일자 조합: {total_groups:,}개 분석 시작")

    for idx, ((code, date), group) in enumerate(grouped):
        if idx % 5000 == 0 and idx > 0:
            logger.info(f"  진행: {idx:,}/{total_groups:,} ({idx/total_groups*100:.1f}%)")

        group = group.sort_values("datetime").reset_index(drop=True)

        if len(group) < MIN_BARS_PER_DAY:
            continue

        # 급등 bar 식별
        surge_bars = identify_surge_bars(group)
        total_surge_count += len(surge_bars)

        for sb in surge_bars:
            # 급등 직전 bar에서 피처 추출
            pre_surge_idx = sb - 1
            if pre_surge_idx < LOOKBACK_BARS:
                continue

            features = compute_features(group, pre_surge_idx)
            features["forward_return"] = compute_forward_return(group, pre_surge_idx)
            features["code"] = code
            features["date"] = str(date)
            features["label"] = "surge"
            surge_records.append(features)

        # 일반 구간 샘플링 (급등이 아닌 bar에서 동일 수 추출)
        surge_set = set(surge_bars)
        normal_candidates = [
            i for i in range(LOOKBACK_BARS, len(group) - FORWARD_BARS)
            if i not in surge_set and (i - 1) not in surge_set and (i + 1) not in surge_set
        ]

        n_samples = min(len(surge_bars), len(normal_candidates))
        if n_samples > 0:
            rng = np.random.RandomState(42)
            sampled = rng.choice(normal_candidates, size=n_samples, replace=False)
            for ni in sampled:
                features = compute_features(group, ni)
                features["forward_return"] = compute_forward_return(group, ni)
                features["code"] = code
                features["date"] = str(date)
                features["label"] = "normal"
                normal_records.append(features)

    logger.info(f"급등 구간: {total_surge_count:,}건, 피처 추출: 급등={len(surge_records):,}, 일반={len(normal_records):,}")

    surge_df = pd.DataFrame(surge_records)
    normal_df = pd.DataFrame(normal_records)
    return surge_df, normal_df


def measure_feature_predictive_power(
    surge_df: pd.DataFrame,
    normal_df: pd.DataFrame,
    feature_cols: list[str],
) -> list[dict]:
    """각 피처의 예측력 측정.

    - 피처 상위/하위 20% 비교
    - 히트율 (조건 충족 시 30분 양수 확률)
    - IC (rank correlation)
    """
    combined = pd.concat([surge_df, normal_df], ignore_index=True)
    results = []

    for feat in feature_cols:
        if feat in ("code", "date", "label", "forward_return"):
            continue

        vals = combined[feat].values
        fwd = combined["forward_return"].values

        valid_mask = ~(np.isnan(vals) | np.isnan(fwd))
        vals_valid = vals[valid_mask]
        fwd_valid = fwd[valid_mask]

        if len(vals_valid) < 100:
            continue

        # IC: rank correlation
        try:
            ic, ic_pval = stats.spearmanr(vals_valid, fwd_valid)
        except Exception:
            ic, ic_pval = 0.0, 1.0

        # 상위 20% vs 하위 20%
        q80 = np.percentile(vals_valid, 80)
        q20 = np.percentile(vals_valid, 20)

        top_mask = vals_valid >= q80
        bottom_mask = vals_valid <= q20

        top_fwd = fwd_valid[top_mask]
        bottom_fwd = fwd_valid[bottom_mask]

        top_avg = np.mean(top_fwd) if len(top_fwd) > 0 else 0.0
        bottom_avg = np.mean(bottom_fwd) if len(bottom_fwd) > 0 else 0.0

        # 히트율: 상위 20%일 때 양수 확률
        top_hit_rate = np.mean(top_fwd > 0) if len(top_fwd) > 0 else 0.0

        # 급등 구간 vs 일반 구간 분포
        surge_vals = surge_df[feat].values
        normal_vals = normal_df[feat].values
        surge_mean = np.nanmean(surge_vals) if len(surge_vals) > 0 else 0.0
        normal_mean = np.nanmean(normal_vals) if len(normal_vals) > 0 else 0.0

        results.append({
            "feature": feat,
            "ic": round(float(ic), 4),
            "ic_pval": round(float(ic_pval), 6),
            "top20_avg_return": round(float(top_avg), 6),
            "bottom20_avg_return": round(float(bottom_avg), 6),
            "spread": round(float(top_avg - bottom_avg), 6),
            "top20_hit_rate": round(float(top_hit_rate), 4),
            "top20_count": int(np.sum(top_mask)),
            "surge_mean": round(float(surge_mean), 6),
            "normal_mean": round(float(normal_mean), 6),
            "surge_vs_normal_diff": round(float(surge_mean - normal_mean), 6),
        })

    # IC 절댓값 기준 정렬
    results.sort(key=lambda x: abs(x["ic"]), reverse=True)
    return results


def find_best_feature_combinations(
    combined_df: pd.DataFrame,
    top_features: list[str],
    max_combo_size: int = 3,
) -> list[dict]:
    """상위 피처 2~3개 조합의 히트율/평균수익률/발생건수 측정."""
    results = []

    for combo_size in range(2, max_combo_size + 1):
        for combo in combinations(top_features, combo_size):
            # 각 피처 상위 50% 이상 조건 (AND)
            mask = np.ones(len(combined_df), dtype=bool)
            thresholds = {}

            for feat in combo:
                vals = combined_df[feat].values
                median = np.nanmedian(vals)
                thresholds[feat] = round(float(median), 6)
                feat_mask = vals >= median
                mask = mask & feat_mask

            selected = combined_df[mask]
            count = len(selected)

            if count < MIN_OCCURRENCES:
                continue

            fwd_returns = selected["forward_return"].values
            hit_rate = float(np.mean(fwd_returns > 0))
            avg_return = float(np.mean(fwd_returns))
            median_return = float(np.median(fwd_returns))

            if hit_rate >= HIT_RATE_THRESHOLD and avg_return >= AVG_RETURN_THRESHOLD:
                results.append({
                    "features": list(combo),
                    "thresholds": thresholds,
                    "count": count,
                    "hit_rate": round(hit_rate, 4),
                    "avg_return": round(avg_return, 6),
                    "median_return": round(median_return, 6),
                    "combo_size": combo_size,
                })

    results.sort(key=lambda x: x["avg_return"], reverse=True)
    return results


def measure_by_time_period(
    combined_df: pd.DataFrame,
    feature_cols: list[str],
) -> dict:
    """시간대별로 피처 예측력 측정."""
    periods = {
        "morning_early": (0, 60),     # 9:00-10:00
        "morning_late": (60, 120),    # 10:00-11:00
        "midday": (120, 240),         # 11:00-13:00
        "afternoon": (240, 390),      # 13:00-15:30
    }

    period_results = {}

    for period_name, (start_min, end_min) in periods.items():
        period_mask = (
            (combined_df["minutes_from_open"] >= start_min) &
            (combined_df["minutes_from_open"] < end_min)
        )
        period_df = combined_df[period_mask]

        if len(period_df) < 200:
            continue

        top_features_for_period = []
        for feat in feature_cols:
            if feat in ("code", "date", "label", "forward_return", "minutes_from_open",
                        "time_hour", "time_0900_1000", "time_1000_1100", "time_1100_1200",
                        "time_1200_1300", "time_1300_1400", "time_1400_1530"):
                continue

            vals = period_df[feat].values
            fwd = period_df["forward_return"].values
            valid = ~(np.isnan(vals) | np.isnan(fwd))

            if np.sum(valid) < 50:
                continue

            try:
                ic, _ = stats.spearmanr(vals[valid], fwd[valid])
            except Exception:
                ic = 0.0

            q80 = np.percentile(vals[valid], 80)
            top_mask = vals[valid] >= q80
            top_fwd = fwd[valid][top_mask]
            hit_rate = float(np.mean(top_fwd > 0)) if len(top_fwd) > 0 else 0.0

            top_features_for_period.append({
                "feature": feat,
                "ic": round(float(ic), 4),
                "hit_rate": round(hit_rate, 4),
                "count": int(np.sum(valid)),
            })

        top_features_for_period.sort(key=lambda x: abs(x["ic"]), reverse=True)
        period_results[period_name] = top_features_for_period[:10]

    return period_results


def main():
    logger.info("=" * 70)
    logger.info("분봉 데이터 패턴 마이닝 시작")
    logger.info(f"급등 임계값: {SURGE_THRESHOLD*100:.1f}%, 전방 수익률: {FORWARD_BARS*5}분")
    logger.info("=" * 70)

    # Step A: 데이터 로드
    df = load_all_intraday_data()

    # Step B: 피처 추출
    logger.info("\n[Step B] 급등 구간 식별 및 피처 추출...")
    surge_df, normal_df = extract_all_features(df)

    if surge_df.empty:
        logger.error("급등 구간을 찾지 못했습니다. 임계값을 낮춰 보세요.")
        return

    # 피처 컬럼 식별
    meta_cols = {"code", "date", "label", "forward_return"}
    feature_cols = [c for c in surge_df.columns if c not in meta_cols]
    logger.info(f"추출된 피처 수: {len(feature_cols)}")

    # Step C: 예측력 측정
    logger.info("\n[Step C] 피처 예측력 측정...")
    feature_power = measure_feature_predictive_power(surge_df, normal_df, feature_cols)

    logger.info("\n--- TOP 15 예측력 피처 ---")
    for i, fp in enumerate(feature_power[:15], 1):
        logger.info(
            f"  {i:2d}. {fp['feature']:30s}  IC={fp['ic']:+.4f}  "
            f"히트율={fp['top20_hit_rate']:.1%}  "
            f"스프레드={fp['spread']:+.4%}"
        )

    # Step C-2: 시간대별 분석
    logger.info("\n[Step C-2] 시간대별 예측력 분석...")
    combined_df = pd.concat([surge_df, normal_df], ignore_index=True)
    time_period_results = measure_by_time_period(combined_df, feature_cols)

    for period, feats in time_period_results.items():
        logger.info(f"\n  [{period}] TOP 5:")
        for fp in feats[:5]:
            logger.info(
                f"    {fp['feature']:30s}  IC={fp['ic']:+.4f}  히트율={fp['hit_rate']:.1%}"
            )

    # Step D: 피처 조합 탐색
    logger.info("\n[Step D] 피처 조합 탐색...")
    top_10_features = [fp["feature"] for fp in feature_power[:10]]
    logger.info(f"상위 10개 피처 조합 탐색: {top_10_features}")

    combos = find_best_feature_combinations(combined_df, top_10_features, max_combo_size=3)
    logger.info(f"필터 통과 조합: {len(combos)}개 (히트율>={HIT_RATE_THRESHOLD*100:.0f}%, 평균수익>={AVG_RETURN_THRESHOLD*100:.1f}%, 발생>={MIN_OCCURRENCES}건)")

    logger.info("\n--- TOP 20 피처 조합 ---")
    for i, combo in enumerate(combos[:20], 1):
        logger.info(
            f"  {i:2d}. {combo['features']}  "
            f"히트율={combo['hit_rate']:.1%}  "
            f"평균수익={combo['avg_return']:.3%}  "
            f"발생={combo['count']}건"
        )

    # Step E: 결과 저장
    logger.info("\n[Step E] 결과 저장...")

    # 급등 vs 일반 분포 비교 (상위 피처)
    distribution_comparison = {}
    for fp in feature_power[:15]:
        feat = fp["feature"]
        distribution_comparison[feat] = {
            "surge_mean": fp["surge_mean"],
            "normal_mean": fp["normal_mean"],
            "diff": fp["surge_vs_normal_diff"],
        }

    report = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "surge_threshold": SURGE_THRESHOLD,
            "lookback_bars": LOOKBACK_BARS,
            "forward_bars": FORWARD_BARS,
            "forward_minutes": FORWARD_BARS * 5,
            "min_bars_per_day": MIN_BARS_PER_DAY,
            "hit_rate_threshold": HIT_RATE_THRESHOLD,
            "avg_return_threshold": AVG_RETURN_THRESHOLD,
            "min_occurrences": MIN_OCCURRENCES,
        },
        "data_stats": {
            "total_records": len(df),
            "stocks": int(df["code"].nunique()),
            "trading_days": int(df["date"].nunique()),
            "surge_events": len(surge_df),
            "normal_events": len(normal_df),
            "feature_count": len(feature_cols),
        },
        "feature_predictive_power": feature_power,
        "top_feature_combinations": combos[:30],
        "time_period_analysis": time_period_results,
        "distribution_comparison": distribution_comparison,
        "top_features_for_ai": [fp["feature"] for fp in feature_power[:15]],
    }

    report_path = project_root / "reports" / "intraday_pattern_analysis.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"\n결과 저장: {report_path}")
    logger.info("=" * 70)
    logger.info("패턴 마이닝 완료!")
    logger.info(f"  급등 이벤트: {len(surge_df):,}건")
    logger.info(f"  예측력 피처: {len(feature_power)}개")
    logger.info(f"  유효 조합: {len(combos)}개")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
