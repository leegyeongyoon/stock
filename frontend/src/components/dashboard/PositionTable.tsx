"use client";

import type { Position } from "@/lib/api";

interface Props {
  positions: Position[];
}

export default function PositionTable({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center text-slate-500">
        보유 포지션이 없습니다
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700">
        <h3 className="font-semibold">보유 포지션</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/50">
            <tr className="text-slate-400">
              <th className="px-4 py-2 text-left">종목</th>
              <th className="px-4 py-2 text-left">전략</th>
              <th className="px-4 py-2 text-right">수량</th>
              <th className="px-4 py-2 text-right">평균가</th>
              <th className="px-4 py-2 text-right">현재가</th>
              <th className="px-4 py-2 text-right">손익</th>
              <th className="px-4 py-2 text-right">수익률</th>
              <th className="px-4 py-2 text-right">SL / TP</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const pnlColor =
                pos.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400";
              const sign = pos.unrealized_pnl >= 0 ? "+" : "";
              return (
                <tr
                  key={pos.stock_code}
                  className="border-t border-slate-700/50 hover:bg-slate-700/30"
                >
                  <td className="px-4 py-2">
                    <div className="font-medium">{pos.stock_name || pos.stock_code}</div>
                    <div className="text-xs text-slate-500">{pos.stock_code}</div>
                  </td>
                  <td className="px-4 py-2 text-slate-400 text-xs">
                    {pos.strategy_name}
                  </td>
                  <td className="px-4 py-2 text-right">{pos.quantity}</td>
                  <td className="px-4 py-2 text-right">
                    {pos.avg_price.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {pos.current_price.toLocaleString()}
                  </td>
                  <td className={`px-4 py-2 text-right ${pnlColor}`}>
                    {sign}
                    {pos.unrealized_pnl.toLocaleString()}
                  </td>
                  <td className={`px-4 py-2 text-right ${pnlColor}`}>
                    {sign}
                    {pos.unrealized_pnl_pct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-slate-500">
                    {pos.stop_loss_price?.toLocaleString() || "-"} /{" "}
                    {pos.take_profit_price?.toLocaleString() || "-"}
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
