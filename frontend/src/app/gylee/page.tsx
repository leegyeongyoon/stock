"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getGyleeFilters,
  getGyleePerformance,
  getGyleeTrades,
  type HongTrade,
  type HongPerformanceData,
} from "@/lib/api";
import FilterStatusPanel from "@/components/gylee/FilterStatusPanel";
import GyleeTradingPanel from "@/components/gylee/GyleeTradingPanel";
import BacktestComparison from "@/components/gylee/BacktestComparison";

import { Filter, TrendingUp, BarChart3 } from "lucide-react";

function GyleePerformance() {
  const { data, isLoading } = useQuery({
    queryKey: ["gylee-performance"],
    queryFn: getGyleePerformance,
    refetchInterval: 60000,
    retry: 2,
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="animate-pulse h-24 bg-slate-800 rounded-xl" />
      </div>
    );
  }

  if (!data || data.daily.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-6 text-center">
        <TrendingUp size={32} className="text-slate-600 mx-auto mb-2" />
        <p className="text-sm text-slate-400">아직 경윤 전략 거래 기록이 없습니다</p>
        <p className="text-xs text-slate-500 mt-1">자동매매를 시작하면 성과가 여기에 표시됩니다</p>
      </div>
    );
  }

  const { summary } = data;

  const formatKRW = (value: number): string => {
    if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(1)}만`;
    return value.toLocaleString();
  };

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {[
        { label: "총 수익", value: `${summary.total_pnl >= 0 ? "+" : ""}${formatKRW(summary.total_pnl)}원`, color: summary.total_pnl >= 0 ? "text-green-400" : "text-red-400", sub: `${summary.trading_days}일 거래` },
        { label: "총 거래", value: `${summary.total_trades}건`, color: "text-blue-400", sub: `승 ${summary.win_days}일 / 패 ${summary.loss_days}일` },
        { label: "승률", value: `${summary.win_rate}%`, color: summary.win_rate >= 50 ? "text-green-400" : "text-yellow-400", sub: `Best ${formatKRW(summary.best_day_pnl)}원` },
        { label: "평균 일수익", value: `${summary.avg_daily_pnl >= 0 ? "+" : ""}${formatKRW(summary.avg_daily_pnl)}원`, color: summary.avg_daily_pnl >= 0 ? "text-green-400" : "text-red-400", sub: `월추정 ${formatKRW(summary.projected_monthly)}원` },
      ].map((c) => (
        <div key={c.label} className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-3">
          <span className="text-xs text-slate-500">{c.label}</span>
          <p className={`text-lg font-bold font-mono ${c.color}`}>{c.value}</p>
          <p className="text-[10px] text-slate-500 mt-0.5">{c.sub}</p>
        </div>
      ))}
    </div>
  );
}

function GyleeTradeHistory() {
  const { data: trades, isLoading } = useQuery({
    queryKey: ["gylee-trades"],
    queryFn: getGyleeTrades,
    refetchInterval: 10000,
    retry: 2,
  });

  const tradeList: HongTrade[] = trades ?? [];
  const sellTrades = tradeList.filter((t) => t.type !== "buy" && t.pnl != null);
  const totalTrades = sellTrades.length;
  const wins = sellTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;
  const totalPnl = sellTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);

  const fmtPnlPct = (pct: number) => `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
        <BarChart3 size={16} className="text-purple-400" />
        경윤 금일 매매 내역
        {tradeList.length > 0 && (
          <span className="text-xs text-slate-500 font-normal ml-1">({tradeList.length}건)</span>
        )}
      </h3>

      {!isLoading && tradeList.length === 0 && (
        <div className="text-center py-6">
          <BarChart3 size={20} className="text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-500">금일 매매 내역이 없습니다.</p>
        </div>
      )}

      {tradeList.length > 0 && (
        <div className="space-y-1.5 max-h-96 overflow-y-auto">
          {tradeList.map((trade, idx) => {
            const displayPrice = trade.price ?? trade.entry_price ?? 0;
            const hasPnl = trade.type !== "buy" && trade.pnl != null;

            return (
              <div key={`${trade.stock_code}-${trade.time}-${idx}`} className="flex items-center gap-3 p-2.5 rounded-lg bg-slate-900/40">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-white font-medium truncate">{trade.stock_name}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 ${trade.type === "buy" ? "text-blue-400" : "text-slate-400"}`}>
                      {trade.type === "buy" ? "매수" : trade.exit_reason ?? "매도"}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">
                    @{displayPrice.toLocaleString("ko-KR")} | {trade.quantity}주
                  </div>
                </div>
                <div className="text-right shrink-0">
                  {hasPnl ? (
                    <div className={`text-xs font-mono font-medium ${(trade.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {fmtPnlPct(trade.pnl_pct ?? 0)}
                    </div>
                  ) : (
                    <div className="text-xs text-blue-400 font-medium">진입</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {totalTrades > 0 && (
        <div className="grid grid-cols-3 gap-2 pt-3 border-t border-slate-700">
          <div className="text-center">
            <div className="text-[10px] text-slate-500 mb-0.5">청산</div>
            <div className="text-xs font-bold text-white">{totalTrades}건</div>
          </div>
          <div className="text-center">
            <div className="text-[10px] text-slate-500 mb-0.5">승률</div>
            <div className={`text-xs font-bold ${winRate >= 50 ? "text-green-400" : "text-red-400"}`}>{winRate.toFixed(1)}%</div>
          </div>
          <div className="text-center">
            <div className="text-[10px] text-slate-500 mb-0.5">총 손익</div>
            <div className={`text-xs font-bold ${totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
              {totalPnl >= 0 ? "+" : ""}{totalPnl.toLocaleString("ko-KR")}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function GyleePage() {
  const { dataUpdatedAt } = useQuery({
    queryKey: ["gylee-filters"],
    queryFn: getGyleeFilters,
    refetchInterval: 30000,
    retry: 2,
  });

  const lastUpdate = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  return (
    <div className="min-h-screen p-3 space-y-3 sm:p-4 sm:space-y-4 lg:p-6 lg:space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center">
            <Filter size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg sm:text-xl font-bold text-white">경윤 수정 매매법</h1>
            <p className="text-xs text-slate-500">홍인기 전략 + 3대 필터 (시총/기관/눌림)</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && (
            <span className="text-[10px] text-slate-500">
              {lastUpdate.toLocaleTimeString("ko-KR")} 업데이트
            </span>
          )}
        </div>
      </div>

      {/* 1. 필터 현황 */}
      <FilterStatusPanel />

      {/* 2. 자동매매 + 거래내역 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <GyleeTradingPanel />
        <GyleeTradeHistory />
      </div>

      {/* 3. 백테스트 결과 */}
      <BacktestComparison />

      {/* 4. 성과 대시보드 */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3">성과 대시보드</h2>
        <GyleePerformance />
      </div>
    </div>
  );
}
