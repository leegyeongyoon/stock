"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeMarketTiming({
  themes,
}: {
  themes: ThemeRanking[];
}) {
  const timingData = useMemo(() => {
    const avgChange =
      themes.reduce((sum, t) => sum + t.change_rate, 0) / themes.length;
    const positiveRatio =
      (themes.filter((t) => t.change_rate > 0).length / themes.length) * 100;
    const avgMomentum =
      themes.reduce((sum, t) => sum + t.momentum_score, 0) / themes.length;

    let signal: "buy" | "hold" | "sell" = "hold";
    let strength = 50;

    if (avgChange > 2 && positiveRatio > 70 && avgMomentum > 20) {
      signal = "buy";
      strength = Math.min(90, positiveRatio);
    } else if (avgChange < -2 || positiveRatio < 30) {
      signal = "sell";
      strength = Math.max(10, 100 - positiveRatio);
    }

    return { avgChange, positiveRatio, avgMomentum, signal, strength };
  }, [themes]);

  const signalColors: Record<
    string,
    { bg: string; text: string; label: string }
  > = {
    buy: {
      bg: "bg-emerald-500",
      text: "text-emerald-400",
      label: "매수 적기",
    },
    hold: { bg: "bg-amber-500", text: "text-amber-400", label: "관망" },
    sell: { bg: "bg-red-500", text: "text-red-400", label: "주의 필요" },
  };

  const style = signalColors[timingData.signal];

  return (
    <div
      className={`p-5 rounded-2xl border ${
        timingData.signal === "buy"
          ? "bg-emerald-900/20 border-emerald-500/30"
          : timingData.signal === "sell"
            ? "bg-red-900/20 border-red-500/30"
            : "bg-amber-900/20 border-amber-500/30"
      }`}
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-white flex items-center gap-2">
          <span>⏱️</span>
          마켓 타이밍
        </h3>
        <span
          className={`px-3 py-1 rounded-full text-sm font-bold ${style.bg} text-white`}
        >
          {style.label}
        </span>
      </div>

      {/* 게이지 */}
      <div className="relative h-4 bg-slate-700 rounded-full overflow-hidden mb-4">
        <div className="absolute inset-0 flex">
          <div className="flex-1 bg-red-500/30" />
          <div className="flex-1 bg-amber-500/30" />
          <div className="flex-1 bg-emerald-500/30" />
        </div>
        <div
          className={`absolute top-0 bottom-0 w-1 ${style.bg} transition-all`}
          style={{ left: `${timingData.strength}%` }}
        />
      </div>

      <div className="grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="text-xs text-slate-500">평균 등락률</p>
          <p
            className={`text-lg font-bold ${
              timingData.avgChange > 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {timingData.avgChange > 0 ? "+" : ""}
            {timingData.avgChange.toFixed(2)}%
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">상승 비율</p>
          <p className="text-lg font-bold text-white">
            {timingData.positiveRatio.toFixed(0)}%
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">평균 모멘텀</p>
          <p className="text-lg font-bold text-blue-400">
            {timingData.avgMomentum.toFixed(0)}
          </p>
        </div>
      </div>
    </div>
  );
}
