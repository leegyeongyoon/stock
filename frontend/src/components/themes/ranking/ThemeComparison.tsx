"use client";

import type { ThemeRanking } from "@/lib/api";

export default function ThemeComparison({
  themes,
  selectedThemes,
  onToggleTheme,
  onClear,
}: {
  themes: ThemeRanking[];
  selectedThemes: string[];
  onToggleTheme: (code: string) => void;
  onClear: () => void;
}) {
  const comparedThemes = themes.filter((t) => selectedThemes.includes(t.theme_code));

  if (comparedThemes.length === 0) {
    return (
      <div className="p-4 bg-slate-800/30 rounded-xl border border-slate-700/50 border-dashed text-center">
        <p className="text-xs sm:text-sm text-slate-500">
          테마 카드의 비교 버튼을 클릭하여 비교할 테마를 선택하세요 (최대 3개)
        </p>
      </div>
    );
  }

  const getSentimentLabel = (s: string) =>
    s === "very_positive" ? "매우 긍정" : s === "positive" ? "긍정" : s === "negative" ? "부정" : "중립";

  return (
    <div className="p-3 sm:p-4 bg-slate-800/30 rounded-xl border border-slate-700/50">
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        <h3 className="font-bold text-white flex items-center gap-2 text-sm sm:text-base">
          <span>⚖️</span>
          테마 비교 ({comparedThemes.length}/3)
        </h3>
        <button
          onClick={onClear}
          className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-lg transition-colors"
        >
          초기화
        </button>
      </div>

      <div className="overflow-x-auto -mx-3 px-3 sm:mx-0 sm:px-0">
        <table className="w-full text-xs sm:text-sm min-w-[300px]">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left py-2 px-2 sm:px-3 text-slate-500 font-normal">항목</th>
              {comparedThemes.map((t) => (
                <th key={t.theme_code} className="text-center py-2 px-2 sm:px-3 text-white font-semibold">
                  {t.theme_name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {[
              {
                label: "등급",
                render: (t: ThemeRanking) => (
                  <span
                    className={`inline-flex w-7 h-7 sm:w-8 sm:h-8 rounded-lg font-bold items-center justify-center text-xs sm:text-sm ${
                      t.grade === "A"
                        ? "bg-emerald-500 text-white"
                        : t.grade === "B"
                        ? "bg-blue-500 text-white"
                        : t.grade === "C"
                        ? "bg-amber-500 text-white"
                        : t.grade === "D"
                        ? "bg-orange-500 text-white"
                        : "bg-red-500 text-white"
                    }`}
                  >
                    {t.grade}
                  </span>
                ),
              },
              {
                label: "등락률",
                render: (t: ThemeRanking) => (
                  <span
                    className={`font-bold ${
                      t.change_rate > 0 ? "text-emerald-400" : t.change_rate < 0 ? "text-red-400" : "text-slate-400"
                    }`}
                  >
                    {t.change_rate > 0 ? "+" : ""}
                    {t.change_rate.toFixed(2)}%
                  </span>
                ),
              },
              {
                label: "종합점수",
                render: (t: ThemeRanking) => <span className="text-white font-semibold">{t.total_score.toFixed(0)}점</span>,
              },
              {
                label: "모멘텀",
                render: (t: ThemeRanking) => <span className="text-emerald-400">{t.momentum_score.toFixed(0)}/30</span>,
              },
              {
                label: "뉴스",
                render: (t: ThemeRanking) => <span className="text-blue-400">{t.news_score.toFixed(0)}/25</span>,
              },
              {
                label: "감성",
                render: (t: ThemeRanking) => (
                  <span
                    className={
                      t.sentiment.includes("positive")
                        ? "text-emerald-400"
                        : t.sentiment.includes("negative")
                        ? "text-red-400"
                        : "text-slate-400"
                    }
                  >
                    {getSentimentLabel(t.sentiment)}
                  </span>
                ),
              },
              {
                label: "수급예측",
                render: (t: ThemeRanking) => (
                  <span
                    className={
                      t.supply_prediction.includes("매수세")
                        ? "text-emerald-400"
                        : t.supply_prediction.includes("매도세")
                        ? "text-red-400"
                        : "text-slate-400"
                    }
                  >
                    {t.supply_prediction}
                  </span>
                ),
              },
            ].map((row) => (
              <tr key={row.label}>
                <td className="py-2 px-2 sm:px-3 text-slate-400">{row.label}</td>
                {comparedThemes.map((t) => (
                  <td key={t.theme_code} className="text-center py-2 px-2 sm:px-3">
                    {row.render(t)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
