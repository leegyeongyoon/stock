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

// 1000만원 실투자 시뮬레이션 결과 v6.2 (품질 점수 기반 + OpenAI 분석)
const REAL_CAPITAL = {
  version: "v6.2",
  maxPositions: 3,
  skipTop: 1,          // TOP1 스킵
  enterTop: "2-5",     // TOP2-5 진입
  minDailyChange: 6,   // 등락률 6%+ 필터
  initial: 10_000_000,
  final: 11_950_390,
  pnl: 1_950_390,
  returnPct: 19.50,
  commission: 170_039,
  trades: 20,
  winRate: 80.0,
  wins: 16,
  losses: 4,
  mdd: -0.21,
  monthlyPct: 21.45,
  monthlyKrw: 2_145_429,
  skippedLowChange: 41,  // 등락률 부족 스킵
  skippedMaxPos: 0,
  skipped7079: 10,       // 70-79점 스킵
  breakout: { trades: 20, wins: 16, pnl: 1_960_481 },
  pullback: { trades: 0, wins: 0, pnl: 0 },
  // v6.2 품질 점수 시스템
  qualityScore: {
    minScore: 60,        // 최소 60점 진입
    skipRange: "70-79",  // 70-79점 스킵 (손실 구간)
    avgScore: 74.5,      // 평균 진입 점수
    byRange: [
      { range: "90-99", trades: 3, winRate: 66.7, pnl: 449_155 },
      { range: "80-89", trades: 7, winRate: 85.7, pnl: 963_666 },
      { range: "60-69", trades: 10, winRate: 80.0, pnl: 547_661 },
    ],
  },
  // 오버나잇 홀딩 통계
  overnight: {
    total: 10,         // 오버나잇 시도
    success: 10,       // 성공 (갭하락 없음)
    gapStop: 0,        // 갭하락 손절
    gapStopPnl: 0,     // 갭하락 손익
    minScore: 60,      // 홀딩 최소 점수
    gapStopPct: -3,    // 갭하락 손절선
  },
  daily: [
    { date: "01/13", pnl: 0, capital: 9_999_251 },
    { date: "01/14", pnl: 213_707, capital: 10_212_958 },
    { date: "01/15", pnl: 0, capital: 10_212_958 },
    { date: "01/16", pnl: 0, capital: 10_212_958 },
    { date: "01/19", pnl: 0, capital: 10_212_958 },
    { date: "01/20", pnl: 0, capital: 10_212_958 },
    { date: "01/21", pnl: 397_110, capital: 10_609_306 },
    { date: "01/22", pnl: 0, capital: 10_608_139 },
    { date: "01/23", pnl: 97_904, capital: 10_705_464 },
    { date: "01/26", pnl: 212_476, capital: 10_917_227 },
    { date: "01/27", pnl: 283_693, capital: 11_199_692 },
    { date: "01/28", pnl: -22_348, capital: 11_176_172 },
    { date: "01/29", pnl: 109_637, capital: 11_285_046 },
    { date: "01/30", pnl: -20_291, capital: 11_263_909 },
    { date: "02/02", pnl: 0, capital: 11_263_909 },
    { date: "02/03", pnl: 0, capital: 11_262_644 },
    { date: "02/04", pnl: 219_148, capital: 11_481_792 },
    { date: "02/05", pnl: 0, capital: 11_481_792 },
    { date: "02/06", pnl: 0, capital: 11_481_792 },
    { date: "02/09", pnl: 0, capital: 11_481_792 },
    { date: "02/10", pnl: 0, capital: 11_480_945 },
    { date: "02/11", pnl: 469_446, capital: 11_950_390 },
    { date: "02/12", pnl: 0, capital: 11_950_390 },
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
          <span className="text-[9px] text-slate-500 font-normal">40일 (12/16~02/12)</span>
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
            <div className="text-[10px] text-emerald-400 font-medium">실투자 시뮬레이션 v6.2 (품질 점수)</div>
            <div className="text-xl font-bold font-mono text-green-400">+{r.returnPct.toFixed(2)}%</div>
            <div className="space-y-0.5 text-[10px] text-slate-400">
              <div>{r.trades}건 거래 (WR <span className="text-green-400 font-medium">{r.winRate}%</span>), 건당 +{Math.round(r.pnl/r.trades).toLocaleString()}원</div>
              <div>1000만원 <span className="text-emerald-400">실제 자금 운용</span></div>
              <div>품질{r.qualityScore.minScore}점+ + {r.qualityScore.skipRange}점 스킵</div>
            </div>
          </div>
        </div>

        {/* v6.2 품질 점수 시스템 */}
        <div className="p-2 rounded bg-violet-500/5 border border-violet-500/15">
          <div className="text-[10px] text-violet-400 font-medium mb-1">v6.2 품질 점수 시스템 (OpenAI 분석 기반)</div>
          <div className="grid grid-cols-4 gap-2 text-[10px]">
            <div className="text-center">
              <div className="text-slate-500">최소 점수</div>
              <div className="text-green-400 font-mono font-medium">{r.qualityScore.minScore}점+</div>
              <div className="text-slate-600">100점 만점</div>
            </div>
            <div className="text-center">
              <div className="text-slate-500">손실구간 스킵</div>
              <div className="text-red-400 font-mono font-medium">{r.qualityScore.skipRange}점</div>
              <div className="text-slate-600">{r.skipped7079}건 필터</div>
            </div>
            <div className="text-center">
              <div className="text-slate-500">평균 진입점수</div>
              <div className="text-blue-400 font-mono font-medium">{r.qualityScore.avgScore}점</div>
              <div className="text-slate-600">고품질 진입</div>
            </div>
            <div className="text-center">
              <div className="text-slate-500">건당 수익</div>
              <div className="text-emerald-400 font-mono font-medium">+{Math.round(r.pnl/r.trades).toLocaleString()}원</div>
              <div className="text-slate-600">9.8만원/건</div>
            </div>
          </div>
        </div>

        {/* 품질 점수대별 성과 */}
        <div className="p-2 rounded bg-slate-900/40">
          <div className="text-[10px] text-slate-400 font-medium mb-1">품질 점수대별 성과</div>
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            {r.qualityScore.byRange.map((item) => (
              <div key={item.range} className="text-center p-1.5 rounded bg-slate-800/50">
                <div className="text-slate-500">{item.range}점</div>
                <div className="text-green-400 font-mono font-medium">WR {item.winRate}%</div>
                <div className="text-emerald-400 font-mono text-[9px]">+{fmtKRW(item.pnl)}원</div>
              </div>
            ))}
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
        <div className="grid grid-cols-3 gap-2 text-[10px]">
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
            <div className="text-slate-500 font-medium">오버나잇 홀딩</div>
            <div className="flex justify-between text-slate-300">
              <span>시도/성공</span>
              <span className="text-blue-400 font-mono">{r.overnight.total}/{r.overnight.success}건</span>
            </div>
            <div className="flex justify-between text-slate-300">
              <span>갭하락손절</span>
              <span className={`font-mono ${r.overnight.gapStopPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                {r.overnight.gapStop}건 ({r.overnight.gapStopPnl >= 0 ? "+" : ""}{fmtKRW(r.overnight.gapStopPnl)}원)
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
              <span>스킵</span>
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

        {/* v6.2 수익 요약 */}
        <div className="flex gap-1.5 p-2 rounded bg-emerald-500/5 border border-emerald-500/10">
          <Info size={12} className="text-emerald-400 shrink-0 mt-0.5" />
          <div className="text-[10px] text-slate-400 leading-relaxed space-y-1">
            <p>
              v6.2 수익: <span className="text-green-400 font-medium">+{fmtKRW(r.pnl)}원(+{r.returnPct.toFixed(2)}%/40일)</span> →
              월 <span className="text-green-400">+{r.monthlyPct.toFixed(1)}%</span>, 연 환산 약 <span className="text-green-400">{(r.monthlyPct * 12).toFixed(0)}%</span>.
            </p>
            <p className="text-slate-500">
              v6.2 핵심: ① 품질점수 {r.qualityScore.minScore}점+ 진입 ② {r.qualityScore.skipRange}점 손실구간 스킵 ③ 승률 {r.winRate}% 달성
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
            <div className="text-[11px] text-violet-400 font-medium">v6.2 품질 점수 시스템 (OpenAI 분석)</div>
            <div>품질점수 = 시총(15) + 기관(15) + 등락률(20) + 오전상승(20) + 종가강도(20) + 리더순위(10)</div>
            <div>진입: <span className="text-emerald-400">{r.qualityScore.minScore}점+</span> / 스킵: <span className="text-red-400">{r.qualityScore.skipRange}점</span> (일관된 손실)</div>
            <div>SL -4% / TP +5% (70% 분매) / 본전컷</div>
          </div>
          <div className="p-2 rounded bg-slate-900/40 space-y-1">
            <div className="text-[11px] text-violet-400 font-medium">오버나잇 홀딩</div>
            <div>필수: 장마감 수익 ≥ 0% + 고점패턴 미감지</div>
            <div>점수: 끼(30) + 대장주(20) + 일봉자리(20) + D+1후보(15) + 오후거래량(15)</div>
            <div>홀딩: 총점 ≥ {r.overnight.minScore}점 / 갭하락 {r.overnight.gapStopPct}% 손절</div>
          </div>
          <div className="p-2 rounded bg-slate-900/40 space-y-1">
            <div className="text-[11px] text-violet-400 font-medium">시뮬레이션 설정</div>
            <div>기간: 40영업일 (2025-12-16 ~ 2026-02-12)</div>
            <div>초기자금: 1,000만원 / 거래비용: 수수료 0.015%×2 + 세금 0.23%</div>
          </div>
        </div>
      </div>
    </div>
  );
}
