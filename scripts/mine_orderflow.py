#!/usr/bin/env python3
"""호가/체결강도 엣지 검증 — 수집된 orderflow_snapshots 로 '체결강도가 상승을 예측하나' 분석.

OHLC 봉으론 엣지가 없었다(그리드 전수 검증). 이 스크립트는 체결강도(cttr)·호가잔량비가
앞으로의 가격 상승을 예측하는지 본다. 예측력이 있으면 → 라이브 게이트로 쓸 가치가 있다.

collect_orderflow 로 데이터를 모은 뒤 실행. DATABASE_URL 필요.
    DATABASE_URL=... python scripts/mine_orderflow.py --horizon 5 --start 2026-06-10
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(project_root / ".env")

import numpy as np  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from src.database.connection import get_session  # noqa: E402
from src.database.models import OrderFlowSnapshot  # noqa: E402
from src.database.repositories import OrderFlowSnapshotRepository  # noqa: E402


def _bucket_report(name: str, x: np.ndarray, fwd: np.ndarray):
    print(f"\n[{name}]  (전체 평균 전방수익 {fwd.mean()*100:+.3f}%)")
    qs = np.quantile(x, [0, 0.25, 0.5, 0.75, 1.0])
    for a, b in zip(qs[:-1], qs[1:]):
        mask = (x >= a) & (x <= b) if b == qs[-1] else (x >= a) & (x < b)
        if mask.sum() < 30:
            continue
        sub = fwd[mask]
        print(f"   {a:8.1f}~{b:8.1f}: 전방수익 {sub.mean()*100:+.3f}% / 승률 {(sub>0).mean():.0%} ({mask.sum():,}건)")


def run(args):
    horizon = timedelta(minutes=args.horizon)
    with get_session() as s:
        codes = [r[0] for r in s.execute(
            text("SELECT DISTINCT code FROM orderflow_snapshots")
        ).fetchall()]
    if not codes:
        print("orderflow_snapshots 비어있음 — collect_orderflow 먼저 실행")
        return 1
    print(f"종목 {len(codes)}개, 전방 {args.horizon}분 수익 라벨링…")

    strengths, ratios, fwds = [], [], []
    with get_session() as s:
        repo = OrderFlowSnapshotRepository(s)
        for code in codes:
            df = repo.get_by_code(code)
            if df.empty or len(df) < 5:
                continue
            df = df[df["current_price"] > 0]
            times = df.index.to_pydatetime()
            price = df["current_price"].to_numpy(float)
            es = df["exec_strength"].to_numpy(float)
            br = df["bid_ask_ratio"].to_numpy(float)
            n = len(df)
            for i in range(n):
                target_t = times[i] + horizon
                j = i + 1
                while j < n and times[j] < target_t:
                    j += 1
                if j >= n:
                    break
                fwd = price[j] / price[i] - 1.0
                if np.isnan(es[i]):
                    continue
                strengths.append(es[i]); ratios.append(br[i] if not np.isnan(br[i]) else 1.0)
                fwds.append(fwd)

    if not fwds:
        print("라벨 샘플 없음(데이터 더 필요)")
        return 1
    es = np.array(strengths); br = np.array(ratios); fwd = np.array(fwds)
    print(f"\n총 {len(fwd):,}샘플 | 전방 {args.horizon}분 평균수익 {fwd.mean()*100:+.3f}%")
    print("체결강도/잔량비가 높을수록 전방수익이 커지면 = 예측력 있음(라이브 게이트로 가치)")
    _bucket_report("체결강도(exec_strength)", es, fwd)
    _bucket_report("호가잔량비(bid_ask_ratio)", br, fwd)

    # 상관계수
    print(f"\n상관계수: 체결강도-전방수익 {np.corrcoef(es, fwd)[0,1]:+.3f} / "
          f"잔량비-전방수익 {np.corrcoef(br, fwd)[0,1]:+.3f}")
    return 0


def main():
    p = argparse.ArgumentParser(description="호가/체결강도 예측력 검증")
    p.add_argument("--horizon", type=int, default=5, help="전방 수익 측정 시간(분)")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
