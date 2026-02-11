"use client";

import { pnlColor } from "@/lib/utils";
import type { Holding, HoldingsSummary } from "@/lib/api";

interface Props {
  holdings: Holding[];
  summary?: HoldingsSummary;
}

export default function HoldingsPanel({ holdings, summary }: Props) {
  if (holdings.length === 0) {
    return null;
  }

  const totalPnl = summary?.total_unrealized_pnl || 0;
  const totalPnlPct = summary?.total_unrealized_pnl_pct || 0;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700">
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <h3 className="font-semibold">보유종목</h3>
        <div className="flex items-center gap-4 text-xs">
          <span className="text-slate-500">
            {holdings.length}종목
          </span>
          <span className={pnlColor(totalPnl)}>
            평가손익 {totalPnl >= 0 ? "+" : ""}
            {totalPnl.toLocaleString()}원 ({totalPnlPct >= 0 ? "+" : ""}
            {totalPnlPct.toFixed(2)}%)
          </span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-700/50">
              <th className="px-4 py-2 text-left">종목</th>
              <th className="px-4 py-2 text-left">전략</th>
              <th className="px-4 py-2 text-right">수량</th>
              <th className="px-4 py-2 text-right">매수가</th>
              <th className="px-4 py-2 text-right">현재가</th>
              <th className="px-4 py-2 text-right">평가금액</th>
              <th className="px-4 py-2 text-right">손익</th>
              <th className="px-4 py-2 text-right">수익률</th>
              <th className="px-4 py-2 text-center">SL / TP</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => {
              const pnl = h.pnl_amount || 0;
              const pnlPct = h.pnl_pct || 0;
              return (
                <tr
                  key={h.stock_code}
                  className="border-b border-slate-700/30 hover:bg-slate-700/20"
                >
                  <td className="px-4 py-2.5">
                    <div>
                      <span className="text-blue-400 font-mono text-xs">
                        {h.stock_code}
                      </span>
                      <p className="text-xs text-slate-400">{h.stock_name}</p>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-slate-400">
                    {h.strategy_name}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {h.quantity}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-slate-300">
                    {h.avg_price.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-white">
                    {h.current_price.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-slate-300">
                    {h.market_value.toLocaleString()}
                  </td>
                  <td className={`px-4 py-2.5 text-right font-mono ${pnlColor(pnl)}`}>
                    {pnl >= 0 ? "+" : ""}{pnl.toLocaleString()}
                  </td>
                  <td className={`px-4 py-2.5 text-right font-mono font-medium ${pnlColor(pnlPct)}`}>
                    {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-2.5 text-center text-xs">
                    <span className="text-red-400">{h.stop_loss_price?.toLocaleString() || "-"}</span>
                    {" / "}
                    <span className="text-green-400">{h.take_profit_price?.toLocaleString() || "-"}</span>
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
