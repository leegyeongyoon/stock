"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import type { ThemeRanking } from "@/lib/api";

export type FilterGrade = "all" | "A" | "B" | "C" | "D" | "F";
export type FilterSentiment = "all" | "positive" | "neutral" | "negative";

export function ThemeSearchFilter({
  searchQuery,
  setSearchQuery,
  gradeFilter,
  setGradeFilter,
  sentimentFilter,
  setSentimentFilter,
}: {
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  gradeFilter: FilterGrade;
  setGradeFilter: (g: FilterGrade) => void;
  sentimentFilter: FilterSentiment;
  setSentimentFilter: (s: FilterSentiment) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 sm:gap-4 p-3 sm:p-4 bg-slate-800/30 rounded-xl border border-slate-700/50">
      {/* Search */}
      <div className="flex-1 min-w-[160px] sm:min-w-[200px]">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="테마명 검색..."
            className="w-full pl-9 pr-4 py-2 sm:py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {/* Grade filter */}
      <div className="flex items-center gap-1.5 sm:gap-2">
        <span className="text-xs text-slate-500 hidden sm:inline">등급:</span>
        <div className="flex gap-1">
          {(["all", "A", "B", "C", "D", "F"] as FilterGrade[]).map((g) => (
            <button
              key={g}
              onClick={() => setGradeFilter(g)}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                gradeFilter === g
                  ? g === "all"
                    ? "bg-blue-500 text-white"
                    : g === "A"
                    ? "bg-emerald-500 text-white"
                    : g === "B"
                    ? "bg-blue-500 text-white"
                    : g === "C"
                    ? "bg-amber-500 text-white"
                    : g === "D"
                    ? "bg-orange-500 text-white"
                    : "bg-red-500 text-white"
                  : "bg-slate-700 text-slate-400 hover:bg-slate-600"
              }`}
            >
              {g === "all" ? "전체" : g}
            </button>
          ))}
        </div>
      </div>

      {/* Sentiment filter - hide on very small screens */}
      <div className="hidden sm:flex items-center gap-2">
        <span className="text-xs text-slate-500">감성:</span>
        <div className="flex gap-1">
          {([
            { id: "all" as const, label: "전체" },
            { id: "positive" as const, label: "긍정" },
            { id: "neutral" as const, label: "중립" },
            { id: "negative" as const, label: "부정" },
          ]).map((s) => (
            <button
              key={s.id}
              onClick={() => setSentimentFilter(s.id)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                sentimentFilter === s.id
                  ? s.id === "positive"
                    ? "bg-emerald-500 text-white"
                    : s.id === "negative"
                    ? "bg-red-500 text-white"
                    : "bg-blue-500 text-white"
                  : "bg-slate-700 text-slate-400 hover:bg-slate-600"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export type ScreenerFilter = {
  minChangeRate: number;
  maxChangeRate: number;
  minScore: number;
  grades: string[];
  sentiments: string[];
  supplySignal: "all" | "buy" | "sell";
};

export function ThemeScreener({
  themes,
  onApply,
}: {
  themes: ThemeRanking[];
  onApply: (filtered: ThemeRanking[]) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [filters, setFilters] = useState<ScreenerFilter>({
    minChangeRate: -10,
    maxChangeRate: 30,
    minScore: 0,
    grades: ["A", "B", "C", "D", "F"],
    sentiments: ["positive", "neutral", "negative"],
    supplySignal: "all",
  });

  const applyFilters = () => {
    const filtered = themes.filter((t) => {
      if (t.change_rate < filters.minChangeRate || t.change_rate > filters.maxChangeRate) return false;
      if (t.total_score < filters.minScore) return false;
      if (!filters.grades.includes(t.grade)) return false;

      const sentiment = t.sentiment.includes("positive")
        ? "positive"
        : t.sentiment.includes("negative")
        ? "negative"
        : "neutral";
      if (!filters.sentiments.includes(sentiment)) return false;

      if (filters.supplySignal === "buy" && !t.supply_prediction.includes("매수세")) return false;
      if (filters.supplySignal === "sell" && !t.supply_prediction.includes("매도세")) return false;

      return true;
    });
    onApply(filtered);
    setIsOpen(false);
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-xs sm:text-sm text-white transition-colors"
      >
        <span>🔬</span>
        <span className="hidden sm:inline">스크리너</span>
      </button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-72 sm:w-80 p-4 bg-slate-800 rounded-xl border border-slate-700 shadow-xl z-50">
          <h4 className="font-bold text-white mb-4">고급 필터</h4>

          <div className="mb-4">
            <label className="text-xs text-slate-500 block mb-2">등락률 범위</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                value={filters.minChangeRate}
                onChange={(e) => setFilters({ ...filters, minChangeRate: Number(e.target.value) })}
                className="w-20 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-white text-sm"
              />
              <span className="text-slate-500">~</span>
              <input
                type="number"
                value={filters.maxChangeRate}
                onChange={(e) => setFilters({ ...filters, maxChangeRate: Number(e.target.value) })}
                className="w-20 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-white text-sm"
              />
              <span className="text-slate-500 text-sm">%</span>
            </div>
          </div>

          <div className="mb-4">
            <label className="text-xs text-slate-500 block mb-2">최소 종합점수: {filters.minScore}</label>
            <input
              type="range"
              min="0"
              max="100"
              value={filters.minScore}
              onChange={(e) => setFilters({ ...filters, minScore: Number(e.target.value) })}
              className="w-full"
            />
          </div>

          <div className="mb-4">
            <label className="text-xs text-slate-500 block mb-2">수급 신호</label>
            <div className="flex gap-2">
              {[
                { id: "all" as const, label: "전체" },
                { id: "buy" as const, label: "매수세" },
                { id: "sell" as const, label: "매도세" },
              ].map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setFilters({ ...filters, supplySignal: opt.id })}
                  className={`px-3 py-1 rounded text-xs ${
                    filters.supplySignal === opt.id ? "bg-blue-500 text-white" : "bg-slate-700 text-slate-400"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => setIsOpen(false)}
              className="flex-1 py-2 bg-slate-700 text-slate-300 rounded-lg text-sm"
            >
              취소
            </button>
            <button onClick={applyFilters} className="flex-1 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium">
              적용
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
