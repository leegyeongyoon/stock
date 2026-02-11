"use client";

import type { TradeHistoryItem } from "@/lib/api";
import { pnlColor } from "@/lib/utils";

interface Props {
  trade: TradeHistoryItem | null;
  onClose: () => void;
}

export default function TradeDetailModal({ trade, onClose }: Props) {
  if (!trade) return null;

  const entryTime = trade.entry_time
    ? new Date(trade.entry_time).toLocaleString("ko-KR")
    : "-";
  const exitTime = trade.exit_time
    ? new Date(trade.exit_time).toLocaleString("ko-KR")
    : "-";

  const reasonLabel: Record<string, string> = {
    SL: "손절",
    TP: "익절",
    CLOSE: "장마감 청산",
    MANUAL: "수동 청산",
  };

  const rows: { label: string; value: string; color?: string }[] = [
    { label: "종목코드", value: trade.stock_code },
    { label: "종목명", value: trade.stock_name || "-" },
    { label: "전략", value: trade.strategy_name },
    { label: "수량", value: `${trade.quantity}주` },
    {
      label: "매수가",
      value: `${trade.entry_price.toLocaleString()}원`,
    },
    {
      label: "매도가",
      value: `${trade.exit_price.toLocaleString()}원`,
    },
    {
      label: "수익(원)",
      value: `${trade.pnl >= 0 ? "+" : ""}${trade.pnl.toLocaleString()}원`,
      color: pnlColor(trade.pnl),
    },
    {
      label: "수익률",
      value: `${trade.pnl_pct >= 0 ? "+" : ""}${trade.pnl_pct.toFixed(2)}%`,
      color: pnlColor(trade.pnl_pct),
    },
    {
      label: "청산 사유",
      value: reasonLabel[trade.exit_reason] || trade.exit_reason,
    },
    { label: "진입 시간", value: entryTime },
    { label: "청산 시간", value: exitTime },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-slate-800 rounded-xl border border-slate-700 shadow-xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700">
          <div>
            <span className="text-blue-400 font-mono text-sm">
              {trade.stock_code}
            </span>
            {trade.stock_name && (
              <span className="ml-2 text-sm text-slate-300">
                {trade.stock_name}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {/* PnL banner */}
        <div
          className={`mx-5 mt-4 rounded-lg p-3 text-center ${
            trade.pnl >= 0
              ? "bg-green-500/10 border border-green-500/20"
              : "bg-red-500/10 border border-red-500/20"
          }`}
        >
          <p className={`text-2xl font-bold font-mono ${pnlColor(trade.pnl)}`}>
            {trade.pnl >= 0 ? "+" : ""}
            {trade.pnl.toLocaleString()}원
          </p>
          <p
            className={`text-sm font-mono mt-0.5 ${pnlColor(trade.pnl_pct)}`}
          >
            {trade.pnl_pct >= 0 ? "+" : ""}
            {trade.pnl_pct.toFixed(2)}%
          </p>
        </div>

        {/* Detail rows */}
        <div className="px-5 py-4 space-y-2">
          {rows.map((r) => (
            <div
              key={r.label}
              className="flex justify-between text-sm border-b border-slate-700/30 pb-1.5"
            >
              <span className="text-slate-500">{r.label}</span>
              <span className={`font-mono ${r.color || "text-slate-300"}`}>
                {r.value}
              </span>
            </div>
          ))}
        </div>

        {/* Close */}
        <div className="px-5 pb-4">
          <button
            onClick={onClose}
            className="w-full py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm text-slate-300 transition-colors"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
