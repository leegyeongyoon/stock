"use client";

import type { NewsAnalysis } from "@/lib/api";

function NewsCard({ news, onClick }: { news: NewsAnalysis; onClick: () => void }) {
  const isBullish = news.supply_prediction.includes("매수세");
  const isBearish = news.supply_prediction.includes("매도세");

  return (
    <div
      onClick={onClick}
      className={`relative overflow-hidden rounded-xl p-3 sm:p-5 cursor-pointer border transition-all duration-200 ${
        isBullish
          ? "bg-emerald-500/5 border-emerald-500/30 hover:border-emerald-500/50"
          : isBearish
          ? "bg-red-500/5 border-red-500/30 hover:border-red-500/50"
          : "bg-slate-800/50 border-slate-700/50 hover:border-slate-600"
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <h4 className="font-bold text-white text-sm sm:text-base">{news.theme_name}</h4>
        <div className="flex items-center gap-1.5">
          <div className="w-12 sm:w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-500 to-purple-500"
              style={{ width: `${news.confidence}%` }}
            />
          </div>
          <span className="text-xs text-slate-400">{news.confidence.toFixed(0)}%</span>
        </div>
      </div>

      <div className="space-y-2 sm:space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs sm:text-sm text-slate-400">뉴스 {news.news_count}건</span>
          <span
            className={`text-xs sm:text-sm font-semibold ${
              news.sentiment.includes("positive")
                ? "text-emerald-400"
                : news.sentiment.includes("negative")
                ? "text-red-400"
                : "text-slate-400"
            }`}
          >
            {news.sentiment.includes("very_positive")
              ? "매우 긍정"
              : news.sentiment.includes("very_negative")
              ? "매우 부정"
              : news.sentiment.includes("positive")
              ? "긍정"
              : news.sentiment.includes("negative")
              ? "부정"
              : "중립"}
          </span>
        </div>

        <div
          className={`p-2 sm:p-3 rounded-lg ${
            isBullish ? "bg-emerald-500/10" : isBearish ? "bg-red-500/10" : "bg-slate-700/50"
          }`}
        >
          <p
            className={`text-xs sm:text-sm font-medium ${
              isBullish ? "text-emerald-400" : isBearish ? "text-red-400" : "text-slate-300"
            }`}
          >
            {news.supply_prediction}
          </p>
        </div>

        {news.key_issues.length > 0 && (
          <ul className="space-y-0.5 sm:space-y-1">
            {news.key_issues.slice(0, 2).map((issue, i) => (
              <li key={i} className="text-[10px] sm:text-xs text-slate-400 truncate">
                • {issue}
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-xs text-blue-400 mt-2 sm:mt-3">상세보기 →</p>
    </div>
  );
}

export default function NewsSection({
  newsAnalysis,
}: {
  newsAnalysis?: NewsAnalysis[];
}) {
  if (!newsAnalysis || newsAnalysis.length === 0) {
    return (
      <div className="py-12 text-center text-slate-500 text-sm">뉴스 분석 데이터가 없습니다</div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
      {newsAnalysis.map((news) => (
        <NewsCard key={news.theme_name} news={news} onClick={() => {}} />
      ))}
    </div>
  );
}
