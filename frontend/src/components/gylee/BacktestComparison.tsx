"use client";

import { FlaskConical, ArrowRight } from "lucide-react";

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

export default function BacktestComparison() {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
        <FlaskConical size={16} className="text-emerald-400" />
        20일 백테스트 검증 (2026-01-16 ~ 02-12)
      </h3>

      {/* 메인 비교 테이블 */}
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
                className={`border-b border-slate-700/50 ${
                  row.highlight
                    ? "bg-emerald-500/10"
                    : ""
                }`}
              >
                <td className="py-2">
                  <div className="flex items-center gap-1">
                    {idx > 0 && idx < BACKTEST_DATA.length && (
                      <ArrowRight size={10} className="text-slate-600 shrink-0" />
                    )}
                    <span className={row.highlight ? "text-emerald-400 font-medium" : "text-slate-300"}>
                      {row.label}
                    </span>
                  </div>
                </td>
                <td className="text-right text-slate-400 font-mono">{row.trades}건</td>
                <td className={`text-right font-mono ${
                  row.winRate >= 55 ? "text-green-400" : row.winRate >= 50 ? "text-yellow-400" : "text-red-400"
                }`}>
                  {row.winRate}%
                </td>
                <td className={`text-right font-mono font-medium ${
                  row.total.startsWith("+") ? "text-green-400" : "text-red-400"
                }`}>
                  {row.total}
                </td>
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
              }`}>
                {row.total}
              </div>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-slate-500 mt-2">
          나쁜 눌림 48건 제거 → 전체 수익 +84.61% → +96.83% (+12.22% 개선)
        </p>
      </div>
    </div>
  );
}
