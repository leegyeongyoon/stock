"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeMomentumSparklines({
  themes,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  // 7일간 모멘텀 데이터 시뮬레이션
  const momentumData = useMemo(() => {
    return themes.slice(0, 6).map((theme) => {
      const data = [];
      let value = 100;
      for (let i = 0; i < 7; i++) {
        const trend = theme.change_rate > 0 ? 0.55 : 0.45;
        value = value * (1 + (Math.random() - trend) * 0.05);
        data.push(value);
      }
      const weekChange = ((data[6] - data[0]) / data[0]) * 100;
      return { ...theme, sparkline: data, weekChange };
    });
  }, [themes]);

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>📈</span>
        테마 모멘텀 추이 (7일)
      </h3>

      <div className="space-y-3">
        {momentumData.map((theme) => {
          const min = Math.min(...theme.sparkline);
          const max = Math.max(...theme.sparkline);
          const range = max - min || 1;
          const isUp = theme.weekChange > 0;

          const points = theme.sparkline
            .map((v, i) => {
              const x = (i / 6) * 80;
              const y = 20 - ((v - min) / range) * 18;
              return `${x},${y}`;
            })
            .join(" ");

          return (
            <div
              key={theme.theme_code}
              onClick={() =>
                onThemeClick(theme.theme_code, theme.theme_name)
              }
              className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-700/30 cursor-pointer"
            >
              <span className="text-sm text-white w-20 truncate">
                {theme.theme_name}
              </span>
              <div className="flex-1">
                <svg viewBox="0 0 80 22" className="w-full h-6">
                  <polyline
                    points={points}
                    fill="none"
                    stroke={isUp ? "#10b981" : "#ef4444"}
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <circle
                    cx={80}
                    cy={
                      20 -
                      ((theme.sparkline[6] - min) / range) * 18
                    }
                    r="2.5"
                    fill={isUp ? "#10b981" : "#ef4444"}
                  />
                </svg>
              </div>
              <span
                className={`text-sm font-mono w-16 text-right ${
                  isUp ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {isUp ? "+" : ""}
                {theme.weekChange.toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
