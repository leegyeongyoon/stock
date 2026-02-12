"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeRankTracker({
  themes,
}: {
  themes: ThemeRanking[];
}) {
  // 순위 변동 데이터 시뮬레이션
  const rankChanges = useMemo(() => {
    return themes.slice(0, 10).map((theme, i) => {
      const prevRank = i + 1 + Math.floor((Math.random() - 0.5) * 6);
      const change = prevRank - (i + 1);
      return {
        ...theme,
        currentRank: i + 1,
        prevRank,
        change,
        type: change > 0 ? "up" : change < 0 ? "down" : "same",
      };
    });
  }, [themes]);

  const movers = rankChanges.filter((t) => Math.abs(t.change) >= 2);

  if (movers.length === 0) return null;

  return (
    <div className="p-5 bg-gradient-to-r from-blue-900/30 to-purple-900/30 rounded-2xl border border-blue-500/20">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>🔄</span>
        순위 급변동 테마
      </h3>

      <div className="grid grid-cols-2 gap-3">
        {movers.slice(0, 4).map((theme) => (
          <div
            key={theme.theme_code}
            className={`p-3 rounded-xl border ${
              theme.type === "up"
                ? "bg-emerald-500/10 border-emerald-500/30"
                : "bg-red-500/10 border-red-500/30"
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-white truncate flex-1">
                {theme.theme_name}
              </span>
              <span
                className={`text-lg font-bold ${
                  theme.type === "up" ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {theme.type === "up" ? "▲" : "▼"}
                {Math.abs(theme.change)}
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span>{theme.prevRank}위</span>
              <span>→</span>
              <span className="text-white font-medium">
                {theme.currentRank}위
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
