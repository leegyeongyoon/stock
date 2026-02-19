"use client";

import type { KisExecution } from "@/lib/api";

interface Props {
  executions: KisExecution[];
}

export default function KisExecutionTable({ executions }: Props) {
  const buyTotal = executions
    .filter((e) => e.side === "매수")
    .reduce((s, e) => s + e.total_amount, 0);
  const sellTotal = executions
    .filter((e) => e.side === "매도")
    .reduce((s, e) => s + e.total_amount, 0);

  if (executions.length === 0) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center text-sm text-slate-500">
        체결내역이 없습니다.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 매수/매도 합계 */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
          <p className="text-xs text-slate-500">매수 합계</p>
          <p className="text-lg font-bold font-mono text-red-400">
            {buyTotal.toLocaleString()}원
          </p>
        </div>
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-3 text-center">
          <p className="text-xs text-slate-500">매도 합계</p>
          <p className="text-lg font-bold font-mono text-blue-400">
            {sellTotal.toLocaleString()}원
          </p>
        </div>
      </div>

      {/* 테이블 */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 border-b border-slate-700">
                <th className="px-4 py-2.5 text-left">체결시각</th>
                <th className="px-4 py-2.5 text-left">종목</th>
                <th className="px-4 py-2.5 text-center">매매구분</th>
                <th className="px-4 py-2.5 text-right">체결수량</th>
                <th className="px-4 py-2.5 text-right">체결단가</th>
                <th className="px-4 py-2.5 text-right">체결금액</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((e, i) => {
                const time = e.order_time
                  ? `${e.order_time.slice(0, 2)}:${e.order_time.slice(2, 4)}:${e.order_time.slice(4, 6)}`
                  : "-";

                return (
                  <tr
                    key={`${e.order_id}-${i}`}
                    className={`border-b border-slate-700/30 border-l-2 ${
                      e.side === "매수"
                        ? "border-l-red-500/40"
                        : "border-l-blue-500/40"
                    }`}
                  >
                    <td className="px-4 py-2.5 text-xs text-slate-400 font-mono">
                      {time}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="text-blue-400 font-mono text-xs">
                        {e.stock_code}
                      </span>
                      {e.stock_name && (
                        <span className="ml-1 text-xs text-slate-500">
                          {e.stock_name}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${
                          e.side === "매수"
                            ? "text-red-400 bg-red-500/10"
                            : "text-blue-400 bg-blue-500/10"
                        }`}
                      >
                        {e.side}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">
                      {e.quantity.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-white">
                      {e.price.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">
                      {e.total_amount.toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
