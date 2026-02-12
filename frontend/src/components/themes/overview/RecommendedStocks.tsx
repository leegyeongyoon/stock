"use client";

import type { ThemeStock } from "@/lib/api";

function StockCard({
  stock,
  rank,
  onClick,
}: {
  stock: ThemeStock;
  rank: number;
  onClick: () => void;
}) {
  const score = stock.score ?? stock.total_score ?? 0;
  const changeRate = stock.change_rate ?? 0;
  const isPositive = changeRate > 0;
  const isNegative = changeRate < 0;

  const getGradeColor = (s: number) => {
    if (s >= 70) return "from-emerald-500 to-emerald-600";
    if (s >= 50) return "from-amber-500 to-amber-600";
    return "from-slate-500 to-slate-600";
  };

  return (
    <div className="group relative overflow-hidden bg-slate-800/60 hover:bg-slate-800 rounded-xl p-3 sm:p-4 border border-slate-700/50 hover:border-blue-500/50 transition-all duration-200">
      <div className="absolute -top-1 -left-1 w-7 h-7 sm:w-8 sm:h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-br-xl flex items-center justify-center">
        <span className="text-xs font-bold text-white">{rank}</span>
      </div>

      <div className="ml-4">
        <div className="flex items-start justify-between mb-2 sm:mb-3">
          <div>
            <div className="flex items-center gap-1.5">
              {stock.is_leader && <span className="text-yellow-400 text-sm">👑</span>}
              <h4 className="font-semibold text-white text-sm sm:text-base">{stock.name}</h4>
            </div>
            <p className="text-xs text-slate-500">{stock.code}</p>
          </div>
          <div
            className={`text-right ${
              isPositive ? "text-emerald-400" : isNegative ? "text-red-400" : "text-slate-400"
            }`}
          >
            <p className="text-base sm:text-lg font-bold font-mono">
              {isPositive ? "+" : ""}
              {changeRate.toFixed(2)}%
            </p>
          </div>
        </div>

        <div className="relative h-1.5 sm:h-2 bg-slate-700 rounded-full overflow-hidden mb-2 sm:mb-3">
          <div
            className={`absolute left-0 top-0 h-full bg-gradient-to-r ${getGradeColor(score)} transition-all duration-500`}
            style={{ width: `${score}%` }}
          />
        </div>

        <div className="flex items-center justify-between text-xs mb-2 sm:mb-3">
          <span className="text-slate-500">점수</span>
          <span
            className={`font-bold ${
              score >= 70
                ? "text-emerald-400"
                : score >= 50
                ? "text-amber-400"
                : "text-slate-400"
            }`}
          >
            {score.toFixed(0)}점
          </span>
        </div>

        <button
          onClick={onClick}
          className="w-full py-2 sm:py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-xs sm:text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <span>상세 분석 보기</span>
        </button>
      </div>
    </div>
  );
}

export default function RecommendedStocks({
  stocks,
  onStockClick,
  onViewAll,
}: {
  stocks?: ThemeStock[];
  onStockClick: (code: string, name: string) => void;
  onViewAll: () => void;
}) {
  if (!stocks || stocks.length === 0) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        <h2 className="text-base sm:text-lg font-bold text-white">추천 종목 TOP 4</h2>
        <button onClick={onViewAll} className="text-sm text-blue-400 hover:text-blue-300">
          전체보기 →
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-4 md:gap-4">
        {stocks.slice(0, 4).map((stock, i) => (
          <StockCard
            key={stock.code}
            stock={stock}
            rank={i + 1}
            onClick={() => onStockClick(stock.code, stock.name)}
          />
        ))}
      </div>
    </div>
  );
}

export { StockCard };
