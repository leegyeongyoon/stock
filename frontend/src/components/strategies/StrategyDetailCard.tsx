"use client";

import type { StrategyDetail } from "@/lib/api";
import { pnlColor } from "@/lib/utils";
import NearEntryTable from "./NearEntryTable";

interface Props {
  detail: StrategyDetail | undefined;
  name: string;
  onToggle: (name: string) => void;
}

export default function StrategyDetailCard({ detail, name, onToggle }: Props) {
  if (!detail) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 animate-pulse h-64" />
    );
  }

  const meta = detail.meta;
  const todayPnl = detail.trades.reduce((sum, t) => sum + t.pnl, 0);
  const todayWins = detail.trades.filter((t) => t.pnl > 0).length;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div>
            <h3 className="font-semibold text-sm">
              {meta.display_name}
            </h3>
            <p className="text-xs text-slate-500">
              {meta.time_window}
              {detail.is_active_time && (
                <span className="ml-2 text-green-400">&#9679; 활성</span>
              )}
              {!detail.is_active_time && (
                <span className="ml-2 text-slate-600">&#9675; 비활성</span>
              )}
            </p>
          </div>
        </div>
        <button
          onClick={() => onToggle(name)}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            detail.enabled
              ? "bg-green-500/20 text-green-400 hover:bg-green-500/30"
              : "bg-slate-700 text-slate-400 hover:bg-slate-600"
          }`}
        >
          {detail.enabled ? "ON" : "OFF"}
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3">
          <div className="text-center">
            <p className="text-xs text-slate-500">백테스트</p>
            <p className="text-sm font-mono text-green-400 font-medium">
              {meta.backtest_return}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">승률</p>
            <p className="text-sm font-mono text-blue-400">
              {meta.backtest_wr}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">매매수</p>
            <p className="text-sm font-mono text-white">
              {meta.backtest_trades}회
            </p>
          </div>
        </div>

        {/* Today's performance */}
        <div className="bg-slate-900/50 rounded p-3">
          <p className="text-xs text-slate-500 mb-1">오늘 실적</p>
          <div className="flex items-center gap-4 text-xs">
            <span className="text-slate-400">
              시그널 <span className="text-white font-mono">{detail.signals_today}</span>건
            </span>
            <span className="text-slate-400">
              체결 <span className="text-white font-mono">{detail.trades.length}</span>건
            </span>
            {detail.trades.length > 0 && (
              <>
                <span className={pnlColor(todayPnl)}>
                  {todayPnl >= 0 ? "+" : ""}{todayPnl.toLocaleString()}원
                </span>
                <span className="text-slate-400">
                  승 <span className="text-green-400 font-mono">{todayWins}</span>
                </span>
              </>
            )}
          </div>
        </div>

        {/* SL/TP + Conditions */}
        <div className="flex gap-3 text-xs">
          <span className="text-red-400">SL {meta.sl}</span>
          <span className="text-green-400">TP {meta.tp}</span>
        </div>
        <div className="space-y-0.5">
          {meta.conditions.map((c, i) => (
            <p key={i} className="text-xs text-slate-400 pl-2 border-l border-slate-600">
              {c}
            </p>
          ))}
        </div>

        {/* Active positions for this strategy */}
        {detail.positions.length > 0 && (
          <div className="bg-blue-500/5 border border-blue-500/20 rounded p-3">
            <p className="text-xs text-blue-400 font-medium mb-1">
              보유 포지션 ({detail.positions.length})
            </p>
            {detail.positions.map((p) => (
              <div key={p.stock_code} className="flex items-center justify-between text-xs">
                <span className="font-mono text-blue-400">{p.stock_code}</span>
                <span className="text-slate-400">{p.quantity}주 @{p.avg_price.toLocaleString()}</span>
                <span className={pnlColor(p.unrealized_pnl)}>
                  {p.unrealized_pnl >= 0 ? "+" : ""}{p.unrealized_pnl.toLocaleString()}원
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Near entry stocks */}
        <NearEntryTable stocks={detail.near_entry} />
      </div>
    </div>
  );
}
