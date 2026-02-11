"use client";

import type { NearEntryStock } from "@/lib/api";
import ConditionGauge from "./ConditionGauge";
import { useState } from "react";

interface Props {
  stocks: NearEntryStock[];
}

export default function NearEntryTable({ stocks }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (stocks.length === 0) {
    return (
      <p className="text-xs text-slate-500 py-2">
        조건 근접 종목이 없습니다 (데이터 수집 중)
      </p>
    );
  }

  return (
    <div className="space-y-1">
      <p className="text-xs text-slate-500 font-medium mb-1">
        진입 근접 Top {stocks.length}
      </p>
      {stocks.map((s) => {
        const isOpen = expanded === s.stock_code;
        return (
          <div
            key={s.stock_code}
            className="bg-slate-900/50 rounded border border-slate-700/50"
          >
            <button
              onClick={() => setExpanded(isOpen ? null : s.stock_code)}
              className="w-full px-3 py-2 flex items-center justify-between text-left"
            >
              <div className="flex items-center gap-3">
                <span className="text-xs font-mono text-blue-400">
                  {s.stock_code}
                </span>
                <span className="text-xs text-slate-300">{s.stock_name}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs font-mono text-slate-400">
                  {s.current_price.toLocaleString()}원
                </span>
                <span
                  className={`text-xs font-mono font-medium ${
                    s.score === s.max_score
                      ? "text-green-400"
                      : s.score >= s.max_score - 1
                      ? "text-yellow-400"
                      : "text-slate-500"
                  }`}
                >
                  {s.score}/{s.max_score}
                </span>
              </div>
            </button>
            {isOpen && (
              <div className="px-3 pb-2">
                <ConditionGauge
                  conditions_met={s.conditions_met}
                  conditions_unmet={s.conditions_unmet}
                  score={s.score}
                  max_score={s.max_score}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
