#!/usr/bin/env python3
"""모의 포워드 일일 리컨실 리포트 — 백테스트 가정 vs 모의 실측.

mock_forward_fills 의 그날 체결을 읽어 실현 슬리피지·체결 적중률·승률을 집계하고,
백테스트 기대치와 비교해 실거래 진입 게이트(go_live_gate)를 평가한다.

사용:
    python scripts/mock_forward_report.py --date 2026-06-10 \
        --bt-slippage-bps 25 --bt-winrate 0.58
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(project_root / ".env")

from src.backtest.fill_reconciliation import FillRecord, go_live_gate, reconcile  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.database.repositories import MockForwardFillRepository  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"날짜는 YYYY-MM-DD: {s!r}") from e


def _to_record(row) -> FillRecord:
    return FillRecord(
        code=row.code, side=row.side, tier=row.tier,
        intended_price=float(row.intended_price), intended_qty=row.intended_qty,
        actual_price=float(row.actual_price) if row.actual_price is not None else None,
        actual_qty=row.actual_qty, reason=row.reason or "", is_win=row.is_win,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="모의 포워드 일일 리컨실 리포트")
    p.add_argument("--date", type=_parse_date, default=date.today())
    p.add_argument("--bt-slippage-bps", type=float, default=25.0, dest="bt_slippage",
                   help="백테스트가 가정한 평균 슬리피지(bp)")
    p.add_argument("--bt-winrate", type=float, default=0.55, dest="bt_winrate",
                   help="백테스트 승률(0~1)")
    args = p.parse_args()

    with get_session() as session:
        rows = MockForwardFillRepository(session).get_for_date(args.date)

    if not rows:
        logger.info(f"{args.date} 모의 체결 기록 없음")
        return 0

    fills = [_to_record(r) for r in rows]
    summary = reconcile(fills)
    gate = go_live_gate(summary, args.bt_slippage, args.bt_winrate)

    logger.info(f"=== {args.date} 모의 포워드 리컨실 ===")
    logger.info(
        f"신호 {summary['n_signals']} / 체결 {summary['n_filled']} "
        f"(체결률 {summary['fill_rate']:.0%}) / 모의승률 {summary['win_rate']:.0%}"
    )
    logger.info(
        f"실현 슬리피지 {summary['avg_adverse_slippage_bps']}bp "
        f"(백테스트 가정 {args.bt_slippage}bp)"
    )
    for tier, t in summary["by_tier"].items():
        logger.info(f"  [{tier}] 신호 {t['signals']} / 체결률 {t['fill_rate']:.0%} / 슬리피지 {t['avg_slippage_bps']}bp")

    verdict = "통과(실거래 진입 가능)" if gate["passed"] else "차단(추가 검증 필요)"
    logger.info(
        f"게이트: {verdict} | 체결 {gate['fill_ok']} / 슬리피지 {gate['slippage_ok']} / "
        f"승률 {gate['winrate_ok']}(하락 {gate['winrate_drop']:+.0%})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
