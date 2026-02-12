"use client";

import { FlaskConical, ArrowRight, Wallet, Cpu, Info } from "lucide-react";
import { useState } from "react";

interface BacktestRow {
  label: string;
  trades: number;
  winRate: number;
  total: string;
  highlight?: boolean;
}

const BACKTEST_DATA: BacktestRow[] = [
  { label: "무필터 (원본)", trades: 250, winRate: 42.0, total: "-151.41%" },
  { label: "시총 5000억+", trades: 298, winRate: 51.7, total: "+14.89%" },
  { label: "+ 기관순매수 > 0", trades: 309, winRate: 53.1, total: "+58.22%" },
  { label: "+ 기관 50~200억", trades: 255, winRate: 56.9, total: "+84.61%" },
  { label: "+ 눌림 95%깊이 (최종)", trades: 207, winRate: 60.4, total: "+96.83%", highlight: true },
];

const PULLBACK_DATA = [
  { label: "기존 눌림 (98%)", trades: 53, winRate: 41.5, total: "-10.99%" },
  { label: "95%깊이+오전거래량", trades: 5, winRate: 40.0, total: "+1.23%" },
];

// 1000만원 실투자 시뮬레이션 결과
const REAL_CAPITAL = {
  initial: 10_000_000,
  final: 10_708_865,
  pnl: 708_865,
  returnPct: 7.09,
  commission: 345_823,
  trades: 37,
  winRate: 51.4,
  wins: 19,
  losses: 18,
  mdd: -3.85,
  monthlyPct: 7.80,
  monthlyKrw: 779_752,
  skippedMaxPos: 27,
  breakout: { trades: 34, wins: 18, pnl: 714_856 },
  pullback: { trades: 3, wins: 1, pnl: 15_021 },
  daily: [
    { date: "01/16", pnl: 6815, capital: 10_005_693 },
    { date: "01/19", pnl: -123_491, capital: 9_881_237 },
    { date: "01/20", pnl: 498_236, capital: 10_378_371 },
    { date: "01/21", pnl: 143_536, capital: 10_520_746 },
    { date: "01/22", pnl: -337_313, capital: 10_182_270 },
    { date: "01/23", pnl: 163_455, capital: 10_344_617 },
    { date: "01/26", pnl: 137_006, capital: 10_480_464 },
    { date: "01/27", pnl: -322_997, capital: 10_156_289 },
    { date: "01/28", pnl: 28_845, capital: 10_184_152 },
    { date: "01/29", pnl: 20_863, capital: 10_203_871 },
    { date: "01/30", pnl: -87_196, capital: 10_115_530 },
    { date: "02/02", pnl: 0, capital: 10_115_530 },
    { date: "02/03", pnl: 440_611, capital: 10_555_005 },
    { date: "02/04", pnl: 114_486, capital: 10_668_474 },
    { date: "02/05", pnl: -285_083, capital: 10_382_195 },
    { date: "02/06", pnl: -18_634, capital: 10_362_406 },
    { date: "02/09", pnl: 5_311, capital: 10_366_940 },
    { date: "02/10", pnl: 56_215, capital: 10_422_000 },
    { date: "02/11", pnl: 71_146, capital: 10_491_976 },
    { date: "02/12", pnl: 218_067, capital: 10_708_865 },
  ],
};

function fmtKRW(v: number): string {
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(1)}만`;
  return v.toLocaleString("ko-KR");
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color: string }) {
  return (
    <div className="bg-slate-900/50 rounded-lg p-2 text-center">
      <div className="text-[9px] text-slate-500 mb-0.5">{label}</div>
      <div className={`text-sm font-bold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[9px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export default function BacktestComparison() {
  const [showDaily, setShowDaily] = useState(false);
  const r = REAL_CAPITAL;
  const maxCap = Math.max(...r.daily.map((d) => d.capital));
  const minCap = Math.min(...r.daily.map((d) => d.capital));

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-4">
      {/* 백테스트 vs 실투자 비교 */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Wallet size={16} className="text-amber-400" />
          백테스트 vs 실투자 시뮬레이션
          <span className="text-[9px] text-slate-500 font-normal">20일 (01/16~02/12)</span>
        </h3>

        {/* Before → After 비교 */}
        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-700/50 space-y-2">
            <div className="text-[10px] text-slate-500 font-medium">백테스트 결과 (이론)</div>
            <div className="text-xl font-bold font-mono text-green-400">+96.83%</div>
            <div className="space-y-0.5 text-[10px] text-slate-400">
              <div>207건 거래, WR 60.4%</div>
              <div>개별 수익률 <span className="text-yellow-400">단순 합산</span></div>
              <div>포지션 제한 없음, 비용 제외</div>
            </div>
          </div>
          <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 space-y-2">
            <div className="text-[10px] text-emerald-400 font-medium">실투자 시뮬레이션 (현실)</div>
            <div className="text-xl font-bold font-mono text-green-400">+7.09%</div>
            <div className="space-y-0.5 text-[10px] text-slate-400">
              <div>37건 거래 (27건 스킵), WR 51.4%</div>
              <div>1000만원 <span className="text-emerald-400">실제 자금 운용</span></div>
              <div>최대2종목 + 비용34.6만 반영</div>
            </div>
          </div>
        </div>

        {/* 왜 차이나는지 */}
        <div className="p-2 rounded bg-orange-500/5 border border-orange-500/15">
          <div className="text-[10px] text-orange-400 font-medium mb-1">왜 +96% → +7%로 줄었나?</div>
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <div className="text-center">
              <div className="text-slate-500">동시보유 제한</div>
              <div className="text-yellow-400 font-mono font-medium">-27건 스킵</div>
              <div className="text-slate-600">최대 2종목</div>
            </div>
            <div className="text-center">
              <div className="text-slate-500">포지션 사이징</div>
              <div className="text-yellow-400 font-mono font-medium">30~50%</div>
              <div className="text-slate-600">전액투자 아님</div>
            </div>
            <div className="text-center">
              <div className="text-slate-500">거래비용</div>
              <div className="text-red-400 font-mono font-medium">-34.6만원</div>
              <div className="text-slate-600">수수료+세금</div>
            </div>
          </div>
        </div>

        {/* 핵심 지표 */}
        <div className="grid grid-cols-4 gap-2">
          <StatCard label="총 수익" value={`+${fmtKRW(r.pnl)}원`} sub={`${r.returnPct.toFixed(1)}%`} color="text-green-400" />
          <StatCard label="승률" value={`${r.winRate}%`} sub={`${r.wins}승 ${r.losses}패`} color={r.winRate >= 50 ? "text-green-400" : "text-yellow-400"} />
          <StatCard label="MDD" value={`${r.mdd}%`} sub="최대 낙폭" color="text-red-400" />
          <StatCard label="월 환산" value={`+${fmtKRW(r.monthlyKrw)}원`} sub={`${r.monthlyPct.toFixed(1)}%/월`} color="text-blue-400" />
        </div>

        {/* 자산 추이 바 */}
        <div className="space-y-1">
          <div className="flex justify-between text-[9px] text-slate-500">
            <span>일별 자산 추이</span>
            <span>{fmtKRW(r.initial)}원 → {fmtKRW(r.final)}원</span>
          </div>
          <div className="flex gap-0.5 h-8 items-end">
            {r.daily.map((d) => {
              const range = maxCap - minCap || 1;
              const h = ((d.capital - minCap) / range) * 100;
              return (
                <div
                  key={d.date}
                  className={`flex-1 rounded-t-sm transition-all ${d.pnl >= 0 ? "bg-green-500/60" : "bg-red-500/60"}`}
                  style={{ height: `${Math.max(h, 8)}%` }}
                  title={`${d.date}: ${d.pnl >= 0 ? "+" : ""}${d.pnl.toLocaleString()}원 (${d.capital.toLocaleString()}원)`}
                />
              );
            })}
          </div>
        </div>

        {/* 상세 내역 */}
        <div className="grid grid-cols-2 gap-2 text-[10px]">
          <div className="space-y-1">
            <div className="text-slate-500 font-medium">매매 방법</div>
            <div className="flex justify-between text-slate-300">
              <span>돌파 {r.breakout.trades}건</span>
              <span className="text-green-400 font-mono">+{fmtKRW(r.breakout.pnl)}원</span>
            </div>
            <div className="flex justify-between text-slate-300">
              <span>눌림 {r.pullback.trades}건</span>
              <span className={`font-mono ${r.pullback.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                {r.pullback.pnl >= 0 ? "+" : ""}{fmtKRW(r.pullback.pnl)}원
              </span>
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-500 font-medium">비용 & 제약</div>
            <div className="flex justify-between text-slate-300">
              <span>거래비용</span>
              <span className="text-red-400 font-mono">-{fmtKRW(r.commission)}원</span>
            </div>
            <div className="flex justify-between text-slate-300">
              <span>보유초과 스킵</span>
              <span className="text-yellow-400 font-mono">{r.skippedMaxPos}건</span>
            </div>
          </div>
        </div>

        {/* 일별 토글 */}
        <button
          onClick={() => setShowDaily((v) => !v)}
          className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
        >
          {showDaily ? "▲ 일별 접기" : "▼ 일별 상세 보기"}
        </button>
        {showDaily && (
          <div className="max-h-48 overflow-y-auto">
            <table className="w-full text-[10px]">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-1">날짜</th>
                  <th className="text-right py-1">PnL</th>
                  <th className="text-right py-1">자산</th>
                </tr>
              </thead>
              <tbody>
                {r.daily.map((d) => (
                  <tr key={d.date} className="border-b border-slate-700/30">
                    <td className="py-1 text-slate-400 font-mono">{d.date}</td>
                    <td className={`py-1 text-right font-mono ${d.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {d.pnl >= 0 ? "+" : ""}{d.pnl.toLocaleString()}
                    </td>
                    <td className="py-1 text-right text-slate-300 font-mono">{d.capital.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 현실 수익 요약 + 개선 포인트 */}
        <div className="flex gap-1.5 p-2 rounded bg-blue-500/5 border border-blue-500/10">
          <Info size={12} className="text-blue-400 shrink-0 mt-0.5" />
          <div className="text-[10px] text-slate-400 leading-relaxed space-y-1">
            <p>
              현실 수익: <span className="text-green-400 font-medium">+70.9만원(+7.09%/20일)</span> →
              월 <span className="text-green-400">+7.8%</span>, 연 환산 약 <span className="text-green-400">94%</span>.
            </p>
            <p className="text-slate-500">
              개선 여지: ① 동시보유 3~4종목 확대 (27건 기회 손실 감소) ② TP +5% 실현율 개선 (현재 장마감 청산 위주) ③ 눌림매매 비중 확대 (현재 3건)
            </p>
          </div>
        </div>
      </div>

      {/* 구분선 */}
      <div className="border-t border-slate-700/50" />

      {/* 필터 검증 백테스트 */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <FlaskConical size={16} className="text-emerald-400" />
          필터 검증 백테스트
          <span className="text-[9px] text-slate-500 font-normal">개별 거래 수익률 합계</span>
        </h3>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700 text-slate-500">
                <th className="text-left py-2 font-medium">필터 조건</th>
                <th className="text-right py-2 font-medium">거래수</th>
                <th className="text-right py-2 font-medium">승률</th>
                <th className="text-right py-2 font-medium">합계</th>
              </tr>
            </thead>
            <tbody>
              {BACKTEST_DATA.map((row, idx) => (
                <tr
                  key={idx}
                  className={`border-b border-slate-700/50 ${row.highlight ? "bg-emerald-500/10" : ""}`}
                >
                  <td className="py-2">
                    <div className="flex items-center gap-1">
                      {idx > 0 && <ArrowRight size={10} className="text-slate-600 shrink-0" />}
                      <span className={row.highlight ? "text-emerald-400 font-medium" : "text-slate-300"}>
                        {row.label}
                      </span>
                    </div>
                  </td>
                  <td className="text-right text-slate-400 font-mono">{row.trades}건</td>
                  <td className={`text-right font-mono ${
                    row.winRate >= 55 ? "text-green-400" : row.winRate >= 50 ? "text-yellow-400" : "text-red-400"
                  }`}>{row.winRate}%</td>
                  <td className={`text-right font-mono font-medium ${
                    row.total.startsWith("+") ? "text-green-400" : "text-red-400"
                  }`}>{row.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 눌림 최적화 */}
        <div className="pt-2 border-t border-slate-700/50">
          <h4 className="text-[11px] text-slate-400 font-medium mb-2">눌림매매 최적화</h4>
          <div className="grid grid-cols-2 gap-3">
            {PULLBACK_DATA.map((row, idx) => (
              <div
                key={idx}
                className={`p-2.5 rounded-lg text-center ${
                  idx === 1 ? "bg-emerald-500/10 border border-emerald-500/20" : "bg-slate-900/40"
                }`}
              >
                <div className="text-[10px] text-slate-500 mb-1">{row.label}</div>
                <div className="text-xs text-slate-300">{row.trades}건 WR {row.winRate}%</div>
                <div className={`text-sm font-bold font-mono ${
                  row.total.startsWith("+") ? "text-green-400" : "text-red-400"
                }`}>{row.total}</div>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-slate-500 mt-2">
            나쁜 눌림 48건 제거 → 전체 수익 +84.61% → +96.83% (+12.22% 개선)
          </p>
        </div>
      </div>

      {/* 구분선 */}
      <div className="border-t border-slate-700/50" />

      {/* 알고리즘 방법론 */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Cpu size={16} className="text-violet-400" />
          알고리즘 방법론
        </h3>
        <div className="space-y-2 text-[10px] text-slate-400 leading-relaxed">
          <div className="p-2 rounded bg-slate-900/40 space-y-1">
            <div className="text-[11px] text-violet-400 font-medium">데이터 수집</div>
            <div>pykrx: 전일 시가총액 + 기관순매수 (KOSPI/KOSDAQ 전종목)</div>
            <div>yfinance: 5분봉 OHLCV (유니버스 종목 1개월)</div>
          </div>
          <div className="p-2 rounded bg-slate-900/40 space-y-1">
            <div className="text-[11px] text-violet-400 font-medium">시그널 생성</div>
            <div>1. 거래대금 TOP100 + 등락률 3%+ → 유니버스</div>
            <div>2. 오전 모멘텀(거래량×상승률) TOP20 → 리더</div>
            <div>3. 돌파: 5봉 고점 돌파 + 거래량 1.2배 (09:30~11:00)</div>
            <div>4. 눌림: 오전고점 95%깊이 반등 + 거래량 중간값↑ (13:00~14:30)</div>
          </div>
          <div className="p-2 rounded bg-slate-900/40 space-y-1">
            <div className="text-[11px] text-violet-400 font-medium">필터링 (3단계)</div>
            <div>시총 ≥ 5,000억 → 기관 50~200억 → 눌림 깊이+거래량 체크</div>
          </div>
          <div className="p-2 rounded bg-slate-900/40 space-y-1">
            <div className="text-[11px] text-violet-400 font-medium">실행 조건</div>
            <div>최대 2종목 동시보유 / 확신 50% · 보통 30% 배분</div>
            <div>SL -4% / TP +5% (70% 분매) / 본전컷 / 2연속 손절→당일종료</div>
          </div>
          <div className="p-2 rounded bg-slate-900/40 space-y-1">
            <div className="text-[11px] text-violet-400 font-medium">시뮬레이션 설정</div>
            <div>기간: 20영업일 (2026-01-16 ~ 02-12)</div>
            <div>초기자금: 1,000만원 / 거래비용: 수수료 0.015%×2 + 세금 0.23%</div>
            <div>장마감 시 잔여 포지션 강제 청산</div>
          </div>
        </div>
      </div>
    </div>
  );
}
