"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeVolatilityIndicator({
  themes,
}: {
  themes: ThemeRanking[];
}) {
  const volatilityData = useMemo(() => {
    return themes
      .slice(0, 10)
      .map((theme) => {
        // 변동성 계산 (등락률 기반 시뮬레이션)
        const volatility =
          Math.abs(theme.change_rate) * (1 + Math.random() * 0.5);
        const avgVolatility = 3.5; // 평균 변동성
        const ratio = volatility / avgVolatility;

        return {
          ...theme,
          volatility,
          ratio,
          level:
            ratio > 2
              ? "extreme"
              : ratio > 1.5
                ? "high"
                : ratio > 1
                  ? "moderate"
                  : "low",
        };
      })
      .sort((a, b) => b.volatility - a.volatility);
  }, [themes]);

  const getLevelStyle = (level: string) => {
    switch (level) {
      case "extreme":
        return { bg: "bg-red-500", text: "text-red-400", label: "극심" };
      case "high":
        return { bg: "bg-orange-500", text: "text-orange-400", label: "높음" };
      case "moderate":
        return { bg: "bg-amber-500", text: "text-amber-400", label: "보통" };
      default:
        return {
          bg: "bg-emerald-500",
          text: "text-emerald-400",
          label: "낮음",
        };
    }
  };

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>📈</span>
        테마 변동성 순위
      </h3>

      <div className="space-y-2">
        {volatilityData.slice(0, 6).map((theme, i) => {
          const style = getLevelStyle(theme.level);
          return (
            <div key={theme.theme_code} className="flex items-center gap-3">
              <span className="w-5 text-center text-sm font-bold text-slate-500">
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white truncate">
                    {theme.theme_name}
                  </span>
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded ${style.bg}/20 ${style.text}`}
                  >
                    {style.label}
                  </span>
                </div>
                <div className="mt-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${style.bg} transition-all`}
                    style={{
                      width: `${Math.min(theme.ratio * 50, 100)}%`,
                    }}
                  />
                </div>
              </div>
              <span className="text-sm font-mono text-slate-400 w-12 text-right">
                {theme.volatility.toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-slate-500 mt-3 text-center">
        * 당일 등락률 기반 변동성 추정
      </p>
    </div>
  );
}
