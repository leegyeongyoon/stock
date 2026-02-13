"""경윤 전략 분석 결과 확인 - 매매 자제일 무시하고 후보 확인"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, time


async def main():
    from src.strategies.hongstyle.hongstyle_engine import HongStyleEngine
    from src.strategies.hongstyle.daily_filter_provider import DailyFilterProvider

    engine = HongStyleEngine()
    filter_provider = DailyFilterProvider()

    print("=" * 60)
    print(f"경윤 전략 분석 테스트 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 60)

    # 1) 필터 데이터 로드
    print("\n[1] 필터 데이터 로딩...")
    await filter_provider.refresh()
    print(f"  데이터 날짜: {filter_provider._data_date}")
    print(f"  전체 종목: {len(filter_provider._cache)}개")

    cap_pass = sum(1 for c in filter_provider._cache.values() if c.get("cap_bil", 0) >= 5000)
    inst_pass = sum(1 for c in filter_provider._cache.values() if 50 <= c.get("inst_bil", 0) <= 200)
    both_pass = sum(1 for c in filter_provider._cache.values()
                    if c.get("cap_bil", 0) >= 5000 and 50 <= c.get("inst_bil", 0) <= 200)
    print(f"  시총 5000억+: {cap_pass}개")
    print(f"  기관 50~200억: {inst_pass}개")
    print(f"  둘 다 통과: {both_pass}개")

    # 2) 홍인기 분석 실행
    print("\n[2] 홍인기 분석 실행 (run_analysis)...")
    result = await engine.run_analysis()

    print(f"  매매 자제일: {result.is_caution_day}")
    print(f"  주도 섹터: {len(result.leading_sectors)}개")
    for i, sector in enumerate(result.leading_sectors[:5]):
        print(f"    #{i+1} {sector.name}: 종목 {sector.stock_count}개, "
              f"거래대금 {sector.trading_value/1e8:.0f}억")

    print(f"  대장주: {len(result.leader_stocks)}개")
    for stock in result.leader_stocks:
        print(f"    {stock.get('name', stock.get('stock_name', '?'))} "
              f"({stock.get('code', stock.get('stock_code', '?'))})")

    print(f"  종목 분석: {len(result.stock_analyses)}개")

    # 3) 각 종목 시그널 확인
    print("\n[3] 시그널 분석 결과:")
    buy_candidates = []
    for sa in result.stock_analyses:
        sig = sa.entry_signal
        ki = sa.ki_score.score if sa.ki_score else 0
        print(f"  {sa.code} | action={sig.action} | conf={sig.confidence:.2f} | "
              f"method={sig.method} | ki={ki:.0f} | leader={sa.is_leader}")
        if sig.high_severity_patterns:
            print(f"    위험패턴: {sig.high_severity_patterns}")

        if sig.action == "buy" and sig.confidence >= 0.5:
            buy_candidates.append({
                "code": sa.code,
                "confidence": sig.confidence,
                "method": sig.method,
                "ki": ki,
                "is_leader": sa.is_leader,
            })

    # 4) 경윤 3대 필터 적용
    print(f"\n[4] 경윤 3대 필터 적용 (매수 후보 {len(buy_candidates)}건):")
    now_time = datetime.now().time()
    final_candidates = []

    for c in buy_candidates:
        code = c["code"]
        # 필터 1: 시총
        cap_ok = filter_provider.passes_market_cap(code)
        # 필터 2: 기관
        inst_ok = filter_provider.passes_inst_filter(code)
        # 필터 3: 시간대
        if c["method"] == "돌파매매":
            time_ok = time(9, 30) <= now_time <= time(11, 0)
            time_label = "돌파(09:30~11:00)"
        elif c["method"] == "눌림매매":
            time_ok = time(13, 0) <= now_time <= time(14, 30)
            time_label = "눌림(13:00~14:30)"
        else:
            time_ok = True
            time_label = "기타"

        status = "PASS" if (cap_ok and inst_ok and time_ok) else "FAIL"
        fail_reasons = []
        if not cap_ok:
            fail_reasons.append("시총<5000억")
        if not inst_ok:
            fail_reasons.append("기관범위밖")
        if not time_ok:
            fail_reasons.append(f"시간대({time_label})")

        print(f"  {code} | {c['method']} | conf={c['confidence']:.2f} | "
              f"시총={'O' if cap_ok else 'X'} | 기관={'O' if inst_ok else 'X'} | "
              f"시간={'O' if time_ok else 'X'} → {status}"
              f"{' (' + ', '.join(fail_reasons) + ')' if fail_reasons else ''}")

        if status == "PASS":
            final_candidates.append(c)

    print(f"\n{'=' * 60}")
    print(f"최종 결과: {len(buy_candidates)}건 매수후보 → 필터 후 {len(final_candidates)}건")
    if result.is_caution_day:
        print("⚠  주의: 오늘은 매매 자제일이지만 분석 결과를 표시합니다")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
