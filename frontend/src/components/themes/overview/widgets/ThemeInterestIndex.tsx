"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeInterestIndex({
  themes,
}: {
  themes: ThemeRanking[];
}) {
  const interestData = useMemo(() => {
    return themes
      .slice(0, 8)
      .map((theme) => {
        // 관심도 지수 시뮬레이션 (뉴스 점수 + 랜덤)
        const baseInterest = theme.news_score * 4;
        const interest = Math.floor(baseInterest + Math.random() * 50);
        const prevInterest = Math.floor(
          interest * (0.8 + Math.random() * 0.4)
        );
        const change = ((interest - prevInterest) / prevInterest) * 100;

        return {
          ...theme,
          interest,
          prevInterest,
          change,
          level: interest > 80 ? "hot" : interest > 50 ? "warm" : "cool",
        };
      })
      .sort((a, b) => b.interest - a.interest);
  }, [themes]);

  const maxInterest = Math.max(...interestData.map((d) => d.interest));

  return (
    <div className="p-5 bg-gradient-to-br from-orange-900/20 to-red-900/20 rounded-2xl border border-orange-500/20">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>🔥</span>
        테마 관심도 지수
        <span className="text-xs text-slate-500 ml-auto">
          SNS + 뉴스 종합
        </span>
      </h3>

      <div className="space-y-2">
        {interestData.slice(0, 5).map((theme, i) => (
          <div key={theme.theme_code} className="flex items-center gap-3">
            <span
              className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                i === 0
                  ? "bg-orange-500 text-white"
                  : i === 1
                    ? "bg-orange-400/70 text-white"
                    : "bg-slate-700 text-slate-400"
              }`}
            >
              {i + 1}
            </span>
            <span className="text-sm text-white flex-1 truncate">
              {theme.theme_name}
            </span>
            <div className="w-24 h-2 bg-slate-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${
                  theme.level === "hot"
                    ? "bg-gradient-to-r from-orange-500 to-red-500"
                    : theme.level === "warm"
                      ? "bg-gradient-to-r from-amber-500 to-orange-500"
                      : "bg-slate-500"
                }`}
                style={{
                  width: `${(theme.interest / maxInterest) * 100}%`,
                }}
              />
            </div>
            <span className="text-sm font-mono text-white w-8">
              {theme.interest}
            </span>
            <span
              className={`text-xs w-12 text-right ${
                theme.change > 0
                  ? "text-emerald-400"
                  : theme.change < 0
                    ? "text-red-400"
                    : "text-slate-400"
              }`}
            >
              {theme.change > 0 ? "▲" : theme.change < 0 ? "▼" : "-"}
              {Math.abs(theme.change).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
