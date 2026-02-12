"use client";

import { useMemo } from "react";
import type { NewsAnalysis } from "@/lib/api";

export default function NewsSentimentDonut({
  newsAnalysis,
}: {
  newsAnalysis?: NewsAnalysis[];
}) {
  const sentimentData = useMemo(() => {
    if (!newsAnalysis)
      return { positive: 0, neutral: 0, negative: 0, total: 0 };

    const positive = newsAnalysis.filter((n) =>
      n.sentiment.includes("positive")
    ).length;
    const negative = newsAnalysis.filter((n) =>
      n.sentiment.includes("negative")
    ).length;
    const neutral = newsAnalysis.length - positive - negative;

    return { positive, neutral, negative, total: newsAnalysis.length };
  }, [newsAnalysis]);

  if (sentimentData.total === 0) return null;

  const { positive, neutral, negative, total } = sentimentData;
  const positivePercent = (positive / total) * 100;
  const neutralPercent = (neutral / total) * 100;
  const negativePercent = (negative / total) * 100;

  // SVG 도넛 차트 계산
  const radius = 40;
  const circumference = 2 * Math.PI * radius;

  const positiveOffset = 0;
  const neutralOffset = (positivePercent / 100) * circumference;
  const negativeOffset =
    ((positivePercent + neutralPercent) / 100) * circumference;

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>📊</span>
        뉴스 감성 분포
      </h3>

      <div className="flex items-center gap-6">
        {/* 도넛 차트 */}
        <div className="relative w-24 h-24">
          <svg
            viewBox="0 0 100 100"
            className="w-full h-full -rotate-90"
          >
            {/* 긍정 */}
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke="#10b981"
              strokeWidth="12"
              strokeDasharray={`${(positivePercent / 100) * circumference} ${circumference}`}
              strokeDashoffset={-positiveOffset}
            />
            {/* 중립 */}
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke="#64748b"
              strokeWidth="12"
              strokeDasharray={`${(neutralPercent / 100) * circumference} ${circumference}`}
              strokeDashoffset={-neutralOffset}
            />
            {/* 부정 */}
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke="#ef4444"
              strokeWidth="12"
              strokeDasharray={`${(negativePercent / 100) * circumference} ${circumference}`}
              strokeDashoffset={-negativeOffset}
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-lg font-bold text-white">{total}</span>
          </div>
        </div>

        {/* 범례 */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-emerald-500" />
            <span className="text-sm text-slate-300">긍정</span>
            <span className="text-sm font-mono text-emerald-400">
              {positive} ({positivePercent.toFixed(0)}%)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-slate-500" />
            <span className="text-sm text-slate-300">중립</span>
            <span className="text-sm font-mono text-slate-400">
              {neutral} ({neutralPercent.toFixed(0)}%)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <span className="text-sm text-slate-300">부정</span>
            <span className="text-sm font-mono text-red-400">
              {negative} ({negativePercent.toFixed(0)}%)
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
