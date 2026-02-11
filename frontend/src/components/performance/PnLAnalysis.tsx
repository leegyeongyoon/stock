"use client";

import type { PnLAnalysisData } from "@/lib/api";

interface Props {
  analysis: PnLAnalysisData | undefined;
}

export default function PnLAnalysis({ analysis }: Props) {
  if (!analysis) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 animate-pulse h-32" />
    );
  }

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <h3 className="font-semibold text-sm mb-3">수익/손실 분석</h3>

      {/* Summary */}
      <p className="text-sm text-slate-300 mb-3">{analysis.summary}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Winning factors */}
        <div className="space-y-1">
          <p className="text-xs font-medium text-green-400 mb-1">수익 요인</p>
          {analysis.winning_factors.length === 0 ? (
            <p className="text-xs text-slate-500">-</p>
          ) : (
            analysis.winning_factors.map((f, i) => (
              <p key={i} className="text-xs text-slate-300 pl-2 border-l-2 border-green-500/30">
                {f}
              </p>
            ))
          )}
        </div>

        {/* Losing factors */}
        <div className="space-y-1">
          <p className="text-xs font-medium text-red-400 mb-1">손실 요인</p>
          {analysis.losing_factors.length === 0 ? (
            <p className="text-xs text-slate-500">-</p>
          ) : (
            analysis.losing_factors.map((f, i) => (
              <p key={i} className="text-xs text-slate-300 pl-2 border-l-2 border-red-500/30">
                {f}
              </p>
            ))
          )}
        </div>
      </div>

      {/* Best/Worst + Recommendation */}
      <div className="mt-3 pt-3 border-t border-slate-700 flex flex-wrap gap-4 text-xs">
        {analysis.best_strategy !== "없음" && (
          <span className="text-slate-400">
            최고 전략: <span className="text-green-400">{analysis.best_strategy}</span>
          </span>
        )}
        {analysis.worst_strategy !== "없음" && (
          <span className="text-slate-400">
            최저 전략: <span className="text-red-400">{analysis.worst_strategy}</span>
          </span>
        )}
      </div>
      <p className="text-xs text-blue-400/80 mt-2">{analysis.recommendation}</p>
    </div>
  );
}
