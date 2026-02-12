"use client";

import { useMemo } from "react";
import type { NewsAnalysis } from "@/lib/api";

export default function NewsKeywordCloud({
  newsAnalysis,
}: {
  newsAnalysis?: NewsAnalysis[];
}) {
  const keywords = useMemo(() => {
    if (!newsAnalysis) return [];

    // 키 이슈에서 키워드 추출
    const wordCount: Record<string, number> = {};
    newsAnalysis.forEach((news) => {
      news.key_issues.forEach((issue) => {
        // 간단한 키워드 추출 (2글자 이상 단어)
        const words = issue
          .split(/[\s,·\-]+/)
          .filter((w) => w.length >= 2 && w.length <= 10);
        words.forEach((word) => {
          wordCount[word] = (wordCount[word] || 0) + 1;
        });
      });
    });

    return Object.entries(wordCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20)
      .map(([word, count]) => ({ word, count }));
  }, [newsAnalysis]);

  if (keywords.length === 0) return null;

  const maxCount = Math.max(...keywords.map((k) => k.count));

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>☁️</span>
        뉴스 키워드
      </h3>
      <div className="flex flex-wrap gap-2">
        {keywords.map((kw, i) => {
          const size = 0.7 + (kw.count / maxCount) * 0.6;
          const opacity = 0.5 + (kw.count / maxCount) * 0.5;
          return (
            <span
              key={i}
              className="px-2 py-1 bg-blue-500/20 text-blue-300 rounded transition-transform hover:scale-110"
              style={{
                fontSize: `${size}rem`,
                opacity,
              }}
            >
              {kw.word}
            </span>
          );
        })}
      </div>
    </div>
  );
}
