"use client";

import { useQuery } from "@tanstack/react-query";
import { getStockkingTrades, type HongTrade } from "@/lib/api";
import { ArrowUpRight, ArrowDownRight, Minus, BarChart3 } from "lucide-react";

const EXIT_REASON_LABELS: Record<string, { label: string; color: string }> = {
  "1차익절": { label: "1차익절", color: "text-green-400" },
  "손절": { label: "손절", color: "text-red-400" },
  "본전컷": { label: "본전컷", color: "text-slate-400" },
  "패턴감지": { label: "패턴감지", color: "text-orange-400" },
  "CLOSE": { label: "장마감", color: "text-blue-400" },
};

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return timestamp;
  }
}

function formatPrice(price: number): string {
  return price.toLocaleString("ko-KR");
}

function formatPnlPct(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function getTradeIcon(trade: HongTrade) {
  if (trade.type === "buy") {
    return <ArrowUpRight size={12} className="text-blue-400" />;
  }
  if (trade.type === "partial_sell") {
    return <Minus size={12} className="text-yellow-400" />;
  }
  if ((trade.pnl ?? 0) >= 0) {
    return <ArrowUpRight size={12} className="text-green-400" />;
  }
  return <ArrowDownRight size={12} className="text-red-400" />;
}

function getTypeLabel(trade: HongTrade): { label: string; color: string } {
  if (trade.type === "buy") {
    return { label: "매수", color: "text-blue-400" };
  }
  if (trade.type === "partial_sell") {
    return { label: "분할매도", color: "text-yellow-400" };
  }
  const reasonInfo = EXIT_REASON_LABELS[trade.exit_reason ?? ""] ?? {
    label: trade.exit_reason ?? "매도",
    color: "text-slate-400",
  };
  return reasonInfo;
}

export default function TradeHistory() {
  const { data: trades, isLoading } = useQuery({
    queryKey: ["stockking-trades"],
    queryFn: getStockkingTrades,
    refetchInterval: 10000,
    retry: 2,
  });

  const tradeList = trades ?? [];

  // 집계 계산
  const sellTrades = tradeList.filter((t) => t.type !== "buy" && t.pnl != null);
  const totalTrades = sellTrades.length;
  const wins = sellTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;
  const totalPnl = sellTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <BarChart3 size={16} className="text-blue-400" />
          금일 매매 내역
          {tradeList.length > 0 && (
            <span className="text-xs text-slate-500 font-normal ml-1">({tradeList.length}건)</span>
          )}
        </h3>
      </div>

      {/* Trade List */}
      {isLoading && tradeList.length === 0 && (
        <div className="animate-pulse space-y-2">
          <div className="h-10 bg-slate-700/50 rounded-lg" />
          <div className="h-10 bg-slate-700/50 rounded-lg" />
        </div>
      )}

      {!isLoading && tradeList.length === 0 && (
        <div className="text-center py-6">
          <BarChart3 size={20} className="text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-500">금일 매매 내역이 없습니다.</p>
        </div>
      )}

      {tradeList.length > 0 && (
        <div className="space-y-1.5 max-h-96 overflow-y-auto">
          {tradeList.map((trade, idx) => {
            const typeInfo = getTypeLabel(trade);
            const displayPrice = trade.price ?? trade.entry_price ?? 0;
            const hasPnl = trade.type !== "buy" && trade.pnl != null;

            return (
              <div
                key={`${trade.stock_code}-${trade.time}-${idx}`}
                className="flex items-center gap-3 p-2.5 rounded-lg bg-slate-900/40 hover:bg-slate-900/60 transition-colors"
              >
                {/* Icon */}
                <div className="shrink-0">{getTradeIcon(trade)}</div>

                {/* Stock Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-white font-medium truncate">
                      {trade.stock_name}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${typeInfo.color} bg-slate-700/50`}>
                      {typeInfo.label}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[10px] text-slate-500">
                      @{formatPrice(displayPrice)}
                    </span>
                    <span className="text-[10px] text-slate-600">|</span>
                    <span className="text-[10px] text-slate-500">{trade.quantity}주</span>
                    {trade.strategy_name && (
                      <>
                        <span className="text-[10px] text-slate-600">|</span>
                        <span className="text-[10px] text-slate-500">{trade.strategy_name}</span>
                      </>
                    )}
                  </div>
                </div>

                {/* PnL */}
                <div className="text-right shrink-0">
                  {hasPnl ? (
                    <div className={`text-xs font-mono font-medium ${
                      (trade.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                    }`}>
                      {formatPnlPct(trade.pnl_pct ?? 0)}
                    </div>
                  ) : (
                    <div className="text-xs text-blue-400 font-medium">진입</div>
                  )}
                  <div className="text-[10px] text-slate-500">
                    {formatTime(trade.time)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Summary Stats */}
      {totalTrades > 0 && (
        <div className="grid grid-cols-3 gap-2 pt-3 border-t border-slate-700">
          <div className="text-center">
            <div className="text-[10px] text-slate-500 mb-0.5">청산 수</div>
            <div className="text-xs font-bold text-white">{totalTrades}건</div>
          </div>
          <div className="text-center">
            <div className="text-[10px] text-slate-500 mb-0.5">승률</div>
            <div className={`text-xs font-bold ${
              winRate >= 50 ? "text-green-400" : "text-red-400"
            }`}>
              {winRate.toFixed(1)}%
            </div>
          </div>
          <div className="text-center">
            <div className="text-[10px] text-slate-500 mb-0.5">총 손익</div>
            <div className={`text-xs font-bold ${
              totalPnl >= 0 ? "text-green-400" : "text-red-400"
            }`}>
              {totalPnl >= 0 ? "+" : ""}{totalPnl.toLocaleString("ko-KR")}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
