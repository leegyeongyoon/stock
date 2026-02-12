import { CalendarPlus } from "lucide-react";
import type { DPlusCandidate } from "@/lib/api";

const DDAY_STYLES: Record<string, string> = {
  "D+1": "bg-blue-500/20 text-blue-400 border-blue-500/30",
  "D+2": "bg-purple-500/20 text-purple-400 border-purple-500/30",
};

function formatTradingValue(value: number): string {
  if (value >= 1_0000_0000) return `${(value / 1_0000_0000).toFixed(1)}조`;
  if (value >= 1_0000) return `${(value / 1_0000).toFixed(0)}억`;
  return `${value.toLocaleString()}만`;
}

export default function DPlusCandidates({ candidates }: { candidates: DPlusCandidate[] | undefined }) {
  if (!candidates || candidates.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <CalendarPlus size={16} className="text-blue-400" />
          D+ 후보 종목
        </h3>
        <p className="text-sm text-slate-500">D+ 후보 종목이 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
        <CalendarPlus size={16} className="text-blue-400" />
        D+ 후보 종목
        <span className="text-xs text-slate-500 font-normal ml-1">({candidates.length}종목)</span>
      </h3>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-500 text-xs border-b border-slate-700">
              <th className="text-center pb-2 pr-3">D+</th>
              <th className="text-left pb-2 pr-3">종목</th>
              <th className="text-right pb-2 pr-3">전일 등락률</th>
              <th className="text-right pb-2 pr-3">전일 거래대금</th>
              <th className="text-left pb-2 pr-3">일봉자리</th>
              <th className="text-left pb-2">사유</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => {
              const ddayStyle = DDAY_STYLES[candidate.d_day] || DDAY_STYLES["D+1"];

              return (
                <tr
                  key={candidate.code}
                  className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors"
                >
                  <td className="py-2.5 pr-3 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium border ${ddayStyle}`}>
                      {candidate.d_day}
                    </span>
                  </td>
                  <td className="py-2.5 pr-3">
                    <span className="text-white font-medium">{candidate.name}</span>
                    <span className="text-[10px] text-slate-500 font-mono ml-2">{candidate.code}</span>
                  </td>
                  <td className={`py-2.5 pr-3 text-right font-mono text-xs ${
                    candidate.prev_change_rate >= 0 ? "text-red-400" : "text-blue-400"
                  }`}>
                    {candidate.prev_change_rate >= 0 ? "+" : ""}
                    {candidate.prev_change_rate.toFixed(2)}%
                  </td>
                  <td className="py-2.5 pr-3 text-right text-white font-mono text-xs">
                    {formatTradingValue(candidate.prev_trading_value)}
                  </td>
                  <td className="py-2.5 pr-3 text-xs text-slate-400">{candidate.daily_position}</td>
                  <td className="py-2.5 text-xs text-slate-400 max-w-[200px] truncate">{candidate.reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
