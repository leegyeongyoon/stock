"""홍인기 전략 집중투자 버전 - 오늘(2026-02-12) 핫테마 기준

변경점 (보수적 버전 대비):
- 포지션 사이즈: 50% (확신) / 30% (보통) → 기존 15%/6%/3%
- 최대 포지션: 2개 (기존 5개)
- 진입 조건 완화: vol 1.2x (기존 1.5x), 시간 9:05~11:30 (기존 9:10~11:00)
- 매도 후 재진입 허용
- 확신도 순으로 진입 우선순위
"""

import os
import sys
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()
from loguru import logger

from src.strategies.hongstyle.daily_chart_analyzer import DailyChartAnalyzer
from src.strategies.hongstyle.pattern_detector import PatternDetector
from src.strategies.hongstyle.signal_generator import SignalGenerator

STOCKS = {
    '028260': {'name': '삼성물산', 'theme': '건설'},
    '000720': {'name': '현대건설', 'theme': '건설'},
    '047040': {'name': '대우건설', 'theme': '건설'},
    '003240': {'name': '태광산업', 'theme': '홈쇼핑'},
    '023530': {'name': '롯데쇼핑', 'theme': '홈쇼핑'},
    '057050': {'name': '현대홈쇼핑', 'theme': '홈쇼핑'},
    '055550': {'name': '신한지주', 'theme': '은행'},
    '175330': {'name': 'JB금융', 'theme': '은행'},
    '138930': {'name': 'BNK금융', 'theme': '은행'},
    '002020': {'name': '코오롱', 'theme': '두나무'},
    '120110': {'name': '코오롱인더', 'theme': '두나무'},
    '003530': {'name': '한화투자증권', 'theme': '두나무'},
    '000810': {'name': '삼성화재', 'theme': '손해보험'},
    '005830': {'name': 'DB손해보험', 'theme': '손해보험'},
    '000370': {'name': '한화손해보험', 'theme': '손해보험'},
    '000660': {'name': 'SK하이닉스', 'theme': 'IT'},
    '004170': {'name': '신세계', 'theme': '백화점'},
    '017670': {'name': 'SK텔레콤', 'theme': '통신'},
}

COMMISSION = 0.00015
TAX = 0.0023
INIT_CAPITAL = 10_000_000

# ── 집중투자 설정 ──
MAX_POSITIONS = 2           # 최대 2종목
ALLOC_HIGH = 0.50           # 확신 종목: 자본의 50%
ALLOC_MED = 0.30            # 보통 종목: 자본의 30%
VOL_THRESHOLD = 1.2         # 거래량 돌파 기준 (기존 1.5 → 1.2)
ALLOW_REENTRY = True        # 매도 후 재진입 허용
TOP_N_ONLY = 5              # 확신도 상위 N개만 진입 대상


def main():
    # ── 데이터 로드 ──
    logger.info("데이터 로딩...")
    intraday = pd.read_csv('/tmp/today_5min.csv')
    intraday['datetime'] = pd.to_datetime(intraday['datetime'])
    intraday['code'] = intraday['code'].astype(str).str.zfill(6)

    from sqlalchemy import create_engine
    db_engine = create_engine(os.getenv('DATABASE_URL'))
    codes = list(STOCKS.keys())
    placeholders = ','.join(f"'{c}'" for c in codes)
    daily = pd.read_sql(
        f"SELECT code, date, open, high, low, close, volume FROM ohlcv_daily "
        f"WHERE code IN ({placeholders}) ORDER BY code, date",
        db_engine,
    )
    daily['date'] = pd.to_datetime(daily['date'])
    logger.info(f"오늘 5분봉: {len(intraday)}행, 일봉: {len(daily)}행")

    # ── 홍인기 엔진 컴포넌트 ──
    chart_analyzer = DailyChartAnalyzer()
    pattern_detector = PatternDetector()
    signal_generator = SignalGenerator()

    # ── 종목별 사전 분석 (일봉) ──
    logger.info("종목별 일봉 분석...")
    stock_analysis = {}
    for code, info in STOCKS.items():
        stock_daily = daily[daily['code'] == code].copy()
        if stock_daily.empty:
            continue

        ki = chart_analyzer.calculate_ki(stock_daily)
        position = chart_analyzer.classify_daily_position(stock_daily)
        is_leader = code in [
            '028260', '003240', '055550', '002020',
            '000810', '000660', '004170', '017670',
        ]

        entry_signal = signal_generator.generate_entry_signal(
            stock_code=code,
            daily_position=position,
            ki_score=ki,
            patterns=[],
            is_leader=is_leader,
        )

        stock_analysis[code] = {
            'ki': ki, 'position': position, 'entry_signal': entry_signal,
            'is_leader': is_leader, 'daily_df': stock_daily,
        }

    # ── 매수 대상 선별 + 확신도 순 정렬 ──
    buyable = {}
    for code, a in stock_analysis.items():
        sig = a['entry_signal']
        if sig.action == 'buy' and sig.confidence >= 0.5:
            # 확신도 점수 = confidence × (끼/100) × (대장주 보너스)
            score = sig.confidence * (a['ki'].score / 100)
            if a['is_leader']:
                score *= 1.3
            buyable[code] = {**a, 'score': score}

    # 확신도 순 정렬
    ranked = sorted(buyable.items(), key=lambda x: x[1]['score'], reverse=True)

    # TOP N만 진입 대상
    top_codes = set(code for code, _ in ranked[:TOP_N_ONLY])

    logger.info(f"\n매수 가능 종목 (확신도 순, TOP {TOP_N_ONLY}만 진입):")
    for i, (code, a) in enumerate(ranked):
        sig = a['entry_signal']
        star = " ★" if a['is_leader'] else ""
        mark = " ◀ 진입대상" if code in top_codes else ""
        logger.info(
            f"  #{i+1} {STOCKS[code]['name']}{star}: "
            f"score={a['score']:.3f} conf={sig.confidence:.2f} 끼={a['ki'].score:.0f} "
            f"자리={a['position'].position_type} {sig.method}{mark}"
        )

    # ── 장중 시뮬레이션 (집중투자) ──
    logger.info("\n=== 장중 시뮬레이션 (집중투자 모드) ===")
    cash = INIT_CAPITAL
    positions = {}
    all_trades = []
    events = []
    exited_codes = set()  # 매도 완료 종목 (재진입 허용시 리셋)

    timestamps = sorted(intraday['datetime'].unique())

    for ts in timestamps:
        bars_now = intraday[intraday['datetime'] == ts]
        ts_dt = pd.Timestamp(ts)
        h, m = ts_dt.hour, ts_dt.minute

        for _, bar in bars_now.iterrows():
            code = bar['code']
            if code not in STOCKS:
                continue
            info = STOCKS[code]

            # ── 보유 포지션 모니터 ──
            if code in positions:
                pos = positions[code]
                current_price = bar['close']

                stock_bars_so_far = intraday[
                    (intraday['code'] == code) & (intraday['datetime'] <= ts)
                ].sort_values('datetime')

                patterns = pattern_detector.detect_all_patterns(
                    minute_bars=stock_bars_so_far,
                    daily_bars=stock_analysis.get(code, {}).get('daily_df'),
                )

                exit_sig = signal_generator.generate_exit_signal(
                    entry_price=pos['entry_price'],
                    current_price=current_price,
                    patterns=patterns,
                    position_info={'partial_sold': pos['partial_sold']},
                )

                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100

                if exit_sig.action == 'partial_sell' and not pos['partial_sold']:
                    sell_qty = int(pos['qty'] * exit_sig.portion)
                    if sell_qty > 0:
                        pnl_amt = (current_price - pos['entry_price']) * sell_qty
                        pnl_amt -= current_price * sell_qty * (TAX + COMMISSION)
                        cash += current_price * sell_qty * (1 - TAX - COMMISSION)
                        all_trades.append({
                            'code': code, 'name': info['name'], 'theme': info['theme'],
                            'entry': pos['entry_price'], 'exit': current_price,
                            'qty': sell_qty, 'pnl': pnl_amt, 'pnl_pct': pnl_pct,
                            'reason': exit_sig.reason, 'time': str(ts),
                            'invested': pos['entry_price'] * pos['original_qty'],
                        })
                        events.append(
                            f"  {ts_dt.strftime('%H:%M')} 📈 {info['name']} 분할매도 "
                            f"{sell_qty}주 @{current_price:,} ({pnl_pct:+.2f}%)"
                        )
                        pos['qty'] -= sell_qty
                        pos['partial_sold'] = True

                elif exit_sig.action == 'sell':
                    pnl_amt = (current_price - pos['entry_price']) * pos['qty']
                    pnl_amt -= current_price * pos['qty'] * (TAX + COMMISSION)
                    cash += current_price * pos['qty'] * (1 - TAX - COMMISSION)
                    all_trades.append({
                        'code': code, 'name': info['name'], 'theme': info['theme'],
                        'entry': pos['entry_price'], 'exit': current_price,
                        'qty': pos['qty'], 'pnl': pnl_amt, 'pnl_pct': pnl_pct,
                        'reason': exit_sig.reason, 'time': str(ts),
                        'invested': pos['entry_price'] * pos['original_qty'],
                    })
                    emoji = "🔴" if pnl_amt < 0 else "🟢"
                    events.append(
                        f"  {ts_dt.strftime('%H:%M')} {emoji} {info['name']} 전량매도 "
                        f"{pos['qty']}주 @{current_price:,} ({pnl_pct:+.2f}%) [{exit_sig.reason}]"
                    )
                    del positions[code]
                    if not ALLOW_REENTRY:
                        exited_codes.add(code)
                continue

            # ── 신규 진입 (집중투자 - TOP N만) ──
            if code not in buyable or code not in top_codes:
                continue
            if code in positions:
                continue
            if not ALLOW_REENTRY and code in exited_codes:
                continue
            if len(positions) >= MAX_POSITIONS:
                continue
            # 시간대: 9:05 ~ 11:30 (기존보다 넓게)
            if h < 9 or (h == 9 and m < 5) or (h == 11 and m > 30) or h >= 12:
                continue

            stock_bars = intraday[
                (intraday['code'] == code) & (intraday['datetime'] <= ts)
            ].sort_values('datetime')

            if len(stock_bars) < 3:
                continue

            cur_bar = stock_bars.iloc[-1]
            prev_bars = stock_bars.iloc[max(0, len(stock_bars)-6):len(stock_bars)-1]

            if len(prev_bars) == 0:
                continue

            # 양봉 확인
            if cur_bar['close'] <= cur_bar['open']:
                continue

            # 거래량 돌파 (완화: 1.2x)
            avg_vol = prev_bars['volume'].mean()
            if avg_vol <= 0:
                continue
            vol_ratio = cur_bar['volume'] / avg_vol
            if vol_ratio < VOL_THRESHOLD:
                continue

            # 전고점 돌파
            if cur_bar['close'] <= prev_bars['high'].max():
                continue

            # 위험 패턴 체크
            patterns = pattern_detector.detect_all_patterns(
                minute_bars=stock_bars,
                daily_bars=stock_analysis[code]['daily_df'],
            )
            high_severity = [p for p in patterns if p.severity == 'high']
            if high_severity:
                continue

            # ── 집중투자 포지션 사이징 ──
            ki_score = stock_analysis[code]['ki'].score
            confidence = stock_analysis[code]['entry_signal'].confidence
            score = buyable[code]['score']

            # 확신 종목 50%, 보통 30%
            if confidence >= 0.7 and ki_score >= 50:
                alloc = ALLOC_HIGH
            else:
                alloc = ALLOC_MED

            price = cur_bar['close']
            invest_amount = cash * alloc
            qty = int(invest_amount / price)
            if qty <= 0:
                continue
            cost = price * qty * (1 + COMMISSION)
            if cost > cash:
                qty = int(cash * 0.95 / price)
                if qty <= 0:
                    continue
                cost = price * qty * (1 + COMMISSION)

            cash -= cost
            positions[code] = {
                'entry_price': price, 'qty': qty, 'partial_sold': False,
                'original_qty': qty, 'entry_time': str(ts),
            }

            sig = stock_analysis[code]['entry_signal']
            events.append(
                f"  {ts_dt.strftime('%H:%M')} 🔵 {info['name']} 매수 {qty}주 @{price:,} "
                f"(투자금 {price*qty:,.0f}원={alloc*100:.0f}%) "
                f"끼{ki_score:.0f} {sig.method} conf={confidence:.2f} vol×{vol_ratio:.1f}"
            )

    # 장마감 잔여 정리
    for code in list(positions.keys()):
        pos = positions[code]
        last = intraday[intraday['code'] == code].sort_values('datetime').iloc[-1]
        cur = last['close']
        pnl_pct = (cur - pos['entry_price']) / pos['entry_price'] * 100
        pnl_amt = (cur - pos['entry_price']) * pos['qty']
        pnl_amt -= cur * pos['qty'] * (TAX + COMMISSION)
        cash += cur * pos['qty'] * (1 - TAX - COMMISSION)

        info = STOCKS[code]
        all_trades.append({
            'code': code, 'name': info['name'], 'theme': info['theme'],
            'entry': pos['entry_price'], 'exit': cur,
            'qty': pos['qty'], 'pnl': pnl_amt, 'pnl_pct': pnl_pct,
            'reason': '장마감', 'time': str(last['datetime']),
            'invested': pos['entry_price'] * pos['original_qty'],
        })
        emoji = "🔴" if pnl_amt < 0 else "🟢"
        events.append(f"  15:30 {emoji} {info['name']} 장마감청산 @{cur:,} ({pnl_pct:+.2f}%)")

    # ═══ 결과 ═══
    final = cash
    total_return = (final - INIT_CAPITAL) / INIT_CAPITAL * 100
    total_pnl = final - INIT_CAPITAL
    wins = [t for t in all_trades if t['pnl'] > 0]
    losses = [t for t in all_trades if t['pnl'] <= 0]
    wr = len(wins) / len(all_trades) * 100 if all_trades else 0

    print("\n" + "=" * 80)
    print("  홍인기 전략 집중투자 시뮬레이션 - 2026년 2월 12일")
    print("=" * 80)

    print(f"\n  ── 설정 ──")
    print(f"  자본금: {INIT_CAPITAL:,}원")
    print(f"  포지션: 확신 {ALLOC_HIGH*100:.0f}% / 보통 {ALLOC_MED*100:.0f}% | 최대 {MAX_POSITIONS}종목")
    print(f"  진입: vol≥{VOL_THRESHOLD}x | 9:05~11:30 | 재진입={'허용' if ALLOW_REENTRY else '불가'}")
    print(f"  청산: SL -4% | TP +5% (70% 분할) | 본전컷 | 패턴감지")

    print(f"\n  ── 확신도 순위 (매수가능 {len(buyable)}종목) ──")
    for i, (code, a) in enumerate(ranked):
        sig = a['entry_signal']
        star = " ★" if a['is_leader'] else ""
        alloc_label = f"{ALLOC_HIGH*100:.0f}%" if sig.confidence >= 0.7 and a['ki'].score >= 50 else f"{ALLOC_MED*100:.0f}%"
        print(
            f"  #{i+1:2d} {STOCKS[code]['name']:>10s}{star}: "
            f"score={a['score']:.3f} conf={sig.confidence:.2f} 끼={a['ki'].score:5.1f} "
            f"→ 배분 {alloc_label}"
        )

    print(f"\n  ── 장중 이벤트 로그 ──")
    for e in events:
        print(e)

    print(f"\n  ── 오늘 성적 ──")
    print(f"  최종자산:    {final:>12,.0f}원")
    print(f"  총수익률:    {total_return:>+11.2f}%")
    print(f"  총손익:      {total_pnl:>+12,.0f}원")
    print(f"  거래 수:     {len(all_trades)}건 (승 {len(wins)} / 패 {len(losses)})")
    print(f"  승률:        {wr:.1f}%")

    if all_trades:
        print(f"\n  ── 거래 상세 ──")
        for t in all_trades:
            emoji = "🟢" if t['pnl'] > 0 else "🔴"
            invested = t.get('invested', 0)
            print(
                f"  {emoji} {t['name']:>10s}[{t['theme']:4s}] "
                f"{t['entry']:>10,}→{t['exit']:>10,} ({t['pnl_pct']:+.2f}%) "
                f"투자{invested:>10,.0f} | {t['pnl']:>+10,.0f}원 [{t['reason']}]"
            )

        theme_pnl = defaultdict(lambda: {'cnt': 0, 'pnl': 0})
        for t in all_trades:
            theme_pnl[t['theme']]['cnt'] += 1
            theme_pnl[t['theme']]['pnl'] += t['pnl']

        print(f"\n  ── 테마별 손익 ──")
        for theme, st in sorted(theme_pnl.items(), key=lambda x: x[1]['pnl'], reverse=True):
            print(f"    {theme:>8s}: {st['cnt']}건 | {st['pnl']:>+10,.0f}원")

    # ── 보수적 대비 비교 ──
    print(f"\n  ── 집중투자 vs 분산투자 비교 ──")
    print(f"  {'':15s} {'집중투자':>12s}  {'분산투자':>12s}")
    print(f"  {'포지션 크기':15s} {'50%/30%':>12s}  {'15%/6%/3%':>12s}")
    print(f"  {'최대 종목':15s} {'2개':>12s}  {'5개':>12s}")
    print(f"  {'일수익률':15s} {total_return:>+11.2f}%  {'+0.11%':>12s}")
    print(f"  {'일수익금':15s} {total_pnl:>+11,.0f}원  {'+10,963원':>12s}")

    # ── 복리 시뮬레이션 ──
    if total_return > 0:
        daily_r = total_return / 100
        monthly = INIT_CAPITAL * ((1 + daily_r) ** 20 - 1)
        yearly = INIT_CAPITAL * ((1 + daily_r) ** 240 - 1)
        print(f"\n  ── 복리 시뮬레이션 (일 {total_return:+.2f}% 유지 가정) ──")
        print(f"  월수익 (20일):  {monthly:>+12,.0f}원 ({monthly/INIT_CAPITAL*100:+.1f}%)")
        print(f"  연수익 (240일): {yearly:>+12,.0f}원 ({yearly/INIT_CAPITAL*100:+.1f}%)")
        print(f"  1년후 자산:     {INIT_CAPITAL + yearly:>12,.0f}원")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
