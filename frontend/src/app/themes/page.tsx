"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, useMemo, useEffect } from "react";
import {
  getMarketAnalysis,
  getPremarketAnalysis,
  getSupplyPrediction,
  getNewsAnalysis,
  getAllSupply,
  getNewsDetail,
  getStockDetail,
  getStockNews,
  getThemeRanking,
  getThemeDetail,
  getThemeNews,
  getHotThemesByPeriod,
  type Theme,
  type ThemeStock,
  type ThemeDetail,
  type NewsAnalysis,
  type SupplyFlow,
  type StockNewsResponse,
  type ThemeRanking,
  type PeriodHotTheme,
} from "@/lib/api";

// ============================================================================
// 탭 네비게이션
// ============================================================================
type TabType = "overview" | "themes" | "stocks" | "news";

function TabNav({ active, onChange }: { active: TabType; onChange: (tab: TabType) => void }) {
  const tabs: { id: TabType; label: string; icon: string }[] = [
    { id: "overview", label: "대시보드", icon: "📊" },
    { id: "themes", label: "핫테마", icon: "🔥" },
    { id: "stocks", label: "추천종목", icon: "💹" },
    { id: "news", label: "뉴스분석", icon: "📰" },
  ];

  return (
    <div className="flex gap-1 p-1 bg-slate-800/50 rounded-xl">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium transition-all ${
            active === tab.id
              ? "bg-white text-slate-900 shadow-lg"
              : "text-slate-400 hover:text-white hover:bg-slate-700/50"
          }`}
        >
          <span>{tab.icon}</span>
          <span>{tab.label}</span>
        </button>
      ))}
    </div>
  );
}

// ============================================================================
// 마켓 상태 헤더
// ============================================================================
function MarketHeader({ phase, label, sentiment }: { phase: string; label: string; sentiment: string }) {
  const phaseConfig: Record<string, { bg: string; text: string; glow: string }> = {
    pre_market: { bg: "bg-purple-500", text: "text-purple-100", glow: "shadow-purple-500/50" },
    opening: { bg: "bg-yellow-500", text: "text-yellow-100", glow: "shadow-yellow-500/50" },
    morning: { bg: "bg-emerald-500", text: "text-emerald-100", glow: "shadow-emerald-500/50" },
    lunch: { bg: "bg-slate-500", text: "text-slate-100", glow: "shadow-slate-500/50" },
    afternoon: { bg: "bg-blue-500", text: "text-blue-100", glow: "shadow-blue-500/50" },
    closing: { bg: "bg-orange-500", text: "text-orange-100", glow: "shadow-orange-500/50" },
    after_market: { bg: "bg-slate-600", text: "text-slate-300", glow: "shadow-slate-600/50" },
  };

  const config = phaseConfig[phase] || phaseConfig.pre_market;

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-4">
        <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
          테마 분석
        </h1>
        <span className={`px-3 py-1.5 rounded-full text-sm font-semibold ${config.bg} ${config.text} shadow-lg ${config.glow}`}>
          {label}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-right">
          <p className="text-xs text-slate-500">시장 센티먼트</p>
          <p className={`text-lg font-bold ${
            sentiment === "강세" ? "text-emerald-400" :
            sentiment === "약세" ? "text-red-400" : "text-amber-400"
          }`}>
            {sentiment}
          </p>
        </div>
        <div className={`w-3 h-3 rounded-full animate-pulse ${
          sentiment === "강세" ? "bg-emerald-400" :
          sentiment === "약세" ? "bg-red-400" : "bg-amber-400"
        }`} />
      </div>
    </div>
  );
}

// ============================================================================
// 대시보드 요약 카드
// ============================================================================
function SummaryCard({
  title,
  value,
  subtitle,
  trend,
  icon
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
  icon: string;
}) {
  return (
    <div className="relative overflow-hidden bg-gradient-to-br from-slate-800 to-slate-900 rounded-2xl p-5 border border-slate-700/50">
      <div className="absolute top-0 right-0 w-20 h-20 bg-gradient-to-br from-blue-500/10 to-purple-500/10 rounded-full blur-2xl" />
      <div className="relative">
        <div className="flex items-center justify-between mb-3">
          <span className="text-2xl">{icon}</span>
          {trend && (
            <span className={`text-xs px-2 py-1 rounded-full ${
              trend === "up" ? "bg-emerald-500/20 text-emerald-400" :
              trend === "down" ? "bg-red-500/20 text-red-400" :
              "bg-slate-500/20 text-slate-400"
            }`}>
              {trend === "up" ? "▲" : trend === "down" ? "▼" : "—"}
            </span>
          )}
        </div>
        <p className="text-sm text-slate-400 mb-1">{title}</p>
        <p className="text-2xl font-bold text-white">{value}</p>
        {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
      </div>
    </div>
  );
}

// ============================================================================
// 핫 테마 카드 (개선된 버전)
// ============================================================================
function HotThemeCard({ theme, onClick, isSelected }: { theme: Theme; onClick: () => void; isSelected: boolean }) {
  const isPositive = theme.change_rate > 0;
  const isNegative = theme.change_rate < 0;

  return (
    <div
      onClick={onClick}
      className={`group relative overflow-hidden rounded-2xl p-5 cursor-pointer transition-all duration-300 ${
        isSelected
          ? "bg-gradient-to-br from-blue-600/20 to-purple-600/20 border-2 border-blue-500/50 scale-[1.02]"
          : "bg-slate-800/80 border border-slate-700/50 hover:border-slate-600 hover:bg-slate-800"
      }`}
    >
      {/* 배경 그라데이션 */}
      <div className={`absolute inset-0 opacity-20 ${
        isPositive ? "bg-gradient-to-br from-emerald-500/20 to-transparent" :
        isNegative ? "bg-gradient-to-br from-red-500/20 to-transparent" :
        "bg-gradient-to-br from-slate-500/20 to-transparent"
      }`} />

      <div className="relative">
        {/* 헤더 */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            <h3 className="font-bold text-lg text-white group-hover:text-blue-300 transition-colors">
              {theme.name}
            </h3>
            {theme.is_hot && (
              <span className="px-2 py-0.5 bg-gradient-to-r from-orange-500 to-red-500 text-white text-xs font-bold rounded-full animate-pulse">
                HOT
              </span>
            )}
          </div>
          <div className={`text-right ${isPositive ? "text-emerald-400" : isNegative ? "text-red-400" : "text-slate-400"}`}>
            <p className="text-xl font-bold font-mono">
              {isPositive ? "+" : ""}{theme.change_rate.toFixed(2)}%
            </p>
          </div>
        </div>

        {/* 통계 */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="text-center p-2 bg-slate-900/50 rounded-lg">
            <p className="text-xs text-slate-500">종목수</p>
            <p className="text-sm font-semibold text-white">{theme.stock_count}</p>
          </div>
          <div className="text-center p-2 bg-slate-900/50 rounded-lg">
            <p className="text-xs text-slate-500">상승</p>
            <p className="text-sm font-semibold text-emerald-400">{theme.up_count}</p>
          </div>
          <div className="text-center p-2 bg-slate-900/50 rounded-lg">
            <p className="text-xs text-slate-500">하락</p>
            <p className="text-sm font-semibold text-red-400">{theme.down_count}</p>
          </div>
        </div>

        {/* 대장주 & 태그 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-yellow-500">👑</span>
            <span className="text-sm text-slate-300">{theme.leader || "-"}</span>
          </div>
          <div className="flex gap-1.5">
            {theme.foreign_buying && (
              <span className="px-2 py-1 bg-blue-500/20 text-blue-400 text-xs rounded-full font-medium">외인</span>
            )}
            {theme.inst_buying && (
              <span className="px-2 py-1 bg-purple-500/20 text-purple-400 text-xs rounded-full font-medium">기관</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// 기간별 핫 테마 카드
// ============================================================================
function PeriodHotThemeCard({
  theme,
  onClick
}: {
  theme: PeriodHotTheme;
  onClick: () => void;
}) {
  const isPositive = theme.change_rate > 0;
  const isNegative = theme.change_rate < 0;

  return (
    <div
      onClick={onClick}
      className="group relative overflow-hidden rounded-2xl p-5 cursor-pointer transition-all duration-300 bg-slate-800/80 border border-slate-700/50 hover:border-slate-600 hover:bg-slate-800"
    >
      {/* 배경 그라데이션 */}
      <div className={`absolute inset-0 opacity-20 ${
        isPositive ? "bg-gradient-to-br from-emerald-500/20 to-transparent" :
        isNegative ? "bg-gradient-to-br from-red-500/20 to-transparent" :
        "bg-gradient-to-br from-slate-500/20 to-transparent"
      }`} />

      <div className="relative">
        {/* 헤더 */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-sm font-bold text-white">
              {theme.rank}
            </span>
            <h3 className="font-bold text-lg text-white group-hover:text-blue-300 transition-colors">
              {theme.theme_name}
            </h3>
          </div>
          <div className={`text-right ${isPositive ? "text-emerald-400" : isNegative ? "text-red-400" : "text-slate-400"}`}>
            <p className="text-xl font-bold font-mono">
              {isPositive ? "+" : ""}{theme.change_rate.toFixed(2)}%
            </p>
            <p className="text-xs text-slate-500">{theme.period_days}일 수익률</p>
          </div>
        </div>

        {/* 통계 */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="text-center p-2 bg-slate-900/50 rounded-lg">
            <p className="text-xs text-slate-500">종목수</p>
            <p className="text-sm font-semibold text-white">{theme.stock_count}</p>
          </div>
          <div className="text-center p-2 bg-slate-900/50 rounded-lg">
            <p className="text-xs text-slate-500">상승</p>
            <p className="text-sm font-semibold text-emerald-400">{theme.up_count}</p>
          </div>
          <div className="text-center p-2 bg-slate-900/50 rounded-lg">
            <p className="text-xs text-slate-500">하락</p>
            <p className="text-sm font-semibold text-red-400">{theme.down_count}</p>
          </div>
        </div>

        {/* 상승률 바 */}
        <div className="mb-3">
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

        {/* 대장주 & 강도 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-yellow-500">👑</span>
            <span className="text-sm text-slate-300">{theme.leader_stock || "-"}</span>
          </div>
          <span className={`px-2 py-1 text-xs rounded-full font-medium ${
            theme.strength === "강세" ? "bg-emerald-500/20 text-emerald-400" :
            theme.strength === "약세" ? "bg-red-500/20 text-red-400" :
            "bg-slate-700 text-slate-400"
          }`}>
            {theme.strength}
          </span>
        </div>

        {/* 상위 종목 */}
        {theme.top_gainers.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-700/50">
            <p className="text-xs text-slate-500 mb-2">상승 TOP 3</p>
            <div className="flex flex-wrap gap-1.5">
              {theme.top_gainers.slice(0, 3).map((stock, i) => (
                <span key={i} className="px-2 py-1 bg-slate-900/50 rounded text-xs text-slate-300">
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

// ============================================================================
// 종목 카드 (그리드용)
// ============================================================================
function StockCard({ stock, rank, onClick }: { stock: ThemeStock; rank: number; onClick: () => void }) {
  const score = stock.score ?? stock.total_score ?? 0;
  const changeRate = stock.change_rate ?? 0;
  const isPositive = changeRate > 0;
  const isNegative = changeRate < 0;

  const getGradeColor = (s: number) => {
    if (s >= 70) return "from-emerald-500 to-emerald-600";
    if (s >= 50) return "from-amber-500 to-amber-600";
    return "from-slate-500 to-slate-600";
  };

  return (
    <div className="group relative overflow-hidden bg-slate-800/60 hover:bg-slate-800 rounded-xl p-4 border border-slate-700/50 hover:border-blue-500/50 transition-all duration-200">
      {/* 순위 뱃지 */}
      <div className="absolute -top-1 -left-1 w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-br-xl flex items-center justify-center">
        <span className="text-xs font-bold text-white">{rank}</span>
      </div>

      <div className="ml-4">
        {/* 종목명 & 등락률 */}
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="flex items-center gap-1.5">
              {stock.is_leader && <span className="text-yellow-400 text-sm">👑</span>}
              <h4 className="font-semibold text-white">{stock.name}</h4>
            </div>
            <p className="text-xs text-slate-500">{stock.code}</p>
          </div>
          <div className={`text-right ${isPositive ? "text-emerald-400" : isNegative ? "text-red-400" : "text-slate-400"}`}>
            <p className="text-lg font-bold font-mono">
              {isPositive ? "+" : ""}{changeRate.toFixed(2)}%
            </p>
          </div>
        </div>

        {/* 점수 바 */}
        <div className="relative h-2 bg-slate-700 rounded-full overflow-hidden mb-3">
          <div
            className={`absolute left-0 top-0 h-full bg-gradient-to-r ${getGradeColor(score)} transition-all duration-500`}
            style={{ width: `${score}%` }}
          />
        </div>

        {/* 하단 정보 */}
        <div className="flex items-center justify-between text-xs mb-3">
          <span className="text-slate-500">점수</span>
          <span className={`font-bold ${score >= 70 ? "text-emerald-400" : score >= 50 ? "text-amber-400" : "text-slate-400"}`}>
            {score.toFixed(0)}점
          </span>
        </div>

        {/* 상세보기 버튼 */}
        <button
          onClick={onClick}
          className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <span>📊</span>
          <span>상세 분석 보기</span>
        </button>
      </div>
    </div>
  );
}

// ============================================================================
// 뉴스 분석 카드
// ============================================================================
function NewsCard({ news, onClick }: { news: NewsAnalysis; onClick: () => void }) {
  const isBullish = news.supply_prediction.includes("매수세");
  const isBearish = news.supply_prediction.includes("매도세");

  return (
    <div
      onClick={onClick}
      className={`relative overflow-hidden rounded-xl p-5 cursor-pointer border transition-all duration-200 ${
        isBullish ? "bg-emerald-500/5 border-emerald-500/30 hover:border-emerald-500/50" :
        isBearish ? "bg-red-500/5 border-red-500/30 hover:border-red-500/50" :
        "bg-slate-800/50 border-slate-700/50 hover:border-slate-600"
      }`}
    >
      {/* 상단 */}
      <div className="flex items-start justify-between mb-4">
        <h4 className="font-bold text-white">{news.theme_name}</h4>
        <div className="flex items-center gap-2">
          <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-500 to-purple-500"
              style={{ width: `${news.confidence}%` }}
            />
          </div>
          <span className="text-xs text-slate-400">{news.confidence.toFixed(0)}%</span>
        </div>
      </div>

      {/* 본문 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-400">뉴스 {news.news_count}건</span>
          <span className={`text-sm font-semibold ${
            news.sentiment.includes("positive") ? "text-emerald-400" :
            news.sentiment.includes("negative") ? "text-red-400" : "text-slate-400"
          }`}>
            {news.sentiment.includes("very_positive") ? "매우 긍정" :
             news.sentiment.includes("positive") ? "긍정" :
             news.sentiment.includes("negative") ? "부정" :
             news.sentiment.includes("very_negative") ? "매우 부정" : "중립"}
          </span>
        </div>

        {/* 수급 예측 */}
        <div className={`p-3 rounded-lg ${
          isBullish ? "bg-emerald-500/10" : isBearish ? "bg-red-500/10" : "bg-slate-700/50"
        }`}>
          <p className={`text-sm font-medium ${
            isBullish ? "text-emerald-400" : isBearish ? "text-red-400" : "text-slate-300"
          }`}>
            {news.supply_prediction}
          </p>
        </div>

        {/* 핵심 이슈 */}
        {news.key_issues.length > 0 && (
          <ul className="space-y-1">
            {news.key_issues.slice(0, 2).map((issue, i) => (
              <li key={i} className="text-xs text-slate-400 truncate">• {issue}</li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-xs text-blue-400 mt-3 group-hover:text-blue-300">상세보기 →</p>
    </div>
  );
}

// ============================================================================
// 테마 랭킹 카드
// ============================================================================
function ThemeRankingCard({
  ranking,
  onClick
}: {
  ranking: ThemeRanking;
  onClick: () => void;
}) {
  const gradeColors: Record<string, { bg: string; text: string; border: string }> = {
    A: { bg: "bg-emerald-500", text: "text-emerald-100", border: "border-emerald-500/30" },
    B: { bg: "bg-blue-500", text: "text-blue-100", border: "border-blue-500/30" },
    C: { bg: "bg-amber-500", text: "text-amber-100", border: "border-amber-500/30" },
    D: { bg: "bg-orange-500", text: "text-orange-100", border: "border-orange-500/30" },
    F: { bg: "bg-red-500", text: "text-red-100", border: "border-red-500/30" },
  };

  const grade = gradeColors[ranking.grade] || gradeColors.C;

  return (
    <div
      onClick={onClick}
      className={`relative overflow-hidden rounded-xl p-4 cursor-pointer border transition-all duration-200 bg-slate-800/50 ${grade.border} hover:border-slate-500`}
    >
      {/* 순위 뱃지 */}
      <div className="absolute top-3 right-3 flex items-center gap-2">
        <div className={`w-8 h-8 rounded-lg ${grade.bg} flex items-center justify-center`}>
          <span className={`text-sm font-bold ${grade.text}`}>{ranking.grade}</span>
        </div>
      </div>

      {/* 상단: 순위 + 테마명 */}
      <div className="flex items-start gap-3 mb-3">
        <div className="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center">
          <span className="text-lg font-bold text-white">{ranking.rank}</span>
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="font-bold text-white truncate">{ranking.theme_name}</h4>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`text-sm font-medium ${
              ranking.change_rate > 0 ? "text-emerald-400" : ranking.change_rate < 0 ? "text-red-400" : "text-slate-400"
            }`}>
              {ranking.change_rate > 0 ? "+" : ""}{ranking.change_rate.toFixed(2)}%
            </span>
            <span className="text-xs text-slate-500">종합 {ranking.total_score.toFixed(0)}점</span>
          </div>
        </div>
      </div>

      {/* 점수 바 */}
      <div className="space-y-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 w-12">모멘텀</span>
          <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div className="h-full bg-emerald-500" style={{ width: `${(ranking.momentum_score / 30) * 100}%` }} />
          </div>
          <span className="text-xs text-slate-400 w-6">{ranking.momentum_score.toFixed(0)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 w-12">뉴스</span>
          <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500" style={{ width: `${(ranking.news_score / 25) * 100}%` }} />
          </div>
          <span className="text-xs text-slate-400 w-6">{ranking.news_score.toFixed(0)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 w-12">감성</span>
          <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div className="h-full bg-purple-500" style={{ width: `${(ranking.sentiment_score / 20) * 100}%` }} />
          </div>
          <span className="text-xs text-slate-400 w-6">{ranking.sentiment_score.toFixed(0)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 w-12">수급</span>
          <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div className="h-full bg-amber-500" style={{ width: `${(ranking.supply_score / 25) * 100}%` }} />
          </div>
          <span className="text-xs text-slate-400 w-6">{ranking.supply_score.toFixed(0)}</span>
        </div>
      </div>

      {/* 뉴스 감성 & 수급 예측 */}
      <div className="flex items-center justify-between text-xs">
        <span className={`px-2 py-1 rounded ${
          ranking.sentiment.includes("positive") ? "bg-emerald-500/20 text-emerald-400" :
          ranking.sentiment.includes("negative") ? "bg-red-500/20 text-red-400" :
          "bg-slate-700 text-slate-400"
        }`}>
          {ranking.sentiment === "very_positive" ? "매우 긍정" :
           ranking.sentiment === "positive" ? "긍정" :
           ranking.sentiment === "negative" ? "부정" :
           ranking.sentiment === "very_negative" ? "매우 부정" : "중립"}
        </span>
        <span className={`px-2 py-1 rounded ${
          ranking.supply_prediction.includes("매수세") ? "bg-emerald-500/20 text-emerald-400" :
          ranking.supply_prediction.includes("매도세") ? "bg-red-500/20 text-red-400" :
          "bg-slate-700 text-slate-400"
        }`}>
          {ranking.supply_prediction}
        </span>
      </div>

      {/* 주요 이슈 */}
      {ranking.key_issues.length > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-700/50">
          <p className="text-xs text-slate-500 truncate">{ranking.key_issues[0]}</p>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// 종목 상세 모달 (전체화면 모달)
// ============================================================================
function StockDetailModal({
  stockCode,
  stockName,
  onClose
}: {
  stockCode: string;
  stockName: string;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<"signal" | "technical" | "chart" | "news">("signal");

  const { data, isLoading } = useQuery({
    queryKey: ["stock-detail", stockCode],
    queryFn: () => getStockDetail(stockCode, stockName),
    enabled: !!stockCode,
  });

  // 종목 뉴스 조회 (2주)
  const { data: newsData, isLoading: newsLoading } = useQuery({
    queryKey: ["stock-news", stockCode, stockName],
    queryFn: () => getStockNews(stockCode, stockName, 14),
    enabled: !!stockCode && activeTab === "news",
  });

  const formatNumber = (num: number) => {
    if (Math.abs(num) >= 100000000) return (num / 100000000).toFixed(1) + "억";
    if (Math.abs(num) >= 10000) return (num / 10000).toFixed(1) + "만";
    return num.toLocaleString();
  };

  const gradeColors: Record<string, string> = {
    A: "from-emerald-400 to-emerald-600",
    B: "from-blue-400 to-blue-600",
    C: "from-amber-400 to-amber-600",
    D: "from-orange-400 to-orange-600",
    F: "from-red-400 to-red-600",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      {/* 백드롭 */}
      <div className="absolute inset-0 bg-black/80 backdrop-blur-md" />

      {/* 모달 패널 */}
      <div
        className="relative w-full max-w-4xl max-h-[90vh] bg-slate-900 rounded-2xl shadow-2xl overflow-hidden animate-modal-in border border-slate-700"
        onClick={(e) => e.stopPropagation()}
      >
        {isLoading ? (
          <div className="h-96 flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-slate-400 text-lg">종목 분석 중...</p>
            </div>
          </div>
        ) : data ? (
          <div className="h-full max-h-[90vh] flex flex-col">
            {/* 헤더 */}
            <div className="relative px-6 py-6 bg-gradient-to-r from-slate-800 via-slate-800 to-slate-900 border-b border-slate-700/50">
              <button
                onClick={onClose}
                className="absolute top-4 right-4 w-10 h-10 flex items-center justify-center rounded-full bg-slate-700 hover:bg-red-500 text-slate-300 hover:text-white transition-all text-lg font-bold"
              >
                ✕
              </button>

              <div className="flex items-start gap-5">
                {/* 등급 뱃지 */}
                <div className={`w-20 h-20 rounded-2xl bg-gradient-to-br ${gradeColors[data.buy_signal.grade]} flex flex-col items-center justify-center shadow-xl`}>
                  <span className="text-3xl font-black text-white">{data.buy_signal.grade}</span>
                  <span className="text-sm text-white/80 font-medium">{data.buy_signal.score}점</span>
                </div>

                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h2 className="text-2xl font-bold text-white">{stockName}</h2>
                    <span className="px-2 py-1 bg-slate-700 rounded text-sm text-slate-400">{stockCode}</span>
                  </div>
                  <div className="flex items-baseline gap-3 mt-2">
                    <span className={`text-3xl font-bold ${
                      data.change_rate > 0 ? "text-emerald-400" : data.change_rate < 0 ? "text-red-400" : "text-white"
                    }`}>
                      {data.current_price.toLocaleString()}원
                    </span>
                    <span className={`text-lg font-medium ${
                      data.change_rate > 0 ? "text-emerald-400" : data.change_rate < 0 ? "text-red-400" : "text-slate-400"
                    }`}>
                      {data.change_rate > 0 ? "▲" : data.change_rate < 0 ? "▼" : ""} {Math.abs(data.change_rate).toFixed(2)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* 추천 */}
              <div className={`mt-5 p-4 rounded-xl ${
                data.buy_signal.recommendation.includes("매수") ? "bg-emerald-500/10 border border-emerald-500/30" :
                data.buy_signal.recommendation.includes("비추천") ? "bg-red-500/10 border border-red-500/30" :
                "bg-amber-500/10 border border-amber-500/30"
              }`}>
                <p className={`font-semibold ${
                  data.buy_signal.recommendation.includes("매수") ? "text-emerald-400" :
                  data.buy_signal.recommendation.includes("비추천") ? "text-red-400" : "text-amber-400"
                }`}>
                  {data.buy_signal.recommendation}
                </p>
                <p className="text-xs text-slate-400 mt-1">{data.summary}</p>
              </div>
            </div>

            {/* 탭 */}
            <div className="px-6 py-3 border-b border-slate-700/50 flex gap-2">
              {[
                { id: "signal", label: "투자신호", icon: "📊" },
                { id: "technical", label: "기술분석", icon: "📈" },
                { id: "chart", label: "분봉", icon: "📉" },
                { id: "news", label: "뉴스", icon: "📰" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    activeTab === tab.id
                      ? "bg-blue-500 text-white"
                      : "text-slate-400 hover:text-white hover:bg-slate-700/50"
                  }`}
                >
                  <span>{tab.icon}</span>
                  <span>{tab.label}</span>
                </button>
              ))}
            </div>

            {/* 콘텐츠 */}
            <div className="flex-1 overflow-y-auto p-6">
              {activeTab === "signal" && (
                <div className="space-y-6">
                  {/* 긍정/부정 요인 */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
                      <h4 className="text-sm font-semibold text-emerald-400 mb-3">긍정 요인</h4>
                      <ul className="space-y-2">
                        {data.buy_signal.positives.map((p, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-emerald-300">
                            <span className="text-emerald-500">✓</span>
                            {p}
                          </li>
                        ))}
                        {data.buy_signal.positives.length === 0 && (
                          <li className="text-sm text-slate-500">없음</li>
                        )}
                      </ul>
                    </div>
                    <div className="p-4 rounded-xl bg-red-500/5 border border-red-500/20">
                      <h4 className="text-sm font-semibold text-red-400 mb-3">주의 요인</h4>
                      <ul className="space-y-2">
                        {data.buy_signal.negatives.map((n, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-red-300">
                            <span className="text-red-500">✗</span>
                            {n}
                          </li>
                        ))}
                        {data.buy_signal.negatives.length === 0 && (
                          <li className="text-sm text-slate-500">없음</li>
                        )}
                      </ul>
                    </div>
                  </div>

                  {/* 수급 분석 */}
                  <div>
                    <h4 className="text-sm font-semibold text-slate-300 mb-3">수급 분석</h4>
                    <div className="grid grid-cols-4 gap-3">
                      {[data.supply_3d, data.supply_7d, data.supply_10d, data.supply_30d].map((supply) => (
                        <div key={supply.days} className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-slate-500">{supply.days}일</span>
                            <span className={`text-xs px-1.5 py-0.5 rounded ${
                              supply.trend.includes("매집") ? "bg-emerald-500/20 text-emerald-400" :
                              supply.trend.includes("매도") ? "bg-red-500/20 text-red-400" :
                              "bg-slate-600 text-slate-400"
                            }`}>
                              {supply.trend}
                            </span>
                          </div>
                          <div className="text-xs space-y-1">
                            <div className="flex justify-between">
                              <span className="text-slate-500">외인</span>
                              <span className={supply.foreign_total > 0 ? "text-blue-400" : supply.foreign_total < 0 ? "text-red-400" : "text-slate-400"}>
                                {formatNumber(supply.foreign_total)}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-500">기관</span>
                              <span className={supply.inst_total > 0 ? "text-purple-400" : supply.inst_total < 0 ? "text-red-400" : "text-slate-400"}>
                                {formatNumber(supply.inst_total)}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* 거래량 & 볼린저 */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50">
                      <h4 className="text-sm font-semibold text-slate-300 mb-3">거래량</h4>
                      <div className="flex items-baseline gap-2 mb-2">
                        <span className="text-xl font-bold text-white">{formatNumber(data.volume)}</span>
                        <span className={`text-sm px-2 py-0.5 rounded ${
                          data.volume_analysis.trend === "급증" ? "bg-red-500/20 text-red-400" :
                          data.volume_analysis.trend === "증가" ? "bg-emerald-500/20 text-emerald-400" :
                          "bg-slate-600 text-slate-400"
                        }`}>
                          {data.volume_analysis.trend}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400">{data.volume_analysis.comment}</p>
                    </div>

                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50">
                      <h4 className="text-sm font-semibold text-slate-300 mb-3">볼린저밴드</h4>
                      <div className="flex items-baseline gap-2 mb-3">
                        <span className="text-xl font-bold text-white">{data.bb_position.zone}</span>
                        <span className="text-sm text-slate-400">{data.bb_position.position_pct.toFixed(0)}%</span>
                      </div>
                      {/* 볼린저 바 */}
                      <div className="relative h-2 bg-gradient-to-r from-emerald-600/50 via-amber-600/50 to-red-600/50 rounded-full">
                        <div
                          className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-lg border-2 border-blue-500"
                          style={{ left: `calc(${Math.min(100, Math.max(0, data.bb_position.position_pct))}% - 6px)` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === "technical" && (
                <div className="space-y-6">
                  {/* 가격 위치 */}
                  <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50">
                    <h4 className="text-sm font-semibold text-slate-300 mb-4">52주 가격 위치</h4>
                    <div className="grid grid-cols-2 gap-4 mb-4">
                      <div>
                        <p className="text-xs text-slate-500">52주 고점</p>
                        <p className="text-lg font-bold text-white">{data.price_position.high_52w.toLocaleString()}</p>
                        <p className={`text-sm ${data.price_position.from_high_pct > -10 ? "text-emerald-400" : "text-red-400"}`}>
                          {data.price_position.from_high_pct.toFixed(1)}%
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">52주 저점</p>
                        <p className="text-lg font-bold text-white">{data.price_position.low_52w.toLocaleString()}</p>
                        <p className="text-sm text-emerald-400">+{data.price_position.from_low_pct.toFixed(1)}%</p>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      {[
                        { label: "MA20", above: data.price_position.above_ma20 },
                        { label: "MA60", above: data.price_position.above_ma60 },
                        { label: "MA120", above: data.price_position.above_ma120 },
                      ].map((ma) => (
                        <span
                          key={ma.label}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium ${
                            ma.above ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
                          }`}
                        >
                          {ma.label} {ma.above ? "↑" : "↓"}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* 기술적 지표 */}
                  <div className="grid grid-cols-3 gap-4">
                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 text-center">
                      <p className="text-xs text-slate-500 mb-1">RSI (14)</p>
                      <p className={`text-2xl font-bold ${
                        data.indicators.rsi14 > 70 ? "text-red-400" :
                        data.indicators.rsi14 < 30 ? "text-emerald-400" : "text-amber-400"
                      }`}>
                        {data.indicators.rsi14.toFixed(1)}
                      </p>
                      <p className="text-xs text-slate-500">
                        {data.indicators.rsi14 > 70 ? "과매수" : data.indicators.rsi14 < 30 ? "과매도" : "중립"}
                      </p>
                    </div>
                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 text-center">
                      <p className="text-xs text-slate-500 mb-1">MACD</p>
                      <p className={`text-2xl font-bold ${
                        data.indicators.macd_hist > 0 ? "text-emerald-400" : "text-red-400"
                      }`}>
                        {data.indicators.macd.toFixed(0)}
                      </p>
                      <p className="text-xs text-slate-500">Sig: {data.indicators.macd_signal.toFixed(0)}</p>
                    </div>
                    <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 text-center">
                      <p className="text-xs text-slate-500 mb-1">Stoch %K</p>
                      <p className={`text-2xl font-bold ${
                        data.indicators.stoch_k > 80 ? "text-red-400" :
                        data.indicators.stoch_k < 20 ? "text-emerald-400" : "text-slate-300"
                      }`}>
                        {data.indicators.stoch_k.toFixed(1)}
                      </p>
                      <p className="text-xs text-slate-500">%D: {data.indicators.stoch_d.toFixed(1)}</p>
                    </div>
                  </div>

                  {/* 밸류에이션 */}
                  <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50">
                    <h4 className="text-sm font-semibold text-slate-300 mb-4">밸류에이션</h4>
                    <div className="grid grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-slate-500">시가총액</p>
                        <p className="text-sm font-bold text-white">{formatNumber(data.valuation.market_cap * 100000000)}원</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">PER</p>
                        <p className={`text-sm font-bold ${
                          data.valuation.per > 0 && data.valuation.per < 15 ? "text-emerald-400" : "text-white"
                        }`}>
                          {data.valuation.per > 0 ? data.valuation.per.toFixed(1) + "배" : "N/A"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">PBR</p>
                        <p className={`text-sm font-bold ${
                          data.valuation.pbr > 0 && data.valuation.pbr < 1 ? "text-emerald-400" : "text-white"
                        }`}>
                          {data.valuation.pbr > 0 ? data.valuation.pbr.toFixed(2) + "배" : "N/A"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">배당률</p>
                        <p className="text-sm font-bold text-white">
                          {data.valuation.dividend_yield > 0 ? data.valuation.dividend_yield.toFixed(2) + "%" : "N/A"}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === "chart" && (
                <div className="space-y-4">
                  {/* 당일 시세 */}
                  <div className="grid grid-cols-4 gap-3">
                    {[
                      { label: "시가", value: data.open_price, color: "text-white" },
                      { label: "고가", value: data.high_price, color: "text-red-400" },
                      { label: "저가", value: data.low_price, color: "text-blue-400" },
                      { label: "전일", value: data.prev_close, color: "text-slate-400" },
                    ].map((item) => (
                      <div key={item.label} className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50 text-center">
                        <p className="text-xs text-slate-500">{item.label}</p>
                        <p className={`text-sm font-mono font-bold ${item.color}`}>{item.value.toLocaleString()}</p>
                      </div>
                    ))}
                  </div>

                  {/* 분봉 테이블 */}
                  <div className="rounded-xl bg-slate-800/50 border border-slate-700/50 overflow-hidden">
                    <div className="p-3 border-b border-slate-700/50">
                      <h4 className="text-sm font-semibold text-slate-300">5분봉</h4>
                    </div>
                    {data.candles_5m.length > 0 ? (
                      <div className="max-h-64 overflow-y-auto">
                        <table className="w-full text-xs">
                          <thead className="bg-slate-800/80 sticky top-0">
                            <tr className="text-slate-500">
                              <th className="py-2 px-3 text-left">시간</th>
                              <th className="py-2 px-3 text-right">시가</th>
                              <th className="py-2 px-3 text-right">고가</th>
                              <th className="py-2 px-3 text-right">저가</th>
                              <th className="py-2 px-3 text-right">종가</th>
                              <th className="py-2 px-3 text-right">변동</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.candles_5m.slice(-10).reverse().map((candle, i) => {
                              const change = candle.close - candle.open;
                              const rate = candle.open > 0 ? (change / candle.open) * 100 : 0;
                              return (
                                <tr key={i} className="border-t border-slate-700/30">
                                  <td className="py-2 px-3 text-slate-400 font-mono">{candle.time}</td>
                                  <td className="py-2 px-3 text-right font-mono text-slate-300">{candle.open.toLocaleString()}</td>
                                  <td className="py-2 px-3 text-right font-mono text-red-400">{candle.high.toLocaleString()}</td>
                                  <td className="py-2 px-3 text-right font-mono text-blue-400">{candle.low.toLocaleString()}</td>
                                  <td className="py-2 px-3 text-right font-mono text-slate-300">{candle.close.toLocaleString()}</td>
                                  <td className={`py-2 px-3 text-right font-mono ${change > 0 ? "text-emerald-400" : change < 0 ? "text-red-400" : "text-slate-400"}`}>
                                    {rate > 0 ? "+" : ""}{rate.toFixed(2)}%
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="p-4 text-center text-slate-500 text-sm">분봉 데이터 없음</p>
                    )}
                  </div>
                </div>
              )}

              {activeTab === "news" && (
                <div className="space-y-4">
                  {newsLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : newsData && newsData.news_items.length > 0 ? (
                    <>
                      {/* 뉴스 요약 */}
                      <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="text-sm font-semibold text-slate-300">최근 2주 뉴스 분석</h4>
                          <span className="text-xs text-slate-500">{newsData.news_count}건</span>
                        </div>
                        <div className="grid grid-cols-3 gap-3">
                          <div className="text-center">
                            <p className="text-xs text-slate-500 mb-1">핫 스코어</p>
                            <p className={`text-lg font-bold ${
                              newsData.hot_score > 50 ? "text-red-400" :
                              newsData.hot_score > 30 ? "text-amber-400" : "text-slate-400"
                            }`}>
                              {newsData.hot_score.toFixed(0)}
                            </p>
                          </div>
                          <div className="text-center">
                            <p className="text-xs text-slate-500 mb-1">감성</p>
                            <p className={`text-lg font-bold ${
                              newsData.sentiment.includes("positive") ? "text-emerald-400" :
                              newsData.sentiment.includes("negative") ? "text-red-400" : "text-slate-400"
                            }`}>
                              {newsData.sentiment === "very_positive" ? "매우 긍정" :
                               newsData.sentiment === "positive" ? "긍정" :
                               newsData.sentiment === "negative" ? "부정" :
                               newsData.sentiment === "very_negative" ? "매우 부정" : "중립"}
                            </p>
                          </div>
                          <div className="text-center">
                            <p className="text-xs text-slate-500 mb-1">기사수</p>
                            <p className="text-lg font-bold text-blue-400">{newsData.news_count}</p>
                          </div>
                        </div>
                        {newsData.key_issues.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-slate-700/50">
                            <p className="text-xs text-slate-500 mb-2">주요 이슈</p>
                            <div className="flex flex-wrap gap-1.5">
                              {newsData.key_issues.map((issue, i) => (
                                <span key={i} className="px-2 py-1 rounded-md bg-slate-700/50 text-xs text-slate-300 truncate max-w-[200px]">
                                  {issue}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* 뉴스 목록 */}
                      <div className="space-y-2">
                        {newsData.news_items.map((item, i) => (
                          <a
                            key={i}
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block p-4 rounded-xl bg-slate-800/30 border border-slate-700/30 hover:bg-slate-800/60 hover:border-slate-600/50 transition-colors"
                          >
                            <div className="flex items-start gap-3">
                              <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm ${
                                item.sentiment === "positive" ? "bg-emerald-500/20 text-emerald-400" :
                                item.sentiment === "negative" ? "bg-red-500/20 text-red-400" :
                                "bg-slate-700 text-slate-400"
                              }`}>
                                {item.source === "naver" ? "N" :
                                 item.source === "google" ? "G" :
                                 item.source === "youtube" ? "Y" : "📰"}
                              </div>
                              <div className="flex-1 min-w-0">
                                <h5 className="text-sm font-medium text-white line-clamp-2 hover:text-blue-400 transition-colors">
                                  {item.title}
                                </h5>
                                {item.summary && (
                                  <p className="text-xs text-slate-500 mt-1 line-clamp-2">
                                    {item.summary}
                                  </p>
                                )}
                                <div className="flex items-center gap-3 mt-2">
                                  <span className="text-xs text-slate-600">{item.source}</span>
                                  {item.published_at && (
                                    <span className="text-xs text-slate-600">
                                      {new Date(item.published_at).toLocaleDateString("ko-KR")}
                                    </span>
                                  )}
                                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                                    item.sentiment === "positive" ? "bg-emerald-500/10 text-emerald-400" :
                                    item.sentiment === "negative" ? "bg-red-500/10 text-red-400" :
                                    "bg-slate-700 text-slate-400"
                                  }`}>
                                    {item.sentiment === "positive" ? "긍정" :
                                     item.sentiment === "negative" ? "부정" : "중립"}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </a>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-12 text-slate-500">
                      <span className="text-4xl mb-3">📰</span>
                      <p className="text-sm">최근 2주간 관련 뉴스가 없습니다</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center">
            <p className="text-slate-400">데이터를 불러올 수 없습니다</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// 테마 상세 모달
// ============================================================================
function ThemeDetailModal({
  themeCode,
  themeName,
  onClose,
  onStockClick
}: {
  themeCode: string;
  themeName: string;
  onClose: () => void;
  onStockClick: (code: string, name: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<"stocks" | "news">("stocks");

  // 테마 상세 정보
  const { data: themeDetail, isLoading: detailLoading } = useQuery({
    queryKey: ["theme-detail-modal", themeCode],
    queryFn: () => getThemeDetail(themeCode),
    enabled: !!themeCode,
  });

  // 테마 뉴스
  const { data: newsData, isLoading: newsLoading } = useQuery({
    queryKey: ["theme-news-modal", themeName],
    queryFn: () => getThemeNews(themeName),
    enabled: !!themeName && activeTab === "news",
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/80 backdrop-blur-md" />
      <div
        className="relative w-full max-w-5xl max-h-[90vh] bg-slate-900 rounded-2xl shadow-2xl overflow-hidden animate-modal-in border border-slate-700"
        onClick={(e) => e.stopPropagation()}
      >
        {detailLoading ? (
          <div className="h-96 flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-slate-400 text-lg">테마 분석 중...</p>
            </div>
          </div>
        ) : themeDetail ? (
          <div className="h-full max-h-[90vh] flex flex-col">
            {/* 헤더 */}
            <div className="relative px-6 py-6 bg-gradient-to-r from-slate-800 via-slate-800 to-slate-900 border-b border-slate-700/50">
              <button
                onClick={onClose}
                className="absolute top-4 right-4 w-10 h-10 flex items-center justify-center rounded-full bg-slate-700 hover:bg-red-500 text-slate-300 hover:text-white transition-all text-lg font-bold"
              >
                ✕
              </button>

              <div className="flex items-start gap-5">
                <div className={`w-20 h-20 rounded-2xl flex flex-col items-center justify-center shadow-xl ${
                  (themeDetail.change_rate || 0) > 3 ? "bg-gradient-to-br from-emerald-400 to-emerald-600" :
                  (themeDetail.change_rate || 0) > 0 ? "bg-gradient-to-br from-blue-400 to-blue-600" :
                  (themeDetail.change_rate || 0) > -2 ? "bg-gradient-to-br from-amber-400 to-amber-600" :
                  "bg-gradient-to-br from-red-400 to-red-600"
                }`}>
                  <span className="text-2xl font-black text-white">🔥</span>
                  <span className="text-xs text-white/80 font-medium">테마</span>
                </div>

                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h2 className="text-2xl font-bold text-white">{themeDetail.name}</h2>
                    <span className="px-2 py-1 bg-slate-700 rounded text-sm text-slate-400">{themeDetail.code}</span>
                  </div>
                  <div className="flex items-baseline gap-3 mt-2">
                    <span className={`text-3xl font-bold ${
                      (themeDetail.change_rate || 0) > 0 ? "text-emerald-400" : (themeDetail.change_rate || 0) < 0 ? "text-red-400" : "text-white"
                    }`}>
                      {(themeDetail.change_rate || 0) > 0 ? "+" : ""}{(themeDetail.change_rate || 0).toFixed(2)}%
                    </span>
                    <span className="text-sm text-slate-500">
                      종목 {themeDetail.stock_count || themeDetail.stocks?.length || 0}개 | 상승 {themeDetail.up_count || 0}개 | 하락 {themeDetail.down_count || 0}개
                    </span>
                  </div>
                </div>
              </div>

              {/* 요약 정보 */}
              <div className="mt-5 grid grid-cols-4 gap-3">
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/30 text-center">
                  <p className="text-xs text-slate-500">모멘텀</p>
                  <p className={`text-lg font-bold ${
                    themeDetail.momentum === "strong_up" ? "text-emerald-400" :
                    themeDetail.momentum === "up" ? "text-green-400" :
                    themeDetail.momentum === "down" ? "text-red-400" : "text-slate-400"
                  }`}>
                    {themeDetail.momentum === "strong_up" ? "강세" :
                     themeDetail.momentum === "up" ? "상승" :
                     themeDetail.momentum === "down" ? "하락" : "중립"}
                  </p>
                </div>
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/30 text-center">
                  <p className="text-xs text-slate-500">외인</p>
                  <p className={`text-lg font-bold ${themeDetail.foreign_buying ? "text-blue-400" : "text-slate-400"}`}>
                    {themeDetail.foreign_buying ? "매수세" : "-"}
                  </p>
                </div>
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/30 text-center">
                  <p className="text-xs text-slate-500">기관</p>
                  <p className={`text-lg font-bold ${themeDetail.inst_buying ? "text-purple-400" : "text-slate-400"}`}>
                    {themeDetail.inst_buying ? "매수세" : "-"}
                  </p>
                </div>
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/30 text-center">
                  <p className="text-xs text-slate-500">리더주</p>
                  <p className="text-lg font-bold text-white truncate">{themeDetail.leader || "-"}</p>
                </div>
              </div>

              {themeDetail.analysis_comment && (
                <div className="mt-4 p-3 rounded-xl bg-blue-500/10 border border-blue-500/30">
                  <p className="text-sm text-blue-300">{themeDetail.analysis_comment}</p>
                </div>
              )}
            </div>

            {/* 탭 */}
            <div className="px-6 py-3 border-b border-slate-700/50 flex gap-2">
              {[
                { id: "stocks", label: "종목 목록", icon: "📊" },
                { id: "news", label: "테마 뉴스", icon: "📰" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    activeTab === tab.id
                      ? "bg-blue-500 text-white"
                      : "text-slate-400 hover:text-white hover:bg-slate-700/50"
                  }`}
                >
                  <span>{tab.icon}</span>
                  <span>{tab.label}</span>
                </button>
              ))}
            </div>

            {/* 콘텐츠 */}
            <div className="flex-1 overflow-y-auto p-6">
              {activeTab === "stocks" && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {themeDetail.stocks?.map((stock, i) => (
                    <div
                      key={stock.code}
                      onClick={() => onStockClick(stock.code, stock.name)}
                      className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 hover:border-blue-500/50 cursor-pointer transition-all group"
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <span className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-xs font-bold text-white">
                          {i + 1}
                        </span>
                        <span className="font-semibold text-white truncate flex-1">{stock.name}</span>
                        {stock.is_leader && <span className="text-xs text-amber-400">👑</span>}
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-slate-500">{stock.code}</span>
                        <span className={`text-sm font-bold ${
                          stock.change_rate > 0 ? "text-emerald-400" : stock.change_rate < 0 ? "text-red-400" : "text-slate-400"
                        }`}>
                          {stock.change_rate > 0 ? "+" : ""}{stock.change_rate.toFixed(2)}%
                        </span>
                      </div>
                      <div className="mt-2 text-xs text-slate-500">
                        거래량 {(stock.volume / 10000).toFixed(0)}만
                      </div>
                      <div className="mt-2 pt-2 border-t border-slate-700/50">
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          stock.recommendation === "buy" || stock.recommendation === "strong_buy" ? "bg-emerald-500/20 text-emerald-400" :
                          stock.recommendation === "sell" ? "bg-red-500/20 text-red-400" :
                          "bg-slate-700 text-slate-400"
                        }`}>
                          {stock.recommendation === "strong_buy" ? "적극 매수" :
                           stock.recommendation === "buy" ? "매수" :
                           stock.recommendation === "hold" ? "관망" :
                           stock.recommendation === "sell" ? "매도" : "관망"}
                        </span>
                      </div>
                    </div>
                  ))}
                  {(!themeDetail.stocks || themeDetail.stocks.length === 0) && (
                    <div className="col-span-full py-12 text-center text-slate-500">
                      종목 데이터가 없습니다
                    </div>
                  )}
                </div>
              )}

              {activeTab === "news" && (
                <div className="space-y-4">
                  {newsLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : newsData && newsData.length > 0 ? (
                    <div className="space-y-3">
                      {newsData.map((item, i) => (
                        <a
                          key={i}
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block p-4 rounded-xl bg-slate-800/30 border border-slate-700/30 hover:bg-slate-800/60 hover:border-slate-600/50 transition-colors"
                        >
                          <div className="flex items-start gap-3">
                            <div className={`w-2 h-2 rounded-full mt-2 flex-shrink-0 ${
                              item.sentiment === "positive" || item.sentiment === "very_positive" ? "bg-emerald-400" :
                              item.sentiment === "negative" || item.sentiment === "very_negative" ? "bg-red-400" :
                              "bg-slate-400"
                            }`} />
                            <div className="flex-1 min-w-0">
                              <h5 className="font-medium text-white line-clamp-2 group-hover:text-blue-400">{item.title}</h5>
                              <div className="flex items-center gap-2 mt-2 text-xs text-slate-500">
                                <span>{item.source}</span>
                                <span>•</span>
                                <span className={`${
                                  item.sentiment === "positive" || item.sentiment === "very_positive" ? "text-emerald-400" :
                                  item.sentiment === "negative" || item.sentiment === "very_negative" ? "text-red-400" :
                                  "text-slate-400"
                                }`}>
                                  {item.sentiment === "positive" || item.sentiment === "very_positive" ? "긍정" :
                                   item.sentiment === "negative" || item.sentiment === "very_negative" ? "부정" : "중립"}
                                </span>
                              </div>
                            </div>
                          </div>
                        </a>
                      ))}
                    </div>
                  ) : (
                    <div className="py-12 text-center text-slate-500">
                      뉴스 데이터가 없습니다
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="h-96 flex items-center justify-center">
            <p className="text-slate-400">테마 정보를 불러올 수 없습니다</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// 기간 탭 컴포넌트
// ============================================================================
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
          className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
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

// ============================================================================
// 실시간 업데이트 인디케이터
// ============================================================================
function UpdateIndicator({ lastUpdate, isLoading }: { lastUpdate?: Date; isLoading?: boolean }) {
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
    <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 rounded-lg">
      <div className={`w-2 h-2 rounded-full ${isLoading ? "bg-amber-400 animate-pulse" : "bg-emerald-400"}`} />
      <span className="text-xs text-slate-400">
        {isLoading ? "업데이트 중..." : `마지막 업데이트: ${getTimeAgo()}`}
      </span>
    </div>
  );
}

// ============================================================================
// 테마 검색 및 필터
// ============================================================================
type FilterGrade = "all" | "A" | "B" | "C" | "D" | "F";
type FilterSentiment = "all" | "positive" | "neutral" | "negative";

function ThemeSearchFilter({
  searchQuery,
  setSearchQuery,
  gradeFilter,
  setGradeFilter,
  sentimentFilter,
  setSentimentFilter
}: {
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  gradeFilter: FilterGrade;
  setGradeFilter: (g: FilterGrade) => void;
  sentimentFilter: FilterSentiment;
  setSentimentFilter: (s: FilterSentiment) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 p-4 bg-slate-800/30 rounded-xl border border-slate-700/50">
      {/* 검색 */}
      <div className="flex-1 min-w-[200px]">
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">🔍</span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="테마명 검색..."
            className="w-full pl-10 pr-4 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {/* 등급 필터 */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">등급:</span>
        <div className="flex gap-1">
          {(["all", "A", "B", "C", "D", "F"] as FilterGrade[]).map((g) => (
            <button
              key={g}
              onClick={() => setGradeFilter(g)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                gradeFilter === g
                  ? g === "all" ? "bg-blue-500 text-white" :
                    g === "A" ? "bg-emerald-500 text-white" :
                    g === "B" ? "bg-blue-500 text-white" :
                    g === "C" ? "bg-amber-500 text-white" :
                    g === "D" ? "bg-orange-500 text-white" :
                    "bg-red-500 text-white"
                  : "bg-slate-700 text-slate-400 hover:bg-slate-600"
              }`}
            >
              {g === "all" ? "전체" : g}
            </button>
          ))}
        </div>
      </div>

      {/* 감성 필터 */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">감성:</span>
        <div className="flex gap-1">
          {([
            { id: "all", label: "전체" },
            { id: "positive", label: "긍정" },
            { id: "neutral", label: "중립" },
            { id: "negative", label: "부정" },
          ] as { id: FilterSentiment; label: string }[]).map((s) => (
            <button
              key={s.id}
              onClick={() => setSentimentFilter(s.id)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                sentimentFilter === s.id
                  ? s.id === "positive" ? "bg-emerald-500 text-white" :
                    s.id === "negative" ? "bg-red-500 text-white" :
                    "bg-blue-500 text-white"
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

// ============================================================================
// AI 마켓 인사이트
// ============================================================================
function AIMarketInsight({
  hotThemes,
  newsAnalysis,
  sentiment
}: {
  hotThemes?: Theme[];
  newsAnalysis?: NewsAnalysis[];
  sentiment?: string;
}) {
  const insights = useMemo(() => {
    if (!hotThemes || !newsAnalysis) return null;

    const topThemes = hotThemes.slice(0, 3).map(t => t.name).join(", ");
    const bullishThemes = newsAnalysis.filter(n => n.supply_prediction.includes("매수세")).length;
    const bearishThemes = newsAnalysis.filter(n => n.supply_prediction.includes("매도세")).length;
    const positiveNews = newsAnalysis.filter(n => n.sentiment.includes("positive")).length;

    const summary: string[] = [];

    // 시장 상황 분석
    if (sentiment === "강세") {
      summary.push("현재 시장은 전반적으로 강세 흐름을 보이고 있습니다.");
    } else if (sentiment === "약세") {
      summary.push("현재 시장은 약세 국면으로, 신중한 접근이 필요합니다.");
    } else {
      summary.push("현재 시장은 혼조세를 보이며 방향성을 탐색 중입니다.");
    }

    // 주도 테마
    if (topThemes) {
      summary.push(`오늘의 주도 테마는 ${topThemes} 입니다.`);
    }

    // 수급 분석
    if (bullishThemes > bearishThemes * 2) {
      summary.push("뉴스 기반 수급 분석 결과, 매수세가 우세한 테마가 많습니다.");
    } else if (bearishThemes > bullishThemes) {
      summary.push("수급 분석 결과, 일부 테마에서 매도 압력이 감지됩니다.");
    }

    // 투자 조언
    if (sentiment === "강세" && bullishThemes > 3) {
      summary.push("📈 단기 모멘텀 전략이 유효할 수 있습니다.");
    } else if (sentiment === "약세") {
      summary.push("⚠️ 리스크 관리에 주의하시고, 분할 매수를 고려하세요.");
    }

    return summary;
  }, [hotThemes, newsAnalysis, sentiment]);

  if (!insights) return null;

  return (
    <div className="relative overflow-hidden p-5 bg-gradient-to-r from-blue-900/30 via-purple-900/20 to-slate-900/30 rounded-2xl border border-blue-500/20">
      <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 rounded-full blur-3xl" />
      <div className="relative">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xl">🤖</span>
          <h3 className="font-bold text-white">AI 마켓 인사이트</h3>
          <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded-full">Beta</span>
        </div>
        <div className="space-y-2">
          {insights.map((insight, i) => (
            <p key={i} className="text-sm text-slate-300 leading-relaxed">
              {insight}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// 테마 히트맵
// ============================================================================
function ThemeHeatmap({
  themes,
  onThemeClick
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const getHeatColor = (changeRate: number, score: number) => {
    if (changeRate >= 5) return "bg-emerald-500";
    if (changeRate >= 3) return "bg-emerald-600";
    if (changeRate >= 1) return "bg-emerald-700";
    if (changeRate >= 0) return "bg-emerald-800/50";
    if (changeRate >= -1) return "bg-red-800/50";
    if (changeRate >= -3) return "bg-red-700";
    return "bg-red-600";
  };

  const getSizeClass = (score: number) => {
    if (score >= 80) return "col-span-2 row-span-2";
    if (score >= 60) return "col-span-2";
    return "";
  };

  return (
    <div className="p-4 bg-slate-800/30 rounded-xl border border-slate-700/50">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-white flex items-center gap-2">
          <span>🗺️</span>
          테마 히트맵
        </h3>
        <div className="flex items-center gap-2 text-xs">
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 bg-emerald-500 rounded" />
            <span className="text-slate-400">강세</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 bg-red-600 rounded" />
            <span className="text-slate-400">약세</span>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-6 gap-1.5 auto-rows-fr">
        {themes.slice(0, 18).map((theme) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className={`${getHeatColor(theme.change_rate, theme.total_score)} ${getSizeClass(theme.total_score)}
              p-2 rounded-lg cursor-pointer hover:ring-2 hover:ring-white/30 transition-all min-h-[60px] flex flex-col justify-between`}
          >
            <p className="text-xs font-medium text-white truncate">{theme.theme_name}</p>
            <p className="text-sm font-bold text-white">
              {theme.change_rate > 0 ? "+" : ""}{theme.change_rate.toFixed(1)}%
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// 테마 비교
// ============================================================================
function ThemeComparison({
  themes,
  selectedThemes,
  onToggleTheme,
  onClear
}: {
  themes: ThemeRanking[];
  selectedThemes: string[];
  onToggleTheme: (code: string) => void;
  onClear: () => void;
}) {
  const comparedThemes = themes.filter(t => selectedThemes.includes(t.theme_code));

  if (comparedThemes.length === 0) {
    return (
      <div className="p-4 bg-slate-800/30 rounded-xl border border-slate-700/50 border-dashed text-center">
        <p className="text-sm text-slate-500">테마 카드의 비교 버튼을 클릭하여 비교할 테마를 선택하세요 (최대 3개)</p>
      </div>
    );
  }

  return (
    <div className="p-4 bg-slate-800/30 rounded-xl border border-slate-700/50">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-white flex items-center gap-2">
          <span>⚖️</span>
          테마 비교 ({comparedThemes.length}/3)
        </h3>
        <button
          onClick={onClear}
          className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-lg transition-colors"
        >
          초기화
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left py-2 px-3 text-slate-500 font-normal">항목</th>
              {comparedThemes.map(t => (
                <th key={t.theme_code} className="text-center py-2 px-3 text-white font-semibold">
                  {t.theme_name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            <tr>
              <td className="py-2 px-3 text-slate-400">등급</td>
              {comparedThemes.map(t => (
                <td key={t.theme_code} className="text-center py-2 px-3">
                  <span className={`inline-block w-8 h-8 rounded-lg font-bold flex items-center justify-center ${
                    t.grade === "A" ? "bg-emerald-500 text-white" :
                    t.grade === "B" ? "bg-blue-500 text-white" :
                    t.grade === "C" ? "bg-amber-500 text-white" :
                    t.grade === "D" ? "bg-orange-500 text-white" :
                    "bg-red-500 text-white"
                  }`}>{t.grade}</span>
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 px-3 text-slate-400">등락률</td>
              {comparedThemes.map(t => (
                <td key={t.theme_code} className={`text-center py-2 px-3 font-bold ${
                  t.change_rate > 0 ? "text-emerald-400" : t.change_rate < 0 ? "text-red-400" : "text-slate-400"
                }`}>
                  {t.change_rate > 0 ? "+" : ""}{t.change_rate.toFixed(2)}%
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 px-3 text-slate-400">종합점수</td>
              {comparedThemes.map(t => (
                <td key={t.theme_code} className="text-center py-2 px-3 text-white font-semibold">
                  {t.total_score.toFixed(0)}점
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 px-3 text-slate-400">모멘텀</td>
              {comparedThemes.map(t => (
                <td key={t.theme_code} className="text-center py-2 px-3 text-emerald-400">
                  {t.momentum_score.toFixed(0)}/30
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 px-3 text-slate-400">뉴스</td>
              {comparedThemes.map(t => (
                <td key={t.theme_code} className="text-center py-2 px-3 text-blue-400">
                  {t.news_score.toFixed(0)}/25
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 px-3 text-slate-400">감성</td>
              {comparedThemes.map(t => (
                <td key={t.theme_code} className={`text-center py-2 px-3 ${
                  t.sentiment.includes("positive") ? "text-emerald-400" :
                  t.sentiment.includes("negative") ? "text-red-400" : "text-slate-400"
                }`}>
                  {t.sentiment === "very_positive" ? "매우 긍정" :
                   t.sentiment === "positive" ? "긍정" :
                   t.sentiment === "negative" ? "부정" : "중립"}
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 px-3 text-slate-400">수급예측</td>
              {comparedThemes.map(t => (
                <td key={t.theme_code} className={`text-center py-2 px-3 ${
                  t.supply_prediction.includes("매수세") ? "text-emerald-400" :
                  t.supply_prediction.includes("매도세") ? "text-red-400" : "text-slate-400"
                }`}>
                  {t.supply_prediction}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================================
// 테마 랭킹 카드 (비교 버튼 + 즐겨찾기 추가)
// ============================================================================
function ThemeRankingCardWithCompare({
  ranking,
  onClick,
  isComparing,
  onToggleCompare,
  canCompare,
  isFavorite,
  onToggleFavorite
}: {
  ranking: ThemeRanking;
  onClick: () => void;
  isComparing: boolean;
  onToggleCompare: () => void;
  canCompare: boolean;
  isFavorite?: boolean;
  onToggleFavorite?: () => void;
}) {
  const gradeColors: Record<string, { bg: string; text: string; border: string }> = {
    A: { bg: "bg-emerald-500", text: "text-emerald-100", border: "border-emerald-500/30" },
    B: { bg: "bg-blue-500", text: "text-blue-100", border: "border-blue-500/30" },
    C: { bg: "bg-amber-500", text: "text-amber-100", border: "border-amber-500/30" },
    D: { bg: "bg-orange-500", text: "text-orange-100", border: "border-orange-500/30" },
    F: { bg: "bg-red-500", text: "text-red-100", border: "border-red-500/30" },
  };

  const grade = gradeColors[ranking.grade] || gradeColors.C;

  return (
    <div
      className={`relative overflow-hidden rounded-xl p-4 border transition-all duration-200 bg-slate-800/50 ${
        isComparing ? "border-blue-500 ring-2 ring-blue-500/30" : grade.border
      } hover:border-slate-500`}
    >
      {/* 좌측 상단 버튼들 */}
      <div className="absolute top-2 left-2 flex items-center gap-1">
        {/* 비교 체크박스 */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggleCompare(); }}
          disabled={!canCompare && !isComparing}
          className={`w-6 h-6 rounded flex items-center justify-center transition-all ${
            isComparing ? "bg-blue-500 text-white" :
            canCompare ? "bg-slate-700 text-slate-400 hover:bg-slate-600" :
            "bg-slate-800 text-slate-600 cursor-not-allowed"
          }`}
        >
          {isComparing ? "✓" : "+"}
        </button>

        {/* 즐겨찾기 버튼 */}
        {onToggleFavorite && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleFavorite(); }}
            className={`w-6 h-6 rounded flex items-center justify-center transition-all ${
              isFavorite ? "bg-amber-500/20 text-amber-400" : "bg-slate-700 text-slate-500 hover:text-amber-400"
            }`}
          >
            {isFavorite ? "★" : "☆"}
          </button>
        )}
      </div>

      {/* 순위 뱃지 */}
      <div className="absolute top-3 right-3 flex items-center gap-2">
        <div className={`w-8 h-8 rounded-lg ${grade.bg} flex items-center justify-center`}>
          <span className={`text-sm font-bold ${grade.text}`}>{ranking.grade}</span>
        </div>
      </div>

      {/* 메인 콘텐츠 - 클릭 가능 */}
      <div onClick={onClick} className="cursor-pointer ml-6">
        {/* 상단: 순위 + 테마명 */}
        <div className="flex items-start gap-3 mb-3">
          <div className="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center">
            <span className="text-lg font-bold text-white">{ranking.rank}</span>
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="font-bold text-white truncate">{ranking.theme_name}</h4>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-sm font-medium ${
                ranking.change_rate > 0 ? "text-emerald-400" : ranking.change_rate < 0 ? "text-red-400" : "text-slate-400"
              }`}>
                {ranking.change_rate > 0 ? "+" : ""}{ranking.change_rate.toFixed(2)}%
              </span>
              <span className="text-xs text-slate-500">종합 {ranking.total_score.toFixed(0)}점</span>
            </div>
          </div>
        </div>

        {/* 점수 바 */}
        <div className="space-y-2 mb-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-12">모멘텀</span>
            <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500" style={{ width: `${(ranking.momentum_score / 30) * 100}%` }} />
            </div>
            <span className="text-xs text-slate-400 w-6">{ranking.momentum_score.toFixed(0)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-12">뉴스</span>
            <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500" style={{ width: `${(ranking.news_score / 25) * 100}%` }} />
            </div>
            <span className="text-xs text-slate-400 w-6">{ranking.news_score.toFixed(0)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-12">수급</span>
            <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <div className="h-full bg-amber-500" style={{ width: `${(ranking.supply_score / 25) * 100}%` }} />
            </div>
            <span className="text-xs text-slate-400 w-6">{ranking.supply_score.toFixed(0)}</span>
          </div>
        </div>

        {/* 뉴스 감성 & 수급 예측 */}
        <div className="flex items-center justify-between text-xs">
          <span className={`px-2 py-1 rounded ${
            ranking.sentiment.includes("positive") ? "bg-emerald-500/20 text-emerald-400" :
            ranking.sentiment.includes("negative") ? "bg-red-500/20 text-red-400" :
            "bg-slate-700 text-slate-400"
          }`}>
            {ranking.sentiment === "very_positive" ? "매우 긍정" :
             ranking.sentiment === "positive" ? "긍정" :
             ranking.sentiment === "negative" ? "부정" : "중립"}
          </span>
          <span className={`px-2 py-1 rounded ${
            ranking.supply_prediction.includes("매수세") ? "bg-emerald-500/20 text-emerald-400" :
            ranking.supply_prediction.includes("매도세") ? "bg-red-500/20 text-red-400" :
            "bg-slate-700 text-slate-400"
          }`}>
            {ranking.supply_prediction}
          </span>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// 외인/기관 수급 흐름 차트
// ============================================================================
function SupplyFlowChart({
  themes,
  onThemeClick
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  // 외인/기관 매수세가 있는 테마 필터링 (실제 데이터 기반으로 시뮬레이션)
  const supplyData = useMemo(() => {
    return themes.slice(0, 10).map(theme => {
      // 수급 예측 기반 데이터 생성
      const isForeignBuy = theme.supply_prediction.includes("외인") && theme.supply_prediction.includes("매수");
      const isInstBuy = theme.supply_prediction.includes("기관") && theme.supply_prediction.includes("매수");
      const isForeignSell = theme.supply_prediction.includes("외인") && theme.supply_prediction.includes("매도");
      const isInstSell = theme.supply_prediction.includes("기관") && theme.supply_prediction.includes("매도");

      return {
        ...theme,
        foreignFlow: isForeignBuy ? Math.random() * 100 + 50 : isForeignSell ? -(Math.random() * 100 + 50) : (Math.random() - 0.5) * 40,
        instFlow: isInstBuy ? Math.random() * 80 + 30 : isInstSell ? -(Math.random() * 80 + 30) : (Math.random() - 0.5) * 30,
      };
    });
  }, [themes]);

  const maxFlow = Math.max(...supplyData.map(d => Math.max(Math.abs(d.foreignFlow), Math.abs(d.instFlow))));

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-white flex items-center gap-2">
          <span>📊</span>
          외인/기관 수급 흐름
        </h3>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-blue-500" />
            <span className="text-slate-400">외인</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-purple-500" />
            <span className="text-slate-400">기관</span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {supplyData.map((theme) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className="group cursor-pointer hover:bg-slate-700/30 rounded-lg p-2 transition-colors"
          >
            <div className="flex items-center gap-3 mb-2">
              <span className="text-sm font-medium text-white truncate w-24">{theme.theme_name}</span>
              <div className="flex-1 relative h-6">
                {/* 중앙선 */}
                <div className="absolute left-1/2 top-0 bottom-0 w-px bg-slate-600" />

                {/* 외인 바 */}
                <div
                  className={`absolute top-0 h-3 rounded-sm transition-all ${
                    theme.foreignFlow >= 0 ? "bg-blue-500 left-1/2" : "bg-blue-500/60 right-1/2"
                  }`}
                  style={{
                    width: `${Math.abs(theme.foreignFlow) / maxFlow * 45}%`,
                    ...(theme.foreignFlow < 0 ? { right: '50%' } : { left: '50%' })
                  }}
                />

                {/* 기관 바 */}
                <div
                  className={`absolute bottom-0 h-3 rounded-sm transition-all ${
                    theme.instFlow >= 0 ? "bg-purple-500 left-1/2" : "bg-purple-500/60 right-1/2"
                  }`}
                  style={{
                    width: `${Math.abs(theme.instFlow) / maxFlow * 45}%`,
                    ...(theme.instFlow < 0 ? { right: '50%' } : { left: '50%' })
                  }}
                />
              </div>
              <span className={`text-xs font-mono w-16 text-right ${
                theme.change_rate > 0 ? "text-emerald-400" : theme.change_rate < 0 ? "text-red-400" : "text-slate-400"
              }`}>
                {theme.change_rate > 0 ? "+" : ""}{theme.change_rate.toFixed(1)}%
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-center gap-6 text-xs text-slate-500">
        <span>← 매도</span>
        <span>|</span>
        <span>매수 →</span>
      </div>
    </div>
  );
}

// ============================================================================
// 테마 트렌드 미니 차트
// ============================================================================
function ThemeTrendMiniChart({ themeCode, themeName }: { themeCode: string; themeName: string }) {
  // 7일간 추이 데이터 (시뮬레이션 - 실제로는 API에서 가져옴)
  const trendData = useMemo(() => {
    const data = [];
    let value = 100;
    for (let i = 0; i < 7; i++) {
      value = value + (Math.random() - 0.45) * 5;
      data.push(value);
    }
    return data;
  }, [themeCode]);

  const min = Math.min(...trendData);
  const max = Math.max(...trendData);
  const range = max - min || 1;
  const isUp = trendData[trendData.length - 1] > trendData[0];

  const points = trendData.map((v, i) => {
    const x = (i / (trendData.length - 1)) * 100;
    const y = 100 - ((v - min) / range) * 100;
    return `${x},${y}`;
  }).join(" ");

  return (
    <div className="w-20 h-8">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
        <polyline
          points={points}
          fill="none"
          stroke={isUp ? "#10b981" : "#ef4444"}
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

// ============================================================================
// 순위 변동 인디케이터
// ============================================================================
function RankChangeIndicator({ currentRank, previousRank }: { currentRank: number; previousRank?: number }) {
  if (!previousRank) return null;

  const change = previousRank - currentRank;

  if (change === 0) {
    return <span className="text-slate-500 text-xs">-</span>;
  }

  return (
    <span className={`flex items-center gap-0.5 text-xs font-medium ${
      change > 0 ? "text-emerald-400" : "text-red-400"
    }`}>
      {change > 0 ? "▲" : "▼"}
      {Math.abs(change)}
    </span>
  );
}

// ============================================================================
// 관심 테마 (로컬 스토리지 기반)
// ============================================================================
function useFavoriteThemes() {
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    const stored = localStorage.getItem("favoriteThemes");
    if (stored) {
      try {
        setFavorites(JSON.parse(stored));
      } catch {
        setFavorites([]);
      }
    }
  }, []);

  const toggleFavorite = (themeCode: string) => {
    setFavorites(prev => {
      const newFavorites = prev.includes(themeCode)
        ? prev.filter(c => c !== themeCode)
        : [...prev, themeCode];
      localStorage.setItem("favoriteThemes", JSON.stringify(newFavorites));
      return newFavorites;
    });
  };

  const isFavorite = (themeCode: string) => favorites.includes(themeCode);

  return { favorites, toggleFavorite, isFavorite };
}

// ============================================================================
// 실시간 뉴스 피드 타임라인
// ============================================================================
function NewsTimeline({ newsAnalysis }: { newsAnalysis?: NewsAnalysis[] }) {
  if (!newsAnalysis || newsAnalysis.length === 0) {
    return (
      <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50 text-center">
        <p className="text-slate-500 text-sm">뉴스 데이터가 없습니다</p>
      </div>
    );
  }

  // 최근 뉴스 이슈들을 타임라인으로 표시
  const recentIssues = newsAnalysis
    .flatMap(n => n.key_issues.map(issue => ({
      theme: n.theme_name,
      issue,
      sentiment: n.sentiment,
      confidence: n.confidence,
    })))
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
              <div className={`absolute left-0 top-1.5 w-4 h-4 rounded-full border-2 ${
                item.sentiment.includes("positive") ? "bg-emerald-500/20 border-emerald-500" :
                item.sentiment.includes("negative") ? "bg-red-500/20 border-red-500" :
                "bg-slate-700 border-slate-500"
              }`} />

              <div className="bg-slate-800/50 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">{item.theme}</span>
                  <span className={`text-xs ${
                    item.sentiment.includes("positive") ? "text-emerald-400" :
                    item.sentiment.includes("negative") ? "text-red-400" : "text-slate-400"
                  }`}>
                    {item.confidence.toFixed(0)}%
                  </span>
                </div>
                <p className="text-sm text-slate-300 line-clamp-2">{item.issue}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// 테마 거래대금 순위
// ============================================================================
function ThemeVolumeRanking({
  themes,
  onThemeClick
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  // 거래대금 시뮬레이션 (실제로는 API에서)
  const volumeData = useMemo(() => {
    return themes.slice(0, 8).map(theme => ({
      ...theme,
      volume: Math.floor(Math.random() * 5000 + 500), // 억 단위
      volumeChange: (Math.random() - 0.3) * 100,
    })).sort((a, b) => b.volume - a.volume);
  }, [themes]);

  const maxVolume = Math.max(...volumeData.map(d => d.volume));

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>💰</span>
        테마별 거래대금
      </h3>

      <div className="space-y-2">
        {volumeData.map((theme, i) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-700/30 cursor-pointer transition-colors"
          >
            <span className="w-5 text-center text-sm font-bold text-slate-500">{i + 1}</span>
            <span className="text-sm text-white truncate flex-1">{theme.theme_name}</span>
            <div className="w-24 h-2 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-amber-500 to-orange-500"
                style={{ width: `${(theme.volume / maxVolume) * 100}%` }}
              />
            </div>
            <div className="text-right w-20">
              <p className="text-sm font-mono text-white">{theme.volume.toLocaleString()}억</p>
              <p className={`text-xs ${theme.volumeChange > 0 ? "text-emerald-400" : "text-red-400"}`}>
                {theme.volumeChange > 0 ? "+" : ""}{theme.volumeChange.toFixed(0)}%
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// 테마 상관관계 매트릭스 (심플 버전)
// ============================================================================
function ThemeCorrelationBadge({ themes }: { themes: ThemeRanking[] }) {
  // 상관관계가 높은 테마 쌍 찾기 (시뮬레이션)
  const correlatedPairs = useMemo(() => {
    const pairs: { theme1: string; theme2: string; correlation: number }[] = [];
    const topThemes = themes.slice(0, 6);

    for (let i = 0; i < topThemes.length; i++) {
      for (let j = i + 1; j < topThemes.length; j++) {
        const correlation = Math.random() * 0.6 + 0.3; // 0.3 ~ 0.9
        if (correlation > 0.6) {
          pairs.push({
            theme1: topThemes[i].theme_name,
            theme2: topThemes[j].theme_name,
            correlation,
          });
        }
      }
    }

    return pairs.sort((a, b) => b.correlation - a.correlation).slice(0, 3);
  }, [themes]);

  if (correlatedPairs.length === 0) return null;

  return (
    <div className="p-4 bg-gradient-to-r from-indigo-900/30 to-purple-900/30 rounded-xl border border-indigo-500/20">
      <h4 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <span>🔗</span>
        연관 테마
      </h4>
      <div className="flex flex-wrap gap-2">
        {correlatedPairs.map((pair, i) => (
          <div key={i} className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800/50 rounded-full">
            <span className="text-xs text-slate-300">{pair.theme1}</span>
            <span className="text-indigo-400">↔</span>
            <span className="text-xs text-slate-300">{pair.theme2}</span>
            <span className="text-xs text-indigo-400 font-mono">{(pair.correlation * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// 테마 강도 게이지
// ============================================================================
function ThemeStrengthGauge({ theme }: { theme: ThemeRanking }) {
  const strength = theme.total_score;
  const angle = (strength / 100) * 180 - 90; // -90 to 90 degrees

  const getStrengthLabel = (score: number) => {
    if (score >= 80) return { label: "매우 강함", color: "text-emerald-400" };
    if (score >= 60) return { label: "강함", color: "text-green-400" };
    if (score >= 40) return { label: "보통", color: "text-amber-400" };
    if (score >= 20) return { label: "약함", color: "text-orange-400" };
    return { label: "매우 약함", color: "text-red-400" };
  };

  const { label, color } = getStrengthLabel(strength);

  return (
    <div className="relative w-32 h-20">
      {/* 반원 배경 */}
      <svg viewBox="0 0 100 60" className="w-full h-full">
        {/* 배경 호 */}
        <path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke="#334155"
          strokeWidth="8"
          strokeLinecap="round"
        />
        {/* 게이지 호 */}
        <path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke="url(#gaugeGradient)"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${(strength / 100) * 125.6} 125.6`}
        />
        {/* 그라데이션 정의 */}
        <defs>
          <linearGradient id="gaugeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="50%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#10b981" />
          </linearGradient>
        </defs>
        {/* 바늘 */}
        <line
          x1="50"
          y1="50"
          x2={50 + 30 * Math.cos((angle * Math.PI) / 180)}
          y2={50 - 30 * Math.sin((angle * Math.PI) / 180)}
          stroke="white"
          strokeWidth="2"
          strokeLinecap="round"
        />
        {/* 중앙점 */}
        <circle cx="50" cy="50" r="4" fill="white" />
      </svg>
      {/* 점수 & 라벨 */}
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 text-center">
        <p className="text-lg font-bold text-white">{strength.toFixed(0)}</p>
        <p className={`text-xs ${color}`}>{label}</p>
      </div>
    </div>
  );
}

// ============================================================================
// 테마별 뉴스 감성 분포 (도넛 차트)
// ============================================================================
function NewsSentimentDonut({ newsAnalysis }: { newsAnalysis?: NewsAnalysis[] }) {
  const sentimentData = useMemo(() => {
    if (!newsAnalysis) return { positive: 0, neutral: 0, negative: 0, total: 0 };

    const positive = newsAnalysis.filter(n => n.sentiment.includes("positive")).length;
    const negative = newsAnalysis.filter(n => n.sentiment.includes("negative")).length;
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
  const negativeOffset = ((positivePercent + neutralPercent) / 100) * circumference;

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>📊</span>
        뉴스 감성 분포
      </h3>

      <div className="flex items-center gap-6">
        {/* 도넛 차트 */}
        <div className="relative w-24 h-24">
          <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
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
            <span className="text-sm font-mono text-emerald-400">{positive} ({positivePercent.toFixed(0)}%)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-slate-500" />
            <span className="text-sm text-slate-300">중립</span>
            <span className="text-sm font-mono text-slate-400">{neutral} ({neutralPercent.toFixed(0)}%)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <span className="text-sm text-slate-300">부정</span>
            <span className="text-sm font-mono text-red-400">{negative} ({negativePercent.toFixed(0)}%)</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// 시간대별 테마 활성도
// ============================================================================
function ThemeActivityTimeline() {
  // 시간대별 활성도 시뮬레이션
  const activityData = useMemo(() => {
    const hours = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"];
    return hours.map(hour => ({
      hour,
      activity: Math.floor(Math.random() * 100),
      themes: Math.floor(Math.random() * 20 + 5),
    }));
  }, []);

  const maxActivity = Math.max(...activityData.map(d => d.activity));

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>⏰</span>
        시간대별 테마 활성도
      </h3>

      <div className="flex items-end gap-2 h-24">
        {activityData.map((data, i) => (
          <div key={i} className="flex-1 flex flex-col items-center gap-1">
            <div
              className="w-full bg-gradient-to-t from-blue-600 to-blue-400 rounded-t transition-all hover:from-blue-500 hover:to-blue-300"
              style={{ height: `${(data.activity / maxActivity) * 100}%` }}
              title={`${data.themes}개 테마 활성`}
            />
            <span className="text-xs text-slate-500">{data.hour.split(":")[0]}</span>
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
        <span>장 시작</span>
        <span>현재 시각</span>
        <span>장 마감</span>
      </div>
    </div>
  );
}

// ============================================================================
// 테마 투자 시뮬레이터 (간단 버전)
// ============================================================================
function ThemeSimulator({ theme }: { theme: ThemeRanking }) {
  const [investment, setInvestment] = useState(1000000);

  const simulatedReturn = useMemo(() => {
    // 테마 점수 기반 예상 수익률 시뮬레이션
    const baseReturn = theme.change_rate;
    const momentumBonus = (theme.momentum_score / 30) * 2;
    const sentimentBonus = theme.sentiment.includes("positive") ? 1 : theme.sentiment.includes("negative") ? -1 : 0;

    const expectedDaily = baseReturn + momentumBonus + sentimentBonus;
    const expectedWeekly = expectedDaily * 5 * 0.8; // 5일, 변동성 감소
    const expectedMonthly = expectedDaily * 22 * 0.6; // 22일, 변동성 더 감소

    return {
      daily: expectedDaily,
      weekly: expectedWeekly,
      monthly: expectedMonthly,
    };
  }, [theme]);

  return (
    <div className="p-4 bg-gradient-to-br from-emerald-900/20 to-blue-900/20 rounded-xl border border-emerald-500/20">
      <h4 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <span>🎯</span>
        투자 시뮬레이터
      </h4>

      <div className="mb-3">
        <label className="text-xs text-slate-500 block mb-1">투자금액</label>
        <input
          type="number"
          value={investment}
          onChange={(e) => setInvestment(Number(e.target.value))}
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-white text-sm"
          step={100000}
        />
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="text-center p-2 bg-slate-800/50 rounded-lg">
          <p className="text-xs text-slate-500">1일 예상</p>
          <p className={`text-sm font-bold ${simulatedReturn.daily > 0 ? "text-emerald-400" : "text-red-400"}`}>
            {(investment * simulatedReturn.daily / 100).toLocaleString()}원
          </p>
        </div>
        <div className="text-center p-2 bg-slate-800/50 rounded-lg">
          <p className="text-xs text-slate-500">1주 예상</p>
          <p className={`text-sm font-bold ${simulatedReturn.weekly > 0 ? "text-emerald-400" : "text-red-400"}`}>
            {(investment * simulatedReturn.weekly / 100).toLocaleString()}원
          </p>
        </div>
        <div className="text-center p-2 bg-slate-800/50 rounded-lg">
          <p className="text-xs text-slate-500">1달 예상</p>
          <p className={`text-sm font-bold ${simulatedReturn.monthly > 0 ? "text-emerald-400" : "text-red-400"}`}>
            {(investment * simulatedReturn.monthly / 100).toLocaleString()}원
          </p>
        </div>
      </div>

      <p className="text-xs text-slate-500 mt-2 text-center">* 시뮬레이션 결과이며 실제 수익을 보장하지 않습니다</p>
    </div>
  );
}

// ============================================================================
// 테마 종합 대시보드 위젯
// ============================================================================
function ThemeDashboardWidget({
  themes,
  newsAnalysis,
  onThemeClick
}: {
  themes: ThemeRanking[];
  newsAnalysis?: NewsAnalysis[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const topTheme = themes[0];

  if (!topTheme) return null;

  return (
    <div className="p-5 bg-gradient-to-br from-purple-900/30 via-blue-900/20 to-slate-900/30 rounded-2xl border border-purple-500/20">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-white flex items-center gap-2">
          <span>🏆</span>
          오늘의 TOP 테마
        </h3>
        <span className={`px-2 py-1 rounded text-xs font-bold ${
          topTheme.grade === "A" ? "bg-emerald-500 text-white" :
          topTheme.grade === "B" ? "bg-blue-500 text-white" :
          "bg-amber-500 text-white"
        }`}>{topTheme.grade}등급</span>
      </div>

      <div
        onClick={() => onThemeClick(topTheme.theme_code, topTheme.theme_name)}
        className="cursor-pointer group"
      >
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-2xl font-bold text-white group-hover:text-blue-400 transition-colors">
            {topTheme.theme_name}
          </h4>
          <span className={`text-2xl font-bold font-mono ${
            topTheme.change_rate > 0 ? "text-emerald-400" : "text-red-400"
          }`}>
            {topTheme.change_rate > 0 ? "+" : ""}{topTheme.change_rate.toFixed(2)}%
          </span>
        </div>

        <div className="grid grid-cols-4 gap-3 mb-3">
          <div className="text-center">
            <p className="text-xs text-slate-500">종합점수</p>
            <p className="text-lg font-bold text-white">{topTheme.total_score.toFixed(0)}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">모멘텀</p>
            <p className="text-lg font-bold text-emerald-400">{topTheme.momentum_score.toFixed(0)}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">뉴스</p>
            <p className="text-lg font-bold text-blue-400">{topTheme.news_score.toFixed(0)}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500">수급</p>
            <p className="text-lg font-bold text-amber-400">{topTheme.supply_score.toFixed(0)}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className={`px-2 py-1 rounded text-xs ${
            topTheme.sentiment.includes("positive") ? "bg-emerald-500/20 text-emerald-400" :
            topTheme.sentiment.includes("negative") ? "bg-red-500/20 text-red-400" :
            "bg-slate-700 text-slate-400"
          }`}>
            {topTheme.sentiment.includes("positive") ? "긍정적" : topTheme.sentiment.includes("negative") ? "부정적" : "중립"}
          </span>
          <span className={`px-2 py-1 rounded text-xs ${
            topTheme.supply_prediction.includes("매수세") ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-700 text-slate-400"
          }`}>
            {topTheme.supply_prediction}
          </span>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// 실시간 테마 알림 배너
// ============================================================================
function ThemeAlertBanner({ themes }: { themes?: ThemeRanking[] }) {
  const [alerts, setAlerts] = useState<{ theme: string; change: number; type: "surge" | "drop" }[]>([]);
  const [currentAlert, setCurrentAlert] = useState(0);

  useEffect(() => {
    if (!themes) return;

    // 급등/급락 테마 필터링 (3% 이상)
    const newAlerts = themes
      .filter(t => Math.abs(t.change_rate) >= 3)
      .map(t => ({
        theme: t.theme_name,
        change: t.change_rate,
        type: t.change_rate > 0 ? "surge" as const : "drop" as const,
      }))
      .slice(0, 5);

    setAlerts(newAlerts);
  }, [themes]);

  useEffect(() => {
    if (alerts.length === 0) return;
    const timer = setInterval(() => {
      setCurrentAlert(prev => (prev + 1) % alerts.length);
    }, 4000);
    return () => clearInterval(timer);
  }, [alerts.length]);

  if (alerts.length === 0) return null;

  const alert = alerts[currentAlert];

  return (
    <div className={`px-4 py-2 rounded-lg flex items-center justify-between ${
      alert.type === "surge"
        ? "bg-gradient-to-r from-emerald-900/50 to-emerald-800/30 border border-emerald-500/30"
        : "bg-gradient-to-r from-red-900/50 to-red-800/30 border border-red-500/30"
    }`}>
      <div className="flex items-center gap-3">
        <span className="text-lg">{alert.type === "surge" ? "🚀" : "📉"}</span>
        <div>
          <span className="text-sm font-medium text-white">{alert.theme}</span>
          <span className={`ml-2 text-sm font-bold ${
            alert.type === "surge" ? "text-emerald-400" : "text-red-400"
          }`}>
            {alert.change > 0 ? "+" : ""}{alert.change.toFixed(2)}%
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {alerts.map((_, i) => (
          <div
            key={i}
            className={`w-1.5 h-1.5 rounded-full transition-all ${
              i === currentAlert ? "bg-white" : "bg-white/30"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// 테마 스크리너 (고급 필터)
// ============================================================================
type ScreenerFilter = {
  minChangeRate: number;
  maxChangeRate: number;
  minScore: number;
  grades: string[];
  sentiments: string[];
  supplySignal: "all" | "buy" | "sell";
};

function ThemeScreener({
  themes,
  onApply
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
    const filtered = themes.filter(t => {
      if (t.change_rate < filters.minChangeRate || t.change_rate > filters.maxChangeRate) return false;
      if (t.total_score < filters.minScore) return false;
      if (!filters.grades.includes(t.grade)) return false;

      const sentiment = t.sentiment.includes("positive") ? "positive" :
                       t.sentiment.includes("negative") ? "negative" : "neutral";
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
        className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-white transition-colors"
      >
        <span>🔬</span>
        <span>스크리너</span>
      </button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-80 p-4 bg-slate-800 rounded-xl border border-slate-700 shadow-xl z-50">
          <h4 className="font-bold text-white mb-4">고급 필터</h4>

          {/* 등락률 범위 */}
          <div className="mb-4">
            <label className="text-xs text-slate-500 block mb-2">등락률 범위</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                value={filters.minChangeRate}
                onChange={e => setFilters({...filters, minChangeRate: Number(e.target.value)})}
                className="w-20 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-white text-sm"
              />
              <span className="text-slate-500">~</span>
              <input
                type="number"
                value={filters.maxChangeRate}
                onChange={e => setFilters({...filters, maxChangeRate: Number(e.target.value)})}
                className="w-20 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-white text-sm"
              />
              <span className="text-slate-500 text-sm">%</span>
            </div>
          </div>

          {/* 최소 점수 */}
          <div className="mb-4">
            <label className="text-xs text-slate-500 block mb-2">최소 종합점수: {filters.minScore}</label>
            <input
              type="range"
              min="0"
              max="100"
              value={filters.minScore}
              onChange={e => setFilters({...filters, minScore: Number(e.target.value)})}
              className="w-full"
            />
          </div>

          {/* 수급 신호 */}
          <div className="mb-4">
            <label className="text-xs text-slate-500 block mb-2">수급 신호</label>
            <div className="flex gap-2">
              {[
                { id: "all", label: "전체" },
                { id: "buy", label: "매수세" },
                { id: "sell", label: "매도세" },
              ].map(opt => (
                <button
                  key={opt.id}
                  onClick={() => setFilters({...filters, supplySignal: opt.id as any})}
                  className={`px-3 py-1 rounded text-xs ${
                    filters.supplySignal === opt.id
                      ? "bg-blue-500 text-white"
                      : "bg-slate-700 text-slate-400"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* 적용 버튼 */}
          <div className="flex gap-2">
            <button
              onClick={() => setIsOpen(false)}
              className="flex-1 py-2 bg-slate-700 text-slate-300 rounded-lg text-sm"
            >
              취소
            </button>
            <button
              onClick={applyFilters}
              className="flex-1 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium"
            >
              적용
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// 뉴스 키워드 클라우드
// ============================================================================
function NewsKeywordCloud({ newsAnalysis }: { newsAnalysis?: NewsAnalysis[] }) {
  const keywords = useMemo(() => {
    if (!newsAnalysis) return [];

    // 키 이슈에서 키워드 추출
    const wordCount: Record<string, number> = {};
    newsAnalysis.forEach(news => {
      news.key_issues.forEach(issue => {
        // 간단한 키워드 추출 (2글자 이상 단어)
        const words = issue.split(/[\s,·\-]+/).filter(w => w.length >= 2 && w.length <= 10);
        words.forEach(word => {
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

  const maxCount = Math.max(...keywords.map(k => k.count));

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

// ============================================================================
// 테마 포트폴리오 빌더
// ============================================================================
function ThemePortfolioBuilder({
  themes,
  onThemeClick
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const [portfolio, setPortfolio] = useState<{ code: string; name: string; weight: number }[]>([]);
  const [totalInvestment, setTotalInvestment] = useState(10000000);

  const addToPortfolio = (theme: ThemeRanking) => {
    if (portfolio.length >= 5) return;
    if (portfolio.find(p => p.code === theme.theme_code)) return;

    const newWeight = Math.floor(100 / (portfolio.length + 1));
    const updated = portfolio.map(p => ({ ...p, weight: newWeight }));
    updated.push({ code: theme.theme_code, name: theme.theme_name, weight: newWeight });
    setPortfolio(updated);
  };

  const removeFromPortfolio = (code: string) => {
    const filtered = portfolio.filter(p => p.code !== code);
    if (filtered.length > 0) {
      const newWeight = Math.floor(100 / filtered.length);
      setPortfolio(filtered.map(p => ({ ...p, weight: newWeight })));
    } else {
      setPortfolio([]);
    }
  };

  const updateWeight = (code: string, weight: number) => {
    setPortfolio(portfolio.map(p =>
      p.code === code ? { ...p, weight: Math.min(100, Math.max(0, weight)) } : p
    ));
  };

  const totalWeight = portfolio.reduce((sum, p) => sum + p.weight, 0);

  const expectedReturn = useMemo(() => {
    let totalReturn = 0;
    portfolio.forEach(p => {
      const theme = themes.find(t => t.theme_code === p.code);
      if (theme) {
        totalReturn += (theme.change_rate * p.weight) / 100;
      }
    });
    return totalReturn;
  }, [portfolio, themes]);

  return (
    <div className="p-5 bg-gradient-to-br from-slate-800/50 to-slate-900/50 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>📦</span>
        테마 포트폴리오 빌더
        <span className="text-xs text-slate-500 ml-auto">{portfolio.length}/5</span>
      </h3>

      {/* 투자금액 */}
      <div className="mb-4">
        <label className="text-xs text-slate-500 block mb-1">총 투자금액</label>
        <input
          type="number"
          value={totalInvestment}
          onChange={e => setTotalInvestment(Number(e.target.value))}
          className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm"
          step={1000000}
        />
      </div>

      {/* 포트폴리오 목록 */}
      {portfolio.length > 0 ? (
        <div className="space-y-2 mb-4">
          {portfolio.map(p => {
            const theme = themes.find(t => t.theme_code === p.code);
            return (
              <div key={p.code} className="flex items-center gap-2 p-2 bg-slate-800/50 rounded-lg">
                <span className="text-sm text-white flex-1 truncate">{p.name}</span>
                <input
                  type="number"
                  value={p.weight}
                  onChange={e => updateWeight(p.code, Number(e.target.value))}
                  className="w-16 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-white text-sm text-center"
                />
                <span className="text-xs text-slate-500">%</span>
                <span className="text-xs text-slate-400 w-20 text-right">
                  {((totalInvestment * p.weight) / 100).toLocaleString()}원
                </span>
                <button
                  onClick={() => removeFromPortfolio(p.code)}
                  className="text-red-400 hover:text-red-300"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-slate-500 text-center py-4 mb-4">
          아래 테마를 클릭하여 포트폴리오에 추가하세요
        </p>
      )}

      {/* 요약 */}
      {portfolio.length > 0 && (
        <div className="p-3 bg-slate-900/50 rounded-lg mb-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">총 비중</span>
            <span className={totalWeight === 100 ? "text-emerald-400" : "text-amber-400"}>
              {totalWeight}%
            </span>
          </div>
          <div className="flex items-center justify-between text-sm mt-1">
            <span className="text-slate-400">예상 수익률</span>
            <span className={expectedReturn > 0 ? "text-emerald-400" : "text-red-400"}>
              {expectedReturn > 0 ? "+" : ""}{expectedReturn.toFixed(2)}%
            </span>
          </div>
          <div className="flex items-center justify-between text-sm mt-1">
            <span className="text-slate-400">예상 수익금</span>
            <span className={expectedReturn > 0 ? "text-emerald-400" : "text-red-400"}>
              {(totalInvestment * expectedReturn / 100).toLocaleString()}원
            </span>
          </div>
        </div>
      )}

      {/* 추가 가능한 테마 */}
      <div className="flex flex-wrap gap-1">
        {themes.slice(0, 8).map(theme => (
          <button
            key={theme.theme_code}
            onClick={() => addToPortfolio(theme)}
            disabled={portfolio.length >= 5 || portfolio.find(p => p.code === theme.theme_code) !== undefined}
            className={`px-2 py-1 rounded text-xs transition-colors ${
              portfolio.find(p => p.code === theme.theme_code)
                ? "bg-blue-500/20 text-blue-400"
                : "bg-slate-700 text-slate-400 hover:bg-slate-600 disabled:opacity-50"
            }`}
          >
            {theme.theme_name}
          </button>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// 테마 메모/노트
// ============================================================================
function useThemeMemos() {
  const [memos, setMemos] = useState<Record<string, string>>({});

  useEffect(() => {
    const stored = localStorage.getItem("themeMemos");
    if (stored) {
      try {
        setMemos(JSON.parse(stored));
      } catch {
        setMemos({});
      }
    }
  }, []);

  const setMemo = (themeCode: string, memo: string) => {
    const updated = { ...memos, [themeCode]: memo };
    if (!memo) delete updated[themeCode];
    setMemos(updated);
    localStorage.setItem("themeMemos", JSON.stringify(updated));
  };

  const getMemo = (themeCode: string) => memos[themeCode] || "";

  return { memos, setMemo, getMemo };
}

// ============================================================================
// AI 테마 추천 위젯
// ============================================================================
function AIThemeRecommendation({
  themes,
  newsAnalysis,
  onThemeClick
}: {
  themes: ThemeRanking[];
  newsAnalysis?: NewsAnalysis[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const recommendations = useMemo(() => {
    if (!themes || themes.length === 0) return [];

    // AI 추천 로직 (점수 기반)
    const scored = themes.map(theme => {
      let score = 0;

      // 등급 점수
      if (theme.grade === "A") score += 30;
      else if (theme.grade === "B") score += 20;
      else if (theme.grade === "C") score += 10;

      // 모멘텀 점수
      score += theme.momentum_score;

      // 감성 점수
      if (theme.sentiment.includes("positive")) score += 15;
      if (theme.sentiment.includes("very_positive")) score += 10;

      // 수급 점수
      if (theme.supply_prediction.includes("매수세")) score += 20;

      // 뉴스 점수
      score += theme.news_score * 0.5;

      // 적당한 등락률 보너스 (너무 높지 않은)
      if (theme.change_rate > 0 && theme.change_rate < 5) score += 10;

      return { theme, score };
    });

    return scored
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map(s => s.theme);
  }, [themes]);

  if (recommendations.length === 0) return null;

  return (
    <div className="p-5 bg-gradient-to-br from-violet-900/30 to-indigo-900/30 rounded-2xl border border-violet-500/20">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>🤖</span>
        AI 추천 테마
        <span className="px-2 py-0.5 bg-violet-500/20 text-violet-400 text-xs rounded-full ml-auto">AI</span>
      </h3>

      <div className="space-y-3">
        {recommendations.map((theme, i) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-xl cursor-pointer hover:bg-slate-800 transition-colors group"
          >
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-white ${
              i === 0 ? "bg-gradient-to-br from-amber-400 to-orange-500" :
              i === 1 ? "bg-gradient-to-br from-slate-300 to-slate-400" :
              "bg-gradient-to-br from-amber-600 to-amber-700"
            }`}>
              {i + 1}
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-white group-hover:text-violet-300 truncate">{theme.theme_name}</p>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`text-xs px-1.5 py-0.5 rounded ${
                  theme.grade === "A" ? "bg-emerald-500/20 text-emerald-400" :
                  theme.grade === "B" ? "bg-blue-500/20 text-blue-400" :
                  "bg-amber-500/20 text-amber-400"
                }`}>{theme.grade}</span>
                <span className="text-xs text-slate-500">{theme.total_score.toFixed(0)}점</span>
              </div>
            </div>
            <div className="text-right">
              <p className={`font-bold ${
                theme.change_rate > 0 ? "text-emerald-400" : "text-red-400"
              }`}>
                {theme.change_rate > 0 ? "+" : ""}{theme.change_rate.toFixed(2)}%
              </p>
              <p className="text-xs text-slate-500">{theme.supply_prediction}</p>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-slate-500 mt-3 text-center">
        * 등급, 모멘텀, 감성, 수급을 종합 분석한 AI 추천입니다
      </p>
    </div>
  );
}

// ============================================================================
// 메인 페이지
// ============================================================================
export default function ThemesPage() {
  const [activeTab, setActiveTab] = useState<TabType>("overview");
  const [selectedTheme, setSelectedTheme] = useState<string | null>(null);
  const [stockModal, setStockModal] = useState<{ code: string; name: string } | null>(null);
  const [themeModal, setThemeModal] = useState<{ code: string; name: string } | null>(null);
  const [hotPeriod, setHotPeriod] = useState<PeriodType>("1d");

  // 검색 및 필터 상태
  const [searchQuery, setSearchQuery] = useState("");
  const [gradeFilter, setGradeFilter] = useState<FilterGrade>("all");
  const [sentimentFilter, setSentimentFilter] = useState<FilterSentiment>("all");

  // 비교 상태
  const [compareThemes, setCompareThemes] = useState<string[]>([]);

  // 스크리너 필터 결과
  const [screenerThemes, setScreenerThemes] = useState<ThemeRanking[] | null>(null);

  // 업데이트 시간
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  // 관심 테마
  const { favorites, toggleFavorite, isFavorite } = useFavoriteThemes();

  // 테마 메모
  const { memos, setMemo, getMemo } = useThemeMemos();

  // API 쿼리들
  const { data: analysis, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ["market-analysis"],
    queryFn: () => getMarketAnalysis(false),
    refetchInterval: 60000,
  });

  // 업데이트 시간 동기화
  useEffect(() => {
    if (dataUpdatedAt) {
      setLastUpdate(new Date(dataUpdatedAt));
    }
  }, [dataUpdatedAt]);

  const { data: newsAnalysis } = useQuery({
    queryKey: ["news-analysis"],
    queryFn: () => getNewsAnalysis(),
    refetchInterval: 300000,
  });

  // 테마 종합 순위 (overview와 themes 탭 모두에서 사용)
  const { data: themeRanking, isLoading: rankingLoading } = useQuery({
    queryKey: ["theme-ranking"],
    queryFn: () => getThemeRanking(30),
    enabled: activeTab === "themes" || activeTab === "overview",
    refetchInterval: 300000,
  });

  // 선택된 테마 상세 (랭킹에서 선택 시)
  const { data: themeDetailData, isLoading: themeDetailLoading } = useQuery({
    queryKey: ["theme-detail", selectedTheme],
    queryFn: () => getThemeDetail(selectedTheme!),
    enabled: !!selectedTheme && activeTab === "themes",
  });

  // 기간별 핫 테마
  const periodDaysMap: Record<PeriodType, number> = { "1d": 1, "3d": 3, "7d": 7, "30d": 30 };
  const { data: periodHotThemes, isLoading: periodLoading } = useQuery({
    queryKey: ["hot-themes-period", hotPeriod],
    queryFn: () => getHotThemesByPeriod(periodDaysMap[hotPeriod], 20),
    enabled: activeTab === "overview",
    refetchInterval: 300000,
  });

  // 필터링된 테마 목록
  const filteredThemes = useMemo(() => {
    // 스크리너 결과가 있으면 우선 사용
    const baseThemes = screenerThemes || themeRanking;
    if (!baseThemes) return [];

    return baseThemes.filter(theme => {
      // 검색어 필터
      if (searchQuery && !theme.theme_name.toLowerCase().includes(searchQuery.toLowerCase())) {
        return false;
      }
      // 등급 필터
      if (gradeFilter !== "all" && theme.grade !== gradeFilter) {
        return false;
      }
      // 감성 필터
      if (sentimentFilter === "positive" && !theme.sentiment.includes("positive")) {
        return false;
      }
      if (sentimentFilter === "negative" && !theme.sentiment.includes("negative")) {
        return false;
      }
      if (sentimentFilter === "neutral" && (theme.sentiment.includes("positive") || theme.sentiment.includes("negative"))) {
        return false;
      }
      return true;
    });
  }, [themeRanking, screenerThemes, searchQuery, gradeFilter, sentimentFilter]);

  // 비교 토글
  const toggleCompare = (themeCode: string) => {
    setCompareThemes(prev => {
      if (prev.includes(themeCode)) {
        return prev.filter(c => c !== themeCode);
      }
      if (prev.length >= 3) return prev;
      return [...prev, themeCode];
    });
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-400">시장 분석 중...</p>
        </div>
      </div>
    );
  }

  const selectedThemeData = analysis?.hot_themes.find(t => t.code === selectedTheme);

  return (
    <div className="min-h-screen p-6 space-y-6">
      {/* 헤더 */}
      {analysis && (
        <div className="flex items-center justify-between">
          <MarketHeader
            phase={analysis.phase}
            label={analysis.phase_label}
            sentiment={analysis.market_sentiment}
          />
          <UpdateIndicator lastUpdate={lastUpdate} isLoading={isLoading} />
        </div>
      )}

      {/* 실시간 테마 알림 배너 */}
      {themeRanking && <ThemeAlertBanner themes={themeRanking} />}

      {/* 탭 네비게이션 */}
      <TabNav active={activeTab} onChange={setActiveTab} />

      {/* 콘텐츠 */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* 요약 카드 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <SummaryCard
              icon="🔥"
              title="핫 테마"
              value={analysis?.hot_themes.length || 0}
              subtitle="개 테마 상승 중"
              trend="up"
            />
            <SummaryCard
              icon="💹"
              title="추천 종목"
              value={analysis?.recommended_stocks.length || 0}
              subtitle="개 종목 분석 완료"
            />
            <SummaryCard
              icon="📰"
              title="뉴스 분석"
              value={newsAnalysis?.length || 0}
              subtitle="개 테마 분석"
            />
            <SummaryCard
              icon="📊"
              title="시장 상태"
              value={analysis?.market_sentiment || "-"}
            />
          </div>

          {/* AI 마켓 인사이트 */}
          <AIMarketInsight
            hotThemes={analysis?.hot_themes}
            newsAnalysis={newsAnalysis}
            sentiment={analysis?.market_sentiment}
          />

          {/* AI 추천 & 키워드 클라우드 & 포트폴리오 빌더 */}
          {themeRanking && themeRanking.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <AIThemeRecommendation
                themes={themeRanking}
                newsAnalysis={newsAnalysis}
                onThemeClick={(code, name) => setThemeModal({ code, name })}
              />
              <NewsKeywordCloud newsAnalysis={newsAnalysis} />
              <ThemePortfolioBuilder
                themes={themeRanking}
                onThemeClick={(code, name) => setThemeModal({ code, name })}
              />
            </div>
          )}

          {/* TOP 테마 위젯 & 뉴스 감성 분포 */}
          {themeRanking && themeRanking.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ThemeDashboardWidget
                themes={themeRanking}
                newsAnalysis={newsAnalysis}
                onThemeClick={(code, name) => setThemeModal({ code, name })}
              />
              <div className="grid grid-cols-1 gap-4">
                <NewsSentimentDonut newsAnalysis={newsAnalysis} />
                <ThemeActivityTimeline />
              </div>
            </div>
          )}

          {/* 핫 테마 */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-4">
                <h2 className="text-lg font-bold text-white">핫 테마</h2>
                <PeriodTabs active={hotPeriod} onChange={setHotPeriod} />
              </div>
              <button
                onClick={() => setActiveTab("themes")}
                className="text-sm text-blue-400 hover:text-blue-300"
              >
                전체보기 →
              </button>
            </div>

            {periodLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="text-center">
                  <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                  <p className="text-slate-400 text-sm">{hotPeriod === "1d" ? "당일" : hotPeriod === "3d" ? "3일" : hotPeriod === "7d" ? "7일" : "30일"} 테마 분석 중...</p>
                </div>
              </div>
            ) : periodHotThemes && periodHotThemes.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {periodHotThemes.slice(0, 6).map((theme) => (
                  <PeriodHotThemeCard
                    key={theme.theme_code}
                    theme={theme}
                    onClick={() => setThemeModal({ code: theme.theme_code, name: theme.theme_name })}
                  />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {analysis?.hot_themes.slice(0, 6).map((theme) => (
                  <HotThemeCard
                    key={theme.code}
                    theme={theme}
                    isSelected={false}
                    onClick={() => setThemeModal({ code: theme.code, name: theme.name })}
                  />
                ))}
              </div>
            )}

            <p className="text-xs text-slate-500 mt-3 text-center">
              * {hotPeriod === "1d" ? "당일" : hotPeriod === "3d" ? "3일간" : hotPeriod === "7d" ? "7일간" : "30일간"} 테마 등락률 기준
            </p>
          </div>

          {/* 수급 흐름 & 뉴스 타임라인 */}
          {themeRanking && themeRanking.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SupplyFlowChart
                themes={themeRanking}
                onThemeClick={(code, name) => setThemeModal({ code, name })}
              />
              <NewsTimeline newsAnalysis={newsAnalysis} />
            </div>
          )}

          {/* 거래대금 & 연관 테마 */}
          {themeRanking && themeRanking.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ThemeVolumeRanking
                themes={themeRanking}
                onThemeClick={(code, name) => setThemeModal({ code, name })}
              />
              <div className="space-y-4">
                <ThemeCorrelationBadge themes={themeRanking} />

                {/* 관심 테마 (즐겨찾기) */}
                {favorites.length > 0 && (
                  <div className="p-5 bg-gradient-to-r from-amber-900/20 to-orange-900/20 rounded-2xl border border-amber-500/20">
                    <h3 className="font-bold text-white flex items-center gap-2 mb-3">
                      <span>⭐</span>
                      관심 테마
                    </h3>
                    <div className="flex flex-wrap gap-2">
                      {themeRanking
                        .filter(t => favorites.includes(t.theme_code))
                        .map(theme => (
                          <button
                            key={theme.theme_code}
                            onClick={() => setThemeModal({ code: theme.theme_code, name: theme.theme_name })}
                            className="flex items-center gap-2 px-3 py-2 bg-slate-800/50 rounded-lg hover:bg-slate-700/50 transition-colors"
                          >
                            <span className="text-sm text-white">{theme.theme_name}</span>
                            <span className={`text-xs font-mono ${
                              theme.change_rate > 0 ? "text-emerald-400" : theme.change_rate < 0 ? "text-red-400" : "text-slate-400"
                            }`}>
                              {theme.change_rate > 0 ? "+" : ""}{theme.change_rate.toFixed(1)}%
                            </span>
                          </button>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 추천 종목 미리보기 */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-white">추천 종목 TOP 4</h2>
              <button
                onClick={() => setActiveTab("stocks")}
                className="text-sm text-blue-400 hover:text-blue-300"
              >
                전체보기 →
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {analysis?.recommended_stocks.slice(0, 4).map((stock, i) => (
                <StockCard
                  key={stock.code}
                  stock={stock}
                  rank={i + 1}
                  onClick={() => setStockModal({ code: stock.code, name: stock.name })}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === "themes" && (
        <div className="space-y-6">
          {/* 헤더 */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold text-white">테마 종합 순위</h2>
              <p className="text-sm text-slate-400 mt-1">가격 모멘텀 + 뉴스 핫스코어 + 감성 + 수급 예측 종합 분석</p>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                {["A", "B", "C", "D", "F"].map((g) => (
                  <div key={g} className="flex items-center gap-1">
                    <div className={`w-5 h-5 rounded text-xs font-bold flex items-center justify-center ${
                      g === "A" ? "bg-emerald-500 text-white" :
                      g === "B" ? "bg-blue-500 text-white" :
                      g === "C" ? "bg-amber-500 text-white" :
                      g === "D" ? "bg-orange-500 text-white" :
                      "bg-red-500 text-white"
                    }`}>{g}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 검색 및 필터 */}
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <ThemeSearchFilter
                searchQuery={searchQuery}
                setSearchQuery={setSearchQuery}
                gradeFilter={gradeFilter}
                setGradeFilter={setGradeFilter}
                sentimentFilter={sentimentFilter}
                setSentimentFilter={setSentimentFilter}
              />
            </div>
            {themeRanking && (
              <div className="flex items-center gap-2">
                <ThemeScreener
                  themes={themeRanking}
                  onApply={(filtered) => {
                    // 스크리너 필터 적용 시 검색/필터 초기화 후 결과 표시
                    setScreenerThemes(filtered);
                    setSearchQuery("");
                    setGradeFilter("all");
                    setSentimentFilter("all");
                  }}
                />
                {screenerThemes && (
                  <button
                    onClick={() => setScreenerThemes(null)}
                    className="px-3 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg text-xs text-white"
                  >
                    필터 초기화
                  </button>
                )}
              </div>
            )}
          </div>

          {/* 히트맵 & 비교 */}
          {themeRanking && themeRanking.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ThemeHeatmap
                themes={themeRanking}
                onThemeClick={(code, name) => setThemeModal({ code, name })}
              />
              <ThemeComparison
                themes={themeRanking}
                selectedThemes={compareThemes}
                onToggleTheme={toggleCompare}
                onClear={() => setCompareThemes([])}
              />
            </div>
          )}

          {/* 랭킹 그리드 */}
          {rankingLoading ? (
            <div className="flex items-center justify-center py-20">
              <div className="text-center">
                <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                <p className="text-slate-400">테마 순위 분석 중... (최대 1분 소요)</p>
              </div>
            </div>
          ) : filteredThemes && filteredThemes.length > 0 ? (
            <>
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-500">{filteredThemes.length}개 테마</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filteredThemes.map((ranking) => (
                  <ThemeRankingCardWithCompare
                    key={ranking.theme_code}
                    ranking={ranking}
                    onClick={() => setThemeModal({ code: ranking.theme_code, name: ranking.theme_name })}
                    isComparing={compareThemes.includes(ranking.theme_code)}
                    onToggleCompare={() => toggleCompare(ranking.theme_code)}
                    canCompare={compareThemes.length < 3}
                    isFavorite={isFavorite(ranking.theme_code)}
                    onToggleFavorite={() => toggleFavorite(ranking.theme_code)}
                  />
                ))}
              </div>
            </>
          ) : themeRanking && themeRanking.length > 0 ? (
            <div className="flex items-center justify-center py-20 text-slate-500">
              <p>검색 결과가 없습니다</p>
            </div>
          ) : (
            <div className="flex items-center justify-center py-20 text-slate-500">
              <p>테마 순위 데이터를 불러올 수 없습니다</p>
            </div>
          )}
        </div>
      )}

      {activeTab === "stocks" && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {analysis?.recommended_stocks.map((stock, i) => (
            <StockCard
              key={stock.code}
              stock={stock}
              rank={i + 1}
              onClick={() => setStockModal({ code: stock.code, name: stock.name })}
            />
          ))}
        </div>
      )}

      {activeTab === "news" && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {newsAnalysis?.map((news) => (
            <NewsCard
              key={news.theme_name}
              news={news}
              onClick={() => {}}
            />
          ))}
        </div>
      )}

      {/* 종목 상세 모달 */}
      {stockModal && (
        <StockDetailModal
          stockCode={stockModal.code}
          stockName={stockModal.name}
          onClose={() => setStockModal(null)}
        />
      )}

      {/* 테마 상세 모달 */}
      {themeModal && (
        <ThemeDetailModal
          themeCode={themeModal.code}
          themeName={themeModal.name}
          onClose={() => setThemeModal(null)}
          onStockClick={(code, name) => {
            setThemeModal(null);
            setStockModal({ code, name });
          }}
        />
      )}

      {/* 애니메이션 스타일 */}
      <style jsx global>{`
        @keyframes modal-in {
          from {
            transform: scale(0.9);
            opacity: 0;
          }
          to {
            transform: scale(1);
            opacity: 1;
          }
        }
        .animate-modal-in {
          animation: modal-in 0.2s ease-out;
        }
      `}</style>
    </div>
  );
}
