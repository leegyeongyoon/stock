"use client";

import { useState } from "react";
import type { Theme, PeriodHotTheme } from "@/lib/api";
import ChangeRate from "../common/ChangeRate";

type PeriodType = "1d" | "3d" | "7d" | "30d";

function PeriodTabs({ active, onChange }: { active: PeriodType; onChange: (p: PeriodType) => void }) {
  const tabs: { id: PeriodType; label: string }[] = [
    { id: "1d", label: "1일" },
    { id: "3d", label: "3일" },
    { id: "7d", label: "7일" },
    { id: "30d", label: "30일" },
  ];

  return (
    <div className="flex gap-1 p-1 bg-slate-800/50 rounded-lg">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`px-2 sm:px-3 py-1 sm:py-1.5 rounded-md text-xs sm:text-sm font-medium transition-all ${
            active === tab.id
              ? "bg-blue-500 text-white"
              : "text-slate-400 hover:text-white hover:bg-slate-700/50"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function PeriodHotThemeCard({ theme, onClick }: { theme: PeriodHotTheme; onClick: () => void }) {
  const isPositive = theme.change_rate > 0;
  const isNegative = theme.change_rate < 0;

  return (
    <div
      onClick={onClick}
      className="group relative overflow-hidden rounded-xl sm:rounded-2xl p-3 sm:p-5 cursor-pointer transition-all duration-300 bg-slate-800/80 border border-slate-700/50 hover:border-slate-600 hover:bg-slate-800 min-w-[260px] sm:min-w-0 snap-start"
    >
      <div
        className={`absolute inset-0 opacity-20 ${
          isPositive
            ? "bg-gradient-to-br from-emerald-500/20 to-transparent"
            : isNegative
            ? "bg-gradient-to-br from-red-500/20 to-transparent"
            : "bg-gradient-to-br from-slate-500/20 to-transparent"
        }`}
      />
      <div className="relative">
        <div className="flex items-start justify-between mb-3 sm:mb-4">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-slate-700 flex items-center justify-center text-xs sm:text-sm font-bold text-white">
              {theme.rank}
            </span>
            <h3 className="font-bold text-sm sm:text-lg text-white group-hover:text-blue-300 transition-colors truncate max-w-[120px] sm:max-w-none">
              {theme.theme_name}
            </h3>
          </div>
          <div className="text-right">
            <ChangeRate value={theme.change_rate} size="md" />
            <p className="text-xs text-slate-500">{theme.period_days}일</p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 sm:gap-3 mb-3">
          <div className="text-center p-1.5 sm:p-2 bg-slate-900/50 rounded-lg">
            <p className="text-[10px] sm:text-xs text-slate-500">종목수</p>
            <p className="text-xs sm:text-sm font-semibold text-white">{theme.stock_count}</p>
          </div>
          <div className="text-center p-1.5 sm:p-2 bg-slate-900/50 rounded-lg">
            <p className="text-[10px] sm:text-xs text-slate-500">상승</p>
            <p className="text-xs sm:text-sm font-semibold text-emerald-400">{theme.up_count}</p>
          </div>
          <div className="text-center p-1.5 sm:p-2 bg-slate-900/50 rounded-lg">
            <p className="text-[10px] sm:text-xs text-slate-500">하락</p>
            <p className="text-xs sm:text-sm font-semibold text-red-400">{theme.down_count}</p>
          </div>
        </div>

        <div className="mb-2">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-slate-500">상승 비율</span>
            <span className="text-slate-400">{theme.up_ratio.toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400"
              style={{ width: `${theme.up_ratio}%` }}
            />
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-yellow-500 text-sm">👑</span>
            <span className="text-xs sm:text-sm text-slate-300">{theme.leader_stock || "-"}</span>
          </div>
          <span
            className={`px-2 py-1 text-xs rounded-full font-medium ${
              theme.strength === "강세"
                ? "bg-emerald-500/20 text-emerald-400"
                : theme.strength === "약세"
                ? "bg-red-500/20 text-red-400"
                : "bg-slate-700 text-slate-400"
            }`}
          >
            {theme.strength}
          </span>
        </div>

        {theme.top_gainers.length > 0 && (
          <div className="mt-2 pt-2 border-t border-slate-700/50 hidden sm:block">
            <p className="text-xs text-slate-500 mb-1.5">상승 TOP 3</p>
            <div className="flex flex-wrap gap-1.5">
              {theme.top_gainers.slice(0, 3).map((stock, i) => (
                <span key={i} className="px-2 py-0.5 bg-slate-900/50 rounded text-xs text-slate-300">
                  {stock.name} <span className="text-emerald-400">+{stock.change_rate.toFixed(1)}%</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function HotThemeCard({ theme, onClick }: { theme: Theme; onClick: () => void }) {
  const isPositive = theme.change_rate > 0;
  const isNegative = theme.change_rate < 0;

  return (
    <div
      onClick={onClick}
      className="group relative overflow-hidden rounded-xl sm:rounded-2xl p-3 sm:p-5 cursor-pointer transition-all duration-300 bg-slate-800/80 border border-slate-700/50 hover:border-slate-600 hover:bg-slate-800 min-w-[260px] sm:min-w-0 snap-start"
    >
      <div
        className={`absolute inset-0 opacity-20 ${
          isPositive
            ? "bg-gradient-to-br from-emerald-500/20 to-transparent"
            : isNegative
            ? "bg-gradient-to-br from-red-500/20 to-transparent"
            : "bg-gradient-to-br from-slate-500/20 to-transparent"
        }`}
      />
      <div className="relative">
        <div className="flex items-start justify-between mb-3 sm:mb-4">
          <div className="flex items-center gap-2">
            <h3 className="font-bold text-sm sm:text-lg text-white group-hover:text-blue-300 transition-colors">
              {theme.name}
            </h3>
            {theme.is_hot && (
              <span className="px-2 py-0.5 bg-gradient-to-r from-orange-500 to-red-500 text-white text-xs font-bold rounded-full animate-pulse">
                HOT
              </span>
            )}
          </div>
          <ChangeRate value={theme.change_rate} size="lg" />
        </div>

        <div className="grid grid-cols-3 gap-2 sm:gap-3 mb-3">
          <div className="text-center p-1.5 sm:p-2 bg-slate-900/50 rounded-lg">
            <p className="text-[10px] sm:text-xs text-slate-500">종목수</p>
            <p className="text-xs sm:text-sm font-semibold text-white">{theme.stock_count}</p>
          </div>
          <div className="text-center p-1.5 sm:p-2 bg-slate-900/50 rounded-lg">
            <p className="text-[10px] sm:text-xs text-slate-500">상승</p>
            <p className="text-xs sm:text-sm font-semibold text-emerald-400">{theme.up_count}</p>
          </div>
          <div className="text-center p-1.5 sm:p-2 bg-slate-900/50 rounded-lg">
            <p className="text-[10px] sm:text-xs text-slate-500">하락</p>
            <p className="text-xs sm:text-sm font-semibold text-red-400">{theme.down_count}</p>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-yellow-500 text-sm">👑</span>
            <span className="text-xs sm:text-sm text-slate-300">{theme.leader || "-"}</span>
          </div>
          <div className="flex gap-1.5">
            {theme.foreign_buying && (
              <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded-full font-medium">
                외인
              </span>
            )}
            {theme.inst_buying && (
              <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded-full font-medium">
                기관
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function HotThemeSection({
  periodHotThemes,
  fallbackThemes,
  periodLoading,
  hotPeriod,
  onHotPeriodChange,
  onThemeClick,
  onViewAll,
}: {
  periodHotThemes?: PeriodHotTheme[];
  fallbackThemes?: Theme[];
  periodLoading: boolean;
  hotPeriod: PeriodType;
  onHotPeriodChange: (p: PeriodType) => void;
  onThemeClick: (code: string, name: string) => void;
  onViewAll: () => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3 sm:mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-2 sm:gap-4">
          <h2 className="text-base sm:text-lg font-bold text-white">핫 테마</h2>
          <PeriodTabs active={hotPeriod} onChange={onHotPeriodChange} />
        </div>
        <button onClick={onViewAll} className="text-sm text-blue-400 hover:text-blue-300">
          전체보기 →
        </button>
      </div>

      {periodLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p className="text-slate-400 text-sm">테마 분석 중...</p>
          </div>
        </div>
      ) : periodHotThemes && periodHotThemes.length > 0 ? (
        <>
          {/* Mobile: horizontal scroll */}
          <div className="flex gap-3 overflow-x-auto pb-2 snap-x snap-mandatory md:hidden -mx-3 px-3">
            {periodHotThemes.slice(0, 6).map((theme) => (
              <PeriodHotThemeCard
                key={theme.theme_code}
                theme={theme}
                onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
              />
            ))}
          </div>
          {/* Desktop: grid */}
          <div className="hidden md:grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {periodHotThemes.slice(0, 6).map((theme) => (
              <PeriodHotThemeCard
                key={theme.theme_code}
                theme={theme}
                onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
              />
            ))}
          </div>
        </>
      ) : fallbackThemes && fallbackThemes.length > 0 ? (
        <>
          <div className="flex gap-3 overflow-x-auto pb-2 snap-x snap-mandatory md:hidden -mx-3 px-3">
            {fallbackThemes.slice(0, 6).map((theme) => (
              <HotThemeCard
                key={theme.code}
                theme={theme}
                onClick={() => onThemeClick(theme.code, theme.name)}
              />
            ))}
          </div>
          <div className="hidden md:grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {fallbackThemes.slice(0, 6).map((theme) => (
              <HotThemeCard
                key={theme.code}
                theme={theme}
                onClick={() => onThemeClick(theme.code, theme.name)}
              />
            ))}
          </div>
        </>
      ) : null}

      <p className="text-xs text-slate-500 mt-3 text-center">
        * {hotPeriod === "1d" ? "당일" : hotPeriod === "3d" ? "3일간" : hotPeriod === "7d" ? "7일간" : "30일간"} 테마 등락률 기준
      </p>
    </div>
  );
}

export { type PeriodType };
