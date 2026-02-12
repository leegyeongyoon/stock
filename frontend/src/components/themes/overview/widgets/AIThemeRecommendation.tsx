"use client";

import { useMemo } from "react";
import type { ThemeRanking, NewsAnalysis } from "@/lib/api";

export default function AIThemeRecommendation({
  themes,
  newsAnalysis,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  newsAnalysis?: NewsAnalysis[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const recommendations = useMemo(() => {
    if (!themes || themes.length === 0) return [];

    // AI 추천 로직 (점수 기반)
    const scored = themes.map((theme) => {
      let score = 0;

      // 등급 점수
      if (theme.grade === "A") score += 30;
      else if (theme.grade === "B") score += 20;
      else if (theme.grade === "C") score += 10;

      // 모멘텀 점수
      score += theme.momentum_score;

      // 감성 점수
      if (theme.sentiment.includes("positive")) score += 15;
      if (theme.sentiment.includes("very_positive")) score += 10;

      // 수급 점수
      if (theme.supply_prediction.includes("매수세")) score += 20;

      // 뉴스 점수
      score += theme.news_score * 0.5;

      // 적당한 등락률 보너스 (너무 높지 않은)
      if (theme.change_rate > 0 && theme.change_rate < 5) score += 10;

      return { theme, score };
    });

    return scored
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map((s) => s.theme);
  }, [themes]);

  if (recommendations.length === 0) return null;

  return (
    <div className="p-5 bg-gradient-to-br from-violet-900/30 to-indigo-900/30 rounded-2xl border border-violet-500/20">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>🤖</span>
        AI 추천 테마
        <span className="px-2 py-0.5 bg-violet-500/20 text-violet-400 text-xs rounded-full ml-auto">
          AI
        </span>
      </h3>

      <div className="space-y-3">
        {recommendations.map((theme, i) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-xl cursor-pointer hover:bg-slate-800 transition-colors group"
          >
            <div
              className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-white ${
                i === 0
                  ? "bg-gradient-to-br from-amber-400 to-orange-500"
                  : i === 1
                    ? "bg-gradient-to-br from-slate-300 to-slate-400"
                    : "bg-gradient-to-br from-amber-600 to-amber-700"
              }`}
            >
              {i + 1}
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-white group-hover:text-violet-300 truncate">
                {theme.theme_name}
              </p>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    theme.grade === "A"
                      ? "bg-emerald-500/20 text-emerald-400"
                      : theme.grade === "B"
                        ? "bg-blue-500/20 text-blue-400"
                        : "bg-amber-500/20 text-amber-400"
                  }`}
                >
                  {theme.grade}
                </span>
                <span className="text-xs text-slate-500">
                  {theme.total_score.toFixed(0)}점
                </span>
              </div>
            </div>
            <div className="text-right">
              <p
                className={`font-bold ${
                  theme.change_rate > 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {theme.change_rate > 0 ? "+" : ""}
                {theme.change_rate.toFixed(2)}%
              </p>
              <p className="text-xs text-slate-500">
                {theme.supply_prediction}
              </p>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-slate-500 mt-3 text-center">
        * 등급, 모멘텀, 감성, 수급을 종합 분석한 AI 추천입니다
      </p>
    </div>
  );
}
