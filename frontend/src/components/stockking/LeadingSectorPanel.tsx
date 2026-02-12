import { TrendingUp, AlertTriangle, Star } from "lucide-react";
import type { LeadingSector } from "@/lib/api";

function formatTradingValue(value: number): string {
  if (value >= 1_0000_0000) return `${(value / 1_0000_0000).toFixed(1)}조`;
  if (value >= 1_0000) return `${(value / 1_0000).toFixed(0)}억`;
  return `${value.toLocaleString()}만`;
}

export default function LeadingSectorPanel({ sectors }: { sectors: LeadingSector[] | undefined }) {
  if (!sectors || sectors.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Star size={16} className="text-yellow-400" />
          주도 섹터
        </h3>
        <p className="text-sm text-slate-500">장 시작 전이거나 주도 섹터 데이터가 없습니다.</p>
      </div>
    );
  }

  const primaryCount = sectors.filter((s) => s.is_primary).length;
  const isConcentrated = primaryCount <= 2;
  const isScattered = primaryCount >= 4;

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Star size={16} className="text-yellow-400" />
          주도 섹터
        </h3>
        {isConcentrated && (
          <span className="text-xs px-2 py-1 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
            집중 (좋음)
          </span>
        )}
        {isScattered && (
          <span className="text-xs px-2 py-1 rounded-full bg-red-500/20 text-red-400 border border-red-500/30 flex items-center gap-1">
            <AlertTriangle size={12} />
            분산 (주의)
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {sectors.map((sector) => (
          <div
            key={sector.sector_name}
            className={`rounded-lg border p-3 transition-colors ${
              sector.is_primary
                ? "bg-slate-700/50 border-emerald-500/30"
                : "bg-slate-800/50 border-slate-700"
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-white">{sector.sector_name}</span>
              {sector.is_primary && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
                  주도
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-slate-500">거래대금</span>
                <p className="text-white font-mono">{formatTradingValue(sector.total_trading_value)}</p>
              </div>
              <div>
                <span className="text-slate-500">평균 등락률</span>
                <p className={`font-mono ${sector.avg_change_rate >= 0 ? "text-red-400" : "text-blue-400"}`}>
                  {sector.avg_change_rate >= 0 ? "+" : ""}
                  {sector.avg_change_rate.toFixed(2)}%
                </p>
              </div>
              <div>
                <span className="text-slate-500">종목수</span>
                <p className="text-white font-mono">{sector.stock_count}개</p>
              </div>
              <div>
                <span className="text-slate-500">대장주</span>
                <p className="text-yellow-400 truncate flex items-center gap-1">
                  <TrendingUp size={10} />
                  {sector.leader_stock}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
