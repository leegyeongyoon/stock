"use client";

import { useState, useEffect } from "react";

const PHASE_CONFIG: Record<string, { bg: string; text: string; glow: string }> = {
  pre_market: { bg: "bg-purple-500", text: "text-purple-100", glow: "shadow-purple-500/50" },
  opening: { bg: "bg-yellow-500", text: "text-yellow-100", glow: "shadow-yellow-500/50" },
  morning: { bg: "bg-emerald-500", text: "text-emerald-100", glow: "shadow-emerald-500/50" },
  lunch: { bg: "bg-slate-500", text: "text-slate-100", glow: "shadow-slate-500/50" },
  afternoon: { bg: "bg-blue-500", text: "text-blue-100", glow: "shadow-blue-500/50" },
  closing: { bg: "bg-orange-500", text: "text-orange-100", glow: "shadow-orange-500/50" },
  after_market: { bg: "bg-slate-600", text: "text-slate-300", glow: "shadow-slate-600/50" },
};

export default function MarketHeader({
  phase,
  label,
  sentiment,
}: {
  phase: string;
  label: string;
  sentiment: string;
}) {
  const config = PHASE_CONFIG[phase] || PHASE_CONFIG.pre_market;

  return (
    <div className="flex items-center justify-between flex-wrap gap-3">
      <div className="flex items-center gap-2 sm:gap-4">
        <h1 className="text-xl sm:text-3xl font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
          테마 분석
        </h1>
        <span
          className={`px-2 sm:px-3 py-1 sm:py-1.5 rounded-full text-xs sm:text-sm font-semibold ${config.bg} ${config.text} shadow-lg ${config.glow}`}
        >
          {label}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-right">
          <p className="text-xs text-slate-500">시장 센티먼트</p>
          <p
            className={`text-base sm:text-lg font-bold ${
              sentiment === "강세"
                ? "text-emerald-400"
                : sentiment === "약세"
                ? "text-red-400"
                : "text-amber-400"
            }`}
          >
            {sentiment}
          </p>
        </div>
        <div
          className={`w-3 h-3 rounded-full animate-pulse ${
            sentiment === "강세"
              ? "bg-emerald-400"
              : sentiment === "약세"
              ? "bg-red-400"
              : "bg-amber-400"
          }`}
        />
      </div>
    </div>
  );
}

export function UpdateIndicator({
  lastUpdate,
  isLoading,
}: {
  lastUpdate?: Date;
  isLoading?: boolean;
}) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const getTimeAgo = () => {
    if (!lastUpdate) return "-";
    const diff = Math.floor((now.getTime() - lastUpdate.getTime()) / 1000);
    if (diff < 60) return `${diff}초 전`;
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    return `${Math.floor(diff / 3600)}시간 전`;
  };

  return (
    <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 rounded-lg">
      <div
        className={`w-2 h-2 rounded-full ${
          isLoading ? "bg-amber-400 animate-pulse" : "bg-emerald-400"
        }`}
      />
      <span className="text-xs text-slate-400">
        {isLoading ? "업데이트 중..." : `마지막 업데이트: ${getTimeAgo()}`}
      </span>
    </div>
  );
}
