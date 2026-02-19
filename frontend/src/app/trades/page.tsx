"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getTradeHistory,
  getStrategies,
  getKisExecutions,
} from "@/lib/api";
import type { TradeHistoryItem } from "@/lib/api";
import TradeHistoryTable from "@/components/trades/TradeHistoryTable";
import TradeDetailModal from "@/components/trades/TradeDetailModal";
import KisExecutionTable from "@/components/trades/KisExecutionTable";
import { pnlColor } from "@/lib/utils";

type Tab = "system" | "kis";

function todayStr() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function TradesPage() {
  const [tab, setTab] = useState<Tab>("system");
  const [strategyFilter, setStrategyFilter] = useState("");
  const [selectedTrade, setSelectedTrade] = useState<TradeHistoryItem | null>(
    null
  );
  const [kisDate, setKisDate] = useState(todayStr);

  const { data: strategiesData } = useQuery({
    queryKey: ["strategies"],
    queryFn: getStrategies,
  });

  const { data, isLoading } = useQuery({
    queryKey: ["trade-history", strategyFilter],
    queryFn: () =>
      getTradeHistory({
        strategy: strategyFilter || undefined,
        sort_by: "exit_time",
        order: "desc",
      }),
    refetchInterval: 15_000,
    enabled: tab === "system",
  });

  const { data: kisData, isLoading: kisLoading } = useQuery({
    queryKey: ["kis-executions", kisDate],
    queryFn: () => getKisExecutions(kisDate),
    refetchInterval: 30_000,
    enabled: tab === "kis",
  });

  const trades = data?.trades || [];
  const total = data?.total || 0;

  const wins = trades.filter((t) => t.pnl > 0).length;
  const losses = trades.filter((t) => t.pnl < 0).length;
  const totalPnl = trades.reduce((s, t) => s + t.pnl, 0);
  const winRate = trades.length > 0 ? (wins / trades.length) * 100 : 0;
  const avgPnl = trades.length > 0 ? totalPnl / trades.length : 0;

  const executions = kisData?.executions || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">거래내역</h2>
        {tab === "system" && (
          <span className="text-xs text-slate-500">총 {total}건</span>
        )}
        {tab === "kis" && (
          <span className="text-xs text-slate-500">
            {executions.length}건 체결
          </span>
        )}
      </div>

      {/* Tab */}
      <div className="flex gap-1 bg-slate-800 rounded-lg p-1 border border-slate-700 w-fit">
        <button
          onClick={() => setTab("system")}
          className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
            tab === "system"
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          시스템 거래
        </button>
        <button
          onClick={() => setTab("kis")}
          className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
            tab === "kis"
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          KIS 체결내역
        </button>
      </div>

      {/* === System trades tab === */}
      {tab === "system" && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
              <p className="text-xs text-slate-500">총 거래</p>
              <p className="text-lg font-bold font-mono">{trades.length}</p>
            </div>
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
              <p className="text-xs text-slate-500">승/패</p>
              <p className="text-lg font-bold font-mono">
                <span className="text-green-400">{wins}</span>
                <span className="text-slate-600 mx-1">/</span>
                <span className="text-red-400">{losses}</span>
              </p>
            </div>
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
              <p className="text-xs text-slate-500">승률</p>
              <p
                className={`text-lg font-bold font-mono ${pnlColor(winRate - 50)}`}
              >
                {winRate.toFixed(1)}%
              </p>
            </div>
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
              <p className="text-xs text-slate-500">총 수익</p>
              <p
                className={`text-lg font-bold font-mono ${pnlColor(totalPnl)}`}
              >
                {totalPnl >= 0 ? "+" : ""}
                {totalPnl.toLocaleString()}
              </p>
            </div>
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
              <p className="text-xs text-slate-500">평균 수익</p>
              <p
                className={`text-lg font-bold font-mono ${pnlColor(avgPnl)}`}
              >
                {avgPnl >= 0 ? "+" : ""}
                {avgPnl.toLocaleString()}
              </p>
            </div>
          </div>

          {/* Filter */}
          <div className="flex items-center gap-3">
            <label className="text-xs text-slate-500">전략 필터:</label>
            <select
              value={strategyFilter}
              onChange={(e) => setStrategyFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:border-blue-500"
            >
              <option value="">전체</option>
              {(strategiesData?.strategies || []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.display_name}
                </option>
              ))}
            </select>
          </div>

          {/* Table */}
          {isLoading ? (
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center text-sm text-slate-500 animate-pulse">
              거래내역을 불러오는 중...
            </div>
          ) : (
            <TradeHistoryTable
              trades={trades}
              onSelectTrade={setSelectedTrade}
            />
          )}

          {/* Detail modal */}
          <TradeDetailModal
            trade={selectedTrade}
            onClose={() => setSelectedTrade(null)}
          />
        </>
      )}

      {/* === KIS executions tab === */}
      {tab === "kis" && (
        <>
          {/* Date picker */}
          <div className="flex items-center gap-3">
            <label className="text-xs text-slate-500">조회일:</label>
            <input
              type="date"
              value={kisDate}
              onChange={(e) => setKisDate(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:border-blue-500"
            />
          </div>

          {kisData?.error && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 text-sm text-yellow-400">
              {kisData.error}
            </div>
          )}

          {kisLoading ? (
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center text-sm text-slate-500 animate-pulse">
              KIS 체결내역을 불러오는 중...
            </div>
          ) : (
            <KisExecutionTable executions={executions} />
          )}
        </>
      )}
    </div>
  );
}
