"use client";

import type { KisMatchedTrade, KisOpenPosition } from "@/lib/api";
import { pnlColor } from "@/lib/utils";

interface Props {
  trades: KisMatchedTrade[];
  openPositions: KisOpenPosition[];
}

function fmtTime(t: string) {
  if (!t || t.length < 6) return "-";
  return `${t.slice(0, 2)}:${t.slice(2, 4)}:${t.slice(4, 6)}`;
}

export default function KisExecutionTable({ trades, openPositions }: Props) {
  const totalPnl = trades.reduce((s, t) => s + t.pnl, 0);
  const totalBuy = trades.reduce((s, t) => s + t.buy_amount, 0);
  const totalSell = trades.reduce((s, t) => s + t.sell_amount, 0);
  const wins = trades.filter((t) => t.pnl > 0).length;
  const losses = trades.filter((t) => t.pnl < 0).length;

  if (trades.length === 0 && openPositions.length === 0) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center text-sm text-slate-500">
        체결내역이 없습니다.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 요약 카드 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
          <p className="text-xs text-slate-500">실현 손익</p>
          <p className={`text-lg font-bold font-mono ${pnlColor(totalPnl)}`}>
            {totalPnl >= 0 ? "+" : ""}
            {totalPnl.toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
          <p className="text-xs text-slate-500">매매 건수</p>
          <p className="text-lg font-bold font-mono">
            <span className="text-green-400">{wins}</span>
            <span className="text-slate-600 mx-1">/</span>
            <span className="text-red-400">{losses}</span>
          </p>
        </div>
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
          <p className="text-xs text-slate-500">매수 총액</p>
          <p className="text-lg font-bold font-mono text-red-400">
            {totalBuy.toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
          <p className="text-xs text-slate-500">매도 총액</p>
          <p className="text-lg font-bold font-mono text-blue-400">
            {totalSell.toLocaleString()}
          </p>
        </div>
      </div>

      {/* 매칭된 거래 테이블 */}
      {trades.length > 0 && (
        <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 border-b border-slate-700">
                  <th className="px-4 py-2.5 text-left">종목</th>
                  <th className="px-4 py-2.5 text-right">수량</th>
                  <th className="px-4 py-2.5 text-right">매수가</th>
                  <th className="px-4 py-2.5 text-left text-slate-600">시각</th>
                  <th className="px-4 py-2.5 text-right">매도가</th>
                  <th className="px-4 py-2.5 text-left text-slate-600">시각</th>
                  <th className="px-4 py-2.5 text-right">손익(원)</th>
                  <th className="px-4 py-2.5 text-right">수익률</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr
                    key={`${t.stock_code}-${t.sell_time}-${i}`}
                    className={`border-b border-slate-700/30 border-l-2 ${
                      t.pnl >= 0
                        ? "border-l-green-500/40"
                        : "border-l-red-500/40"
                    }`}
                  >
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
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">
                      {t.quantity.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-red-400">
                      {t.buy_price.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-600 font-mono">
                      {fmtTime(t.buy_time)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-blue-400">
                      {t.sell_price.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-600 font-mono">
                      {fmtTime(t.sell_time)}
                    </td>
                    <td
                      className={`px-4 py-2.5 text-right font-mono text-xs font-medium ${pnlColor(t.pnl)}`}
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 미매도 보유 포지션 */}
      {openPositions.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-400 mb-2">
            보유 중 (미매도)
          </h3>
          <div className="bg-slate-800 rounded-lg border border-yellow-500/30 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-slate-700">
                    <th className="px-4 py-2.5 text-left">종목</th>
                    <th className="px-4 py-2.5 text-right">수량</th>
                    <th className="px-4 py-2.5 text-right">매수가</th>
                    <th className="px-4 py-2.5 text-right">매수금액</th>
                    <th className="px-4 py-2.5 text-left">매수시각</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((p, i) => (
                    <tr
                      key={`${p.stock_code}-${p.buy_time}-${i}`}
                      className="border-b border-slate-700/30 border-l-2 border-l-yellow-500/40"
                    >
                      <td className="px-4 py-2.5">
                        <span className="text-blue-400 font-mono text-xs">
                          {p.stock_code}
                        </span>
                        {p.stock_name && (
                          <span className="ml-1 text-xs text-slate-500">
                            {p.stock_name}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">
                        {p.quantity.toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-red-400">
                        {p.buy_price.toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">
                        {p.buy_amount.toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-slate-400 font-mono">
                        {fmtTime(p.buy_time)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
