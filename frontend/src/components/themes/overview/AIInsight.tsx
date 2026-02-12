"use client";

import { useMemo } from "react";
import type { Theme, NewsAnalysis } from "@/lib/api";

export default function AIInsight({
  hotThemes,
  newsAnalysis,
  sentiment,
}: {
  hotThemes?: Theme[];
  newsAnalysis?: NewsAnalysis[];
  sentiment?: string;
}) {
  const insights = useMemo(() => {
    if (!hotThemes || !newsAnalysis) return null;

    const topThemes = hotThemes
      .slice(0, 3)
      .map((t) => t.name)
      .join(", ");
    const bullishThemes = newsAnalysis.filter((n) =>
      n.supply_prediction.includes("매수세")
    ).length;
    const bearishThemes = newsAnalysis.filter((n) =>
      n.supply_prediction.includes("매도세")
    ).length;

    const summary: string[] = [];

    if (sentiment === "강세") {
      summary.push("현재 시장은 전반적으로 강세 흐름을 보이고 있습니다.");
    } else if (sentiment === "약세") {
      summary.push("현재 시장은 약세 국면으로, 신중한 접근이 필요합니다.");
    } else {
      summary.push("현재 시장은 혼조세를 보이며 방향성을 탐색 중입니다.");
    }

    if (topThemes) {
      summary.push(`오늘의 주도 테마는 ${topThemes} 입니다.`);
    }

    if (bullishThemes > bearishThemes * 2) {
      summary.push("뉴스 기반 수급 분석 결과, 매수세가 우세한 테마가 많습니다.");
    } else if (bearishThemes > bullishThemes) {
      summary.push("수급 분석 결과, 일부 테마에서 매도 압력이 감지됩니다.");
    }

    if (sentiment === "강세" && bullishThemes > 3) {
      summary.push("단기 모멘텀 전략이 유효할 수 있습니다.");
    } else if (sentiment === "약세") {
      summary.push("리스크 관리에 주의하시고, 분할 매수를 고려하세요.");
    }

    return summary;
  }, [hotThemes, newsAnalysis, sentiment]);

  if (!insights) return null;

  return (
    <div className="relative overflow-hidden p-4 sm:p-5 bg-gradient-to-r from-blue-900/30 via-purple-900/20 to-slate-900/30 rounded-2xl border border-blue-500/20">
      <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 rounded-full blur-3xl" />
      <div className="relative">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg sm:text-xl">🤖</span>
          <h3 className="font-bold text-white text-sm sm:text-base">AI 마켓 인사이트</h3>
          <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded-full">
            Beta
          </span>
        </div>
        <div className="space-y-2">
          {insights.map((insight, i) => (
            <p key={i} className="text-xs sm:text-sm text-slate-300 leading-relaxed">
              {insight}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}
