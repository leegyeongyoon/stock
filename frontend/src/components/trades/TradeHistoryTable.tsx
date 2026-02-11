"use client";

import { useState } from "react";
import type { TradeHistoryItem } from "@/lib/api";
import { pnlColor } from "@/lib/utils";

interface Props {
  trades: TradeHistoryItem[];
  onSelectTrade: (trade: TradeHistoryItem) => void;
}

type SortKey = "exit_time" | "pnl" | "pnl_pct" | "stock_code";

export default function TradeHistoryTable({ trades, onSelectTrade }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("exit_time");
  const [sortDesc, setSortDesc] = useState(true);

  const sorted = [...trades].sort((a, b) => {
    let cmp = 0;
    if (sortKey === "exit_time") {
      cmp = (a.exit_time || "").localeCompare(b.exit_time || "");
    } else if (sortKey === "pnl" || sortKey === "pnl_pct") {
      cmp = (a[sortKey] || 0) - (b[sortKey] || 0);
    } else {
      cmp = (a.stock_code || "").localeCompare(b.stock_code || "");
    }
    return sortDesc ? -cmp : cmp;
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDesc(!sortDesc);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  const sortIcon = (key: SortKey) =>
    sortKey === key ? (sortDesc ? " ▼" : " ▲") : "";

  if (trades.length === 0) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center text-sm text-slate-500">
        거래내역이 없습니다. 장중 매매가 시작되면 여기에 표시됩니다.
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-700">
              <th
                className="px-4 py-2.5 text-left cursor-pointer hover:text-slate-300"
                onClick={() => handleSort("exit_time")}
              >
                시간{sortIcon("exit_time")}
              </th>
              <th
                className="px-4 py-2.5 text-left cursor-pointer hover:text-slate-300"
                onClick={() => handleSort("stock_code")}
              >
                종목{sortIcon("stock_code")}
              </th>
              <th className="px-4 py-2.5 text-left">전략</th>
              <th className="px-4 py-2.5 text-right">매수가</th>
              <th className="px-4 py-2.5 text-right">매도가</th>
              <th className="px-4 py-2.5 text-right">수량</th>
              <th
                className="px-4 py-2.5 text-right cursor-pointer hover:text-slate-300"
                onClick={() => handleSort("pnl")}
              >
                수익(원){sortIcon("pnl")}
              </th>
              <th
                className="px-4 py-2.5 text-right cursor-pointer hover:text-slate-300"
                onClick={() => handleSort("pnl_pct")}
              >
                수익률{sortIcon("pnl_pct")}
              </th>
              <th className="px-4 py-2.5 text-center">사유</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((t, i) => {
              const time = t.exit_time
                ? new Date(t.exit_time).toLocaleString("ko-KR", {
                    month: "2-digit",
                    day: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "-";

              const reasonLabel: Record<string, string> = {
                SL: "손절",
                TP: "익절",
                CLOSE: "마감",
                MANUAL: "수동",
              };

              const reasonColor: Record<string, string> = {
                SL: "text-red-400 bg-red-500/10",
                TP: "text-green-400 bg-green-500/10",
                CLOSE: "text-slate-400 bg-slate-700",
                MANUAL: "text-yellow-400 bg-yellow-500/10",
              };

              return (
                <tr
                  key={i}
                  onClick={() => onSelectTrade(t)}
                  className={`border-b border-slate-700/30 hover:bg-slate-700/20 cursor-pointer border-l-2 ${
                    t.pnl >= 0 ? "border-l-green-500/40" : "border-l-red-500/40"
                  }`}
                >
                  <td className="px-4 py-2.5 text-xs text-slate-400 font-mono">
                    {time}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-blue-400 font-mono text-xs">
                      {t.stock_code}
                    </span>
                    {t.stock_name && (
                      <span className="ml-1 text-xs text-slate-500">
                        {t.stock_name}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-slate-400">
                    {t.strategy_name}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">
                    {t.entry_price.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-white">
                    {t.exit_price.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs">
                    {t.quantity}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-right font-mono text-xs ${pnlColor(t.pnl)}`}
                  >
                    {t.pnl >= 0 ? "+" : ""}
                    {t.pnl.toLocaleString()}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-right font-mono text-xs font-medium ${pnlColor(t.pnl_pct)}`}
                  >
                    {t.pnl_pct >= 0 ? "+" : ""}
                    {t.pnl_pct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        reasonColor[t.exit_reason] || "text-slate-400 bg-slate-700"
                      }`}
                    >
                      {reasonLabel[t.exit_reason] || t.exit_reason}
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
