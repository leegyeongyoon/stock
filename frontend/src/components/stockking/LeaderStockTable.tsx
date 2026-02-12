import { Crown } from "lucide-react";
import type { LeaderStock } from "@/lib/api";

const GRADE_STYLES: Record<string, string> = {
  A: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  B: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  C: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  D: "bg-red-500/20 text-red-400 border-red-500/30",
};

const POSITION_STYLES: Record<string, string> = {
  "전고점돌파": "text-emerald-400",
  "신고가": "text-yellow-400",
  "빈집": "text-blue-400",
  "바닥반등": "text-orange-400",
  "해당없음": "text-slate-500",
};

function formatTradingValue(value: number): string {
  if (value >= 1_0000_0000) return `${(value / 1_0000_0000).toFixed(1)}조`;
  if (value >= 1_0000) return `${(value / 1_0000).toFixed(0)}억`;
  return `${value.toLocaleString()}만`;
}

export default function LeaderStockTable({
  stocks,
  onStockClick,
}: {
  stocks: LeaderStock[] | undefined;
  onStockClick?: (code: string, name: string) => void;
}) {
  if (!stocks || stocks.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Crown size={16} className="text-yellow-400" />
          대장주 목록
        </h3>
        <p className="text-sm text-slate-500">대장주 데이터가 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
        <Crown size={16} className="text-yellow-400" />
        대장주 목록
        <span className="text-xs text-slate-500 font-normal ml-1">({stocks.length}종목)</span>
      </h3>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-500 text-xs border-b border-slate-700">
              <th className="text-left pb-2 pr-3">종목</th>
              <th className="text-left pb-2 pr-3">섹터</th>
              <th className="text-right pb-2 pr-3">거래대금</th>
              <th className="text-right pb-2 pr-3">등락률</th>
              <th className="text-left pb-2 pr-3">일봉자리</th>
              <th className="text-right pb-2 pr-3">끼점수</th>
              <th className="text-center pb-2">등급</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((stock) => {
              const gradeStyle = GRADE_STYLES[stock.grade] || GRADE_STYLES.D;
              const positionStyle = POSITION_STYLES[stock.daily_position] || "text-slate-400";

              return (
                <tr
                  key={stock.code}
                  className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors cursor-pointer"
                  onClick={() => onStockClick?.(stock.code, stock.name)}
                >
                  <td className="py-2.5 pr-3">
                    <div className="flex items-center gap-1.5">
                      {stock.is_leader && (
                        <Crown size={12} className="text-yellow-400 flex-shrink-0" />
                      )}
                      <span className="text-white font-medium">{stock.name}</span>
                    </div>
                    <span className="text-[10px] text-slate-500 font-mono">{stock.code}</span>
                  </td>
                  <td className="py-2.5 pr-3 text-slate-400 text-xs">{stock.sector}</td>
                  <td className="py-2.5 pr-3 text-right text-white font-mono text-xs">
                    {formatTradingValue(stock.trading_value)}
                  </td>
                  <td className={`py-2.5 pr-3 text-right font-mono text-xs ${stock.change_rate >= 0 ? "text-red-400" : "text-blue-400"}`}>
                    {stock.change_rate >= 0 ? "+" : ""}
                    {stock.change_rate.toFixed(2)}%
                  </td>
                  <td className={`py-2.5 pr-3 text-xs ${positionStyle}`}>
                    {stock.daily_position}
                  </td>
                  <td className="py-2.5 pr-3 text-right text-white font-mono text-xs">
                    {stock.ki_score.toFixed(1)}
                  </td>
                  <td className="py-2.5 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium border ${gradeStyle}`}>
                      {stock.grade}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
