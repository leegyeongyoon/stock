"use client";

import type { NewsAnalysis } from "@/lib/api";

export default function NewsTimeline({
  newsAnalysis,
}: {
  newsAnalysis?: NewsAnalysis[];
}) {
  if (!newsAnalysis || newsAnalysis.length === 0) {
    return (
      <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50 text-center">
        <p className="text-slate-500 text-sm">뉴스 데이터가 없습니다</p>
      </div>
    );
  }

  // 최근 뉴스 이슈들을 타임라인으로 표시
  const recentIssues = newsAnalysis
    .flatMap((n) =>
      n.key_issues.map((issue) => ({
        theme: n.theme_name,
        issue,
        sentiment: n.sentiment,
        confidence: n.confidence,
      }))
    )
    .slice(0, 8);

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>📰</span>
        실시간 뉴스 이슈
      </h3>

      <div className="relative">
        {/* 타임라인 선 */}
        <div className="absolute left-2 top-0 bottom-0 w-px bg-slate-700" />

        <div className="space-y-3">
          {recentIssues.map((item, i) => (
            <div key={i} className="relative pl-6">
              {/* 도트 */}
              <div
                className={`absolute left-0 top-1.5 w-4 h-4 rounded-full border-2 ${
                  item.sentiment.includes("positive")
                    ? "bg-emerald-500/20 border-emerald-500"
                    : item.sentiment.includes("negative")
                      ? "bg-red-500/20 border-red-500"
                      : "bg-slate-700 border-slate-500"
                }`}
              />

              <div className="bg-slate-800/50 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">
                    {item.theme}
                  </span>
                  <span
                    className={`text-xs ${
                      item.sentiment.includes("positive")
                        ? "text-emerald-400"
                        : item.sentiment.includes("negative")
                          ? "text-red-400"
                          : "text-slate-400"
                    }`}
                  >
                    {item.confidence.toFixed(0)}%
                  </span>
                </div>
                <p className="text-sm text-slate-300 line-clamp-2">
                  {item.issue}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
