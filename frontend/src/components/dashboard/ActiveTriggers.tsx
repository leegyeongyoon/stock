"use client";

import { useState } from "react";
import type { DashboardStrategy } from "@/lib/api";

interface Props {
  strategies: DashboardStrategy[] | undefined;
}

export default function ActiveTriggers({ strategies }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!strategies) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center text-slate-500">
        전략 로딩 중...
      </div>
    );
  }

  if (strategies.length === 0) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center text-slate-500">
        등록된 전략 없음
      </div>
    );
  }

  const activeCount = strategies.filter(
    (s) => s.status === "active" || s.enabled
  ).length;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700">
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <h3 className="font-semibold">전략 상태</h3>
        <span className="text-xs text-slate-500">
          {activeCount}/{strategies.length} 활성
        </span>
      </div>
      <div className="divide-y divide-slate-700/50">
        {strategies.map((s) => {
          const isOpen = expanded === s.name;
          const isActive = s.status === "active" || s.enabled;
          return (
            <div key={s.name} className="px-4 py-3">
              {/* Header row */}
              <div className="flex items-center justify-between">
                <button
                  onClick={() => setExpanded(isOpen ? null : s.name)}
                  className="flex-1 text-left"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-500">
                      {isOpen ? "▼" : "▶"}
                    </span>
                    <div>
                      <p className="text-sm font-medium">
                        {s.display_name || s.name}
                      </p>
                      <p className="text-xs text-slate-500">
                        {s.time_window || s.status} | 시그널 {s.signals_today}건
                      </p>
                    </div>
                  </div>
                </button>

                {/* Backtest badge */}
                {s.backtest_return && (
                  <span className="text-xs text-green-400 mr-3 font-mono">
                    {s.backtest_return}
                  </span>
                )}

                {/* Status indicator */}
                <span
                  className={`px-3 py-1 rounded-full text-xs font-medium ${
                    isActive
                      ? "bg-green-500/20 text-green-400"
                      : "bg-slate-700 text-slate-400"
                  }`}
                >
                  {isActive ? "ON" : "OFF"}
                </span>
              </div>

              {/* Expanded detail */}
              {isOpen && (
                <div className="mt-3 ml-5 space-y-2">
                  {s.description && (
                    <p className="text-xs text-slate-400">{s.description}</p>
                  )}

                  {/* Backtest stats */}
                  {(s.backtest_return || s.backtest_wr) && (
                    <div className="flex gap-4 text-xs">
                      {s.backtest_return && (
                        <span className="text-slate-500">
                          수익률{" "}
                          <span className="text-green-400 font-mono">
                            {s.backtest_return}
                          </span>
                        </span>
                      )}
                      {s.backtest_wr && (
                        <span className="text-slate-500">
                          승률{" "}
                          <span className="text-blue-400 font-mono">
                            {s.backtest_wr}
                          </span>
                        </span>
                      )}
                      {s.backtest_trades && (
                        <span className="text-slate-500">
                          매매{" "}
                          <span className="text-white font-mono">
                            {s.backtest_trades}회
                          </span>
                        </span>
                      )}
                    </div>
                  )}

                  {/* SL/TP */}
                  {(s.sl || s.tp) && (
                    <div className="flex gap-4 text-xs">
                      {s.sl && <span className="text-red-400">SL {s.sl}</span>}
                      {s.tp && <span className="text-green-400">TP {s.tp}</span>}
                    </div>
                  )}

                  {/* Entry conditions */}
                  {s.conditions && s.conditions.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-xs text-slate-500 font-medium">
                        진입 조건:
                      </p>
                      {s.conditions.map((cond, i) => (
                        <p
                          key={i}
                          className="text-xs text-slate-400 pl-2 border-l border-slate-600"
                        >
                          {cond}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
