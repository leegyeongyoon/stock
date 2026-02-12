"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeRiskReturnMatrix({
  themes,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const matrixData = useMemo(() => {
    return themes.slice(0, 12).map((theme) => {
      const risk =
        Math.abs(theme.change_rate) * (0.8 + Math.random() * 0.4);
      const returnVal = theme.change_rate;
      const sharpe = returnVal / (risk || 1);

      return {
        ...theme,
        risk,
        return: returnVal,
        sharpe,
        quadrant:
          returnVal > 0 && risk < 3
            ? "optimal"
            : returnVal > 0 && risk >= 3
              ? "aggressive"
              : returnVal <= 0 && risk < 3
                ? "defensive"
                : "avoid",
      };
    });
  }, [themes]);

  const quadrantColors: Record<string, string> = {
    optimal: "bg-emerald-500/20 border-emerald-500/30",
    aggressive: "bg-amber-500/20 border-amber-500/30",
    defensive: "bg-blue-500/20 border-blue-500/30",
    avoid: "bg-red-500/20 border-red-500/30",
  };

  const quadrantLabels: Record<string, { label: string; desc: string }> = {
    optimal: { label: "최적", desc: "저위험 고수익" },
    aggressive: { label: "공격", desc: "고위험 고수익" },
    defensive: { label: "방어", desc: "저위험 저수익" },
    avoid: { label: "회피", desc: "고위험 저수익" },
  };

  const grouped = matrixData.reduce(
    (acc, theme) => {
      if (!acc[theme.quadrant]) acc[theme.quadrant] = [];
      acc[theme.quadrant].push(theme);
      return acc;
    },
    {} as Record<string, typeof matrixData>
  );

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>⚖️</span>
        리스크/수익 매트릭스
      </h3>

      <div className="grid grid-cols-2 gap-3">
        {(["optimal", "aggressive", "defensive", "avoid"] as const).map(
          (quadrant) => (
            <div
              key={quadrant}
              className={`p-3 rounded-xl border ${quadrantColors[quadrant]}`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-white">
                  {quadrantLabels[quadrant].label}
                </span>
                <span className="text-xs text-slate-500">
                  {quadrantLabels[quadrant].desc}
                </span>
              </div>
              <div className="space-y-1">
                {(grouped[quadrant] || []).slice(0, 3).map((theme) => (
                  <div
                    key={theme.theme_code}
                    onClick={() =>
                      onThemeClick(theme.theme_code, theme.theme_name)
                    }
                    className="flex items-center justify-between text-xs cursor-pointer hover:bg-white/5 rounded px-1"
                  >
                    <span className="text-slate-300 truncate flex-1">
                      {theme.theme_name}
                    </span>
                    <span
                      className={
                        theme.return > 0
                          ? "text-emerald-400"
                          : "text-red-400"
                      }
                    >
                      {theme.return > 0 ? "+" : ""}
                      {theme.return.toFixed(1)}%
                    </span>
                  </div>
                ))}
                {(!grouped[quadrant] ||
                  grouped[quadrant].length === 0) && (
                  <span className="text-xs text-slate-500">없음</span>
                )}
              </div>
            </div>
          )
        )}
      </div>
    </div>
  );
}
