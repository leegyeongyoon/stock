"use client";

import type { ThemeRanking, NewsAnalysis } from "@/lib/api";

export default function ThemeDashboardWidget({
  themes,
  newsAnalysis,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  newsAnalysis?: NewsAnalysis[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const topTheme = themes[0];

  if (!topTheme) return null;

  return (
    <div className="p-5 bg-gradient-to-br from-purple-900/30 via-blue-900/20 to-slate-900/30 rounded-2xl border border-purple-500/20">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-white flex items-center gap-2">
          <span>🏆</span>
          오늘의 TOP 테마
        </h3>
        <span
          className={`px-2 py-1 rounded text-xs font-bold ${
            topTheme.grade === "A"
              ? "bg-emerald-500 text-white"
              : topTheme.grade === "B"
                ? "bg-blue-500 text-white"
                : "bg-amber-500 text-white"
          }`}
        >
          {topTheme.grade}등급
        </span>
      </div>

      <div
        onClick={() => onThemeClick(topTheme.theme_code, topTheme.theme_name)}
        className="cursor-pointer group"
      >
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-2xl font-bold text-white group-hover:text-blue-400 transition-colors">
            {topTheme.theme_name}
          </h4>
          <span
            className={`text-2xl font-bold font-mono ${
              topTheme.change_rate > 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {topTheme.change_rate > 0 ? "+" : ""}
            {topTheme.change_rate.toFixed(2)}%
          </span>
        </div>

        <div className="grid grid-cols-4 gap-3 mb-3">
          <div className="text-center">
            <p className="text-xs text-slate-500">종합점수</p>
            <p className="text-lg font-bold text-white">
              {topTheme.total_score.toFixed(0)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">모멘텀</p>
            <p className="text-lg font-bold text-emerald-400">
              {topTheme.momentum_score.toFixed(0)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">뉴스</p>
            <p className="text-lg font-bold text-blue-400">
              {topTheme.news_score.toFixed(0)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">수급</p>
            <p className="text-lg font-bold text-amber-400">
              {topTheme.supply_score.toFixed(0)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-1 rounded text-xs ${
              topTheme.sentiment.includes("positive")
                ? "bg-emerald-500/20 text-emerald-400"
                : topTheme.sentiment.includes("negative")
                  ? "bg-red-500/20 text-red-400"
                  : "bg-slate-700 text-slate-400"
            }`}
          >
            {topTheme.sentiment.includes("positive")
              ? "긍정적"
              : topTheme.sentiment.includes("negative")
                ? "부정적"
                : "중립"}
          </span>
          <span
            className={`px-2 py-1 rounded text-xs ${
              topTheme.supply_prediction.includes("매수세")
                ? "bg-emerald-500/20 text-emerald-400"
                : "bg-slate-700 text-slate-400"
            }`}
          >
            {topTheme.supply_prediction}
          </span>
        </div>
      </div>
    </div>
  );
}
