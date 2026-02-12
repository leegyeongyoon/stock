"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeTopStocksPanel({
  themes,
  onThemeClick,
  onStockClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
  onStockClick: (code: string, name: string) => void;
}) {
  // TOP 3 테마의 대표 종목 시뮬레이션
  const topThemesWithStocks = useMemo(() => {
    return themes.slice(0, 3).map((theme) => ({
      ...theme,
      topStocks: [
        {
          name: `${theme.theme_name.slice(0, 3)}전자`,
          change: theme.change_rate * (0.8 + Math.random() * 0.4),
        },
        {
          name: `${theme.theme_name.slice(0, 3)}화학`,
          change: theme.change_rate * (0.6 + Math.random() * 0.6),
        },
        {
          name: `${theme.theme_name.slice(0, 3)}바이오`,
          change: theme.change_rate * (0.5 + Math.random() * 0.8),
        },
      ],
    }));
  }, [themes]);

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>🏅</span>
        TOP3 테마 대표 종목
      </h3>

      <div className="space-y-4">
        {topThemesWithStocks.map((theme, i) => (
          <div
            key={theme.theme_code}
            className="p-3 bg-slate-900/50 rounded-xl"
          >
            <div
              onClick={() =>
                onThemeClick(theme.theme_code, theme.theme_name)
              }
              className="flex items-center gap-2 mb-2 cursor-pointer hover:text-blue-400"
            >
              <span
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white ${
                  i === 0
                    ? "bg-amber-500"
                    : i === 1
                      ? "bg-slate-400"
                      : "bg-amber-700"
                }`}
              >
                {i + 1}
              </span>
              <span className="font-medium text-white">
                {theme.theme_name}
              </span>
              <span
                className={`text-sm ml-auto ${
                  theme.change_rate > 0
                    ? "text-emerald-400"
                    : "text-red-400"
                }`}
              >
                {theme.change_rate > 0 ? "+" : ""}
                {theme.change_rate.toFixed(2)}%
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {theme.topStocks.map((stock, j) => (
                <div
                  key={j}
                  className="p-2 bg-slate-800/50 rounded-lg text-center cursor-pointer hover:bg-slate-700/50"
                >
                  <p className="text-xs text-white truncate">{stock.name}</p>
                  <p
                    className={`text-xs font-mono mt-1 ${
                      stock.change > 0
                        ? "text-emerald-400"
                        : "text-red-400"
                    }`}
                  >
                    {stock.change > 0 ? "+" : ""}
                    {stock.change.toFixed(1)}%
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
