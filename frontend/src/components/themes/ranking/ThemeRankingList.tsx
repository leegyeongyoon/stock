"use client";

import type { ThemeRanking } from "@/lib/api";
import { getGradeColors } from "../common/GradeBadge";

export default function ThemeRankingList({
  rankings,
  onThemeClick,
  compareThemes,
  onToggleCompare,
  favorites,
  onToggleFavorite,
}: {
  rankings: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
  compareThemes: string[];
  onToggleCompare: (code: string) => void;
  favorites: string[];
  onToggleFavorite: (code: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
      {rankings.map((ranking) => {
        const grade = getGradeColors(ranking.grade);
        const isComparing = compareThemes.includes(ranking.theme_code);
        const canCompare = compareThemes.length < 3;
        const isFav = favorites.includes(ranking.theme_code);

        return (
          <div
            key={ranking.theme_code}
            className={`relative overflow-hidden rounded-xl p-3 sm:p-4 border transition-all duration-200 bg-slate-800/50 ${
              isComparing ? "border-blue-500 ring-2 ring-blue-500/30" : grade.border
            } hover:border-slate-500`}
          >
            {/* Action buttons */}
            <div className="absolute top-2 left-2 flex items-center gap-1">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleCompare(ranking.theme_code);
                }}
                disabled={!canCompare && !isComparing}
                className={`w-6 h-6 rounded flex items-center justify-center transition-all text-xs ${
                  isComparing
                    ? "bg-blue-500 text-white"
                    : canCompare
                    ? "bg-slate-700 text-slate-400 hover:bg-slate-600"
                    : "bg-slate-800 text-slate-600 cursor-not-allowed"
                }`}
              >
                {isComparing ? "✓" : "+"}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleFavorite(ranking.theme_code);
                }}
                className={`w-6 h-6 rounded flex items-center justify-center transition-all text-xs ${
                  isFav ? "bg-amber-500/20 text-amber-400" : "bg-slate-700 text-slate-500 hover:text-amber-400"
                }`}
              >
                {isFav ? "★" : "☆"}
              </button>
            </div>

            {/* Grade badge */}
            <div className="absolute top-3 right-3">
              <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-lg ${grade.bg} flex items-center justify-center`}>
                <span className={`text-xs sm:text-sm font-bold ${grade.text}`}>{ranking.grade}</span>
              </div>
            </div>

            {/* Main content */}
            <div
              onClick={() => onThemeClick(ranking.theme_code, ranking.theme_name)}
              className="cursor-pointer ml-6"
            >
              <div className="flex items-start gap-2 sm:gap-3 mb-2 sm:mb-3">
                <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-full bg-slate-700 flex items-center justify-center flex-shrink-0">
                  <span className="text-sm sm:text-lg font-bold text-white">{ranking.rank}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="font-bold text-white truncate text-sm sm:text-base">{ranking.theme_name}</h4>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span
                      className={`text-xs sm:text-sm font-medium ${
                        ranking.change_rate > 0
                          ? "text-emerald-400"
                          : ranking.change_rate < 0
                          ? "text-red-400"
                          : "text-slate-400"
                      }`}
                    >
                      {ranking.change_rate > 0 ? "+" : ""}
                      {ranking.change_rate.toFixed(2)}%
                    </span>
                    <span className="text-xs text-slate-500">
                      {ranking.total_score.toFixed(0)}점
                    </span>
                  </div>
                </div>
              </div>

              {/* Score bars */}
              <div className="space-y-1.5 sm:space-y-2 mb-2 sm:mb-3">
                {[
                  { label: "모멘텀", value: ranking.momentum_score, max: 30, color: "bg-emerald-500" },
                  { label: "뉴스", value: ranking.news_score, max: 25, color: "bg-blue-500" },
                  { label: "수급", value: ranking.supply_score, max: 25, color: "bg-amber-500" },
                ].map((bar) => (
                  <div key={bar.label} className="flex items-center gap-2">
                    <span className="text-[10px] sm:text-xs text-slate-500 w-10 sm:w-12">{bar.label}</span>
                    <div className="flex-1 h-1 sm:h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${bar.color}`}
                        style={{ width: `${(bar.value / bar.max) * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] sm:text-xs text-slate-400 w-5 sm:w-6">
                      {bar.value.toFixed(0)}
                    </span>
                  </div>
                ))}
              </div>

              {/* Sentiment & Supply */}
              <div className="flex items-center justify-between text-xs">
                <span
                  className={`px-1.5 sm:px-2 py-0.5 sm:py-1 rounded ${
                    ranking.sentiment.includes("positive")
                      ? "bg-emerald-500/20 text-emerald-400"
                      : ranking.sentiment.includes("negative")
                      ? "bg-red-500/20 text-red-400"
                      : "bg-slate-700 text-slate-400"
                  }`}
                >
                  {ranking.sentiment === "very_positive"
                    ? "매우 긍정"
                    : ranking.sentiment === "positive"
                    ? "긍정"
                    : ranking.sentiment === "negative"
                    ? "부정"
                    : "중립"}
                </span>
                <span
                  className={`px-1.5 sm:px-2 py-0.5 sm:py-1 rounded ${
                    ranking.supply_prediction.includes("매수세")
                      ? "bg-emerald-500/20 text-emerald-400"
                      : ranking.supply_prediction.includes("매도세")
                      ? "bg-red-500/20 text-red-400"
                      : "bg-slate-700 text-slate-400"
                  }`}
                >
                  {ranking.supply_prediction}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
