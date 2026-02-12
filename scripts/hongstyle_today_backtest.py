"""홍인기 전략 실전 시뮬레이션 - 오늘(2026-02-12) 핫테마 기준

실제 엔진 컴포넌트 사용:
- DailyChartAnalyzer: 끼 점수 + 일봉 자리 분류
- SignalGenerator: 진입/청산 시그널 생성
- PatternDetector: 위험 패턴 감지
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

        icon = "✅" if entry_signal.action == "buy" else "⏸️" if entry_signal.action == "wait" else "❌"
        leader_mark = " ★" if is_leader else ""
        logger.info(
            f"  {icon} {info['name']:>10s}{leader_mark}: "
            f"끼={ki.score:5.1f} 자리={position.position_type:6s} → "
            f"{entry_signal.action}({entry_signal.method}) conf={entry_signal.confidence:.2f}"
        )

    buyable = {
        code: a for code, a in stock_analysis.items()
        if a['entry_signal'].action == 'buy' and a['entry_signal'].confidence >= 0.5
    }
    logger.info(f"\n매수 가능 종목: {len(buyable)}개")
    for code, a in buyable.items():
        sig = a['entry_signal']
        logger.info(f"  {STOCKS[code]['name']}: {sig.method} conf={sig.confidence:.2f} - {sig.reason}")

    # ── 장중 시뮬레이션 ──
    logger.info("\n=== 장중 시뮬레이션 시작 ===")
    cash = INIT_CAPITAL
    positions = {}
    all_trades = []
    events = []

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
                    })
                    emoji = "🔴" if pnl_amt < 0 else "🟢"
                    events.append(
                        f"  {ts_dt.strftime('%H:%M')} {emoji} {info['name']} 전량매도 "
                        f"{pos['qty']}주 @{current_price:,} ({pnl_pct:+.2f}%) [{exit_sig.reason}]"
                    )
                    del positions[code]
                continue

            # ── 신규 진입 ──
            if code not in buyable or code in positions or len(positions) >= 5:
                continue
            if h < 9 or (h == 9 and m < 10) or h >= 11:
                continue

            stock_bars = intraday[
                (intraday['code'] == code) & (intraday['datetime'] <= ts)
            ].sort_values('datetime')

            if len(stock_bars) < 5:
                continue

            cur_bar = stock_bars.iloc[-1]
            prev_bars = stock_bars.iloc[-6:-1]

            if cur_bar['close'] <= cur_bar['open']:
                continue
            avg_vol = prev_bars['volume'].mean()
            if avg_vol <= 0:
                continue
            vol_ratio = cur_bar['volume'] / avg_vol
            if vol_ratio < 1.5:
                continue
            if cur_bar['close'] <= prev_bars['high'].max():
                continue

            patterns = pattern_detector.detect_all_patterns(
                minute_bars=stock_bars,
                daily_bars=stock_analysis[code]['daily_df'],
            )
            high_severity = [p for p in patterns if p.severity == 'high']
            if high_severity:
                continue

            ki_score = stock_analysis[code]['ki'].score
            confidence = stock_analysis[code]['entry_signal'].confidence

            if ki_score >= 60 and confidence >= 0.7:
                alloc = 0.15
            elif ki_score >= 40:
                alloc = 0.06
            else:
                alloc = 0.03

            price = cur_bar['close']
            qty = int(cash * alloc / price)
            if qty <= 0:
                continue
            cost = price * qty * (1 + COMMISSION)
            if cost > cash:
                continue

            cash -= cost
            positions[code] = {
                'entry_price': price, 'qty': qty, 'partial_sold': False,
                'original_qty': qty, 'entry_time': str(ts),
            }

            sig = stock_analysis[code]['entry_signal']
            events.append(
                f"  {ts_dt.strftime('%H:%M')} 🔵 {info['name']} 매수 {qty}주 @{price:,} "
                f"(끼{ki_score:.0f}, {sig.method}, conf={confidence:.2f}, vol×{vol_ratio:.1f})"
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
    print("  홍인기 전략 실전 시뮬레이션 - 2026년 2월 12일 (오늘)")
    print("=" * 80)
    print(f"\n  핫테마: 건설, 홈쇼핑, 은행, 두나무, 손해보험, IT, 백화점, 통신")
    print(f"  대상: 테마별 탑3 (18종목) → 매수 가능 {len(buyable)}종목")
    print(f"  자본금: {INIT_CAPITAL:,}원")
    print(f"  규칙: SL -4% | TP +5% (70% 분할매도) | 본전컷 | 패턴감지 청산")

    print(f"\n  ── 종목 분석 결과 ──")
    for code, a in stock_analysis.items():
        info = STOCKS[code]
        sig = a['entry_signal']
        icon = "✅" if code in buyable else "⏸️" if sig.action == 'wait' else "❌"
        leader = " ★" if a['is_leader'] else ""
        print(
            f"  {icon} {info['name']:>10s}{leader}: "
            f"끼={a['ki'].score:5.1f} 자리={a['position'].position_type:6s} → "
            f"{sig.action}({sig.method}) conf={sig.confidence:.2f}"
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
            print(
                f"  {emoji} {t['name']:>10s}[{t['theme']:4s}] "
                f"{t['entry']:>10,}→{t['exit']:>10,} ({t['pnl_pct']:+.2f}%) "
                f"{t['reason']:20s} | {t['pnl']:>+10,.0f}원"
            )

        theme_pnl = defaultdict(lambda: {'cnt': 0, 'pnl': 0})
        for t in all_trades:
            theme_pnl[t['theme']]['cnt'] += 1
            theme_pnl[t['theme']]['pnl'] += t['pnl']

        print(f"\n  ── 테마별 손익 ──")
        for theme, st in sorted(theme_pnl.items(), key=lambda x: x[1]['pnl'], reverse=True):
            print(f"    {theme:>8s}: {st['cnt']}건 | {st['pnl']:>+10,.0f}원")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
