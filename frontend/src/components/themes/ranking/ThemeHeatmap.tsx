"use client";

import type { ThemeRanking } from "@/lib/api";

export default function ThemeHeatmap({
  themes,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const getHeatColor = (changeRate: number) => {
    if (changeRate >= 5) return "bg-emerald-500";
    if (changeRate >= 3) return "bg-emerald-600";
    if (changeRate >= 1) return "bg-emerald-700";
    if (changeRate >= 0) return "bg-emerald-800/50";
    if (changeRate >= -1) return "bg-red-800/50";
    if (changeRate >= -3) return "bg-red-700";
    return "bg-red-600";
  };

  const getSizeClass = (score: number) => {
    if (score >= 80) return "col-span-2 row-span-2";
    if (score >= 60) return "col-span-2";
    return "";
  };

  return (
    <div className="p-3 sm:p-4 bg-slate-800/30 rounded-xl border border-slate-700/50">
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        <h3 className="font-bold text-white flex items-center gap-2 text-sm sm:text-base">
          <span>🗺️</span>
          테마 히트맵
        </h3>
        <div className="flex items-center gap-2 text-xs">
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 bg-emerald-500 rounded" />
            <span className="text-slate-400">강세</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 bg-red-600 rounded" />
            <span className="text-slate-400">약세</span>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-4 sm:grid-cols-6 gap-1 sm:gap-1.5 auto-rows-fr">
        {themes.slice(0, 18).map((theme) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className={`${getHeatColor(theme.change_rate)} ${getSizeClass(theme.total_score)}
              p-1.5 sm:p-2 rounded-lg cursor-pointer hover:ring-2 hover:ring-white/30 transition-all min-h-[50px] sm:min-h-[60px] flex flex-col justify-between`}
          >
            <p className="text-[10px] sm:text-xs font-medium text-white truncate">{theme.theme_name}</p>
            <p className="text-xs sm:text-sm font-bold text-white">
              {theme.change_rate > 0 ? "+" : ""}
              {theme.change_rate.toFixed(1)}%
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
