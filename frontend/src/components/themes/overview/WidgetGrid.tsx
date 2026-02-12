"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { ThemeRanking, NewsAnalysis } from "@/lib/api";
import CollapsibleSection from "../common/CollapsibleSection";

// Lazy-load heavy widgets
const AIThemeRecommendation = dynamic(() => import("./widgets/AIThemeRecommendation"));
const NewsKeywordCloud = dynamic(() => import("./widgets/NewsKeywordCloud"));
const ThemePortfolioBuilder = dynamic(() => import("./widgets/ThemePortfolioBuilder"));
const ThemeDashboardWidget = dynamic(() => import("./widgets/ThemeDashboardWidget"));
const NewsSentimentDonut = dynamic(() => import("./widgets/NewsSentimentDonut"));
const SupplyFlowChart = dynamic(() => import("./widgets/SupplyFlowChart"));
const NewsTimeline = dynamic(() => import("./widgets/NewsTimeline"));
const ThemeVolumeRanking = dynamic(() => import("./widgets/ThemeVolumeRanking"));
const SupplyHeatmap = dynamic(() => import("./widgets/SupplyHeatmap"));
const ThemeVolatilityIndicator = dynamic(() => import("./widgets/ThemeVolatilityIndicator"));
const ThemeRankTracker = dynamic(() => import("./widgets/ThemeRankTracker"));
const ThemeMomentumSparklines = dynamic(() => import("./widgets/ThemeMomentumSparklines"));
const ThemeInterestIndex = dynamic(() => import("./widgets/ThemeInterestIndex"));
const ThemeRiskReturnMatrix = dynamic(() => import("./widgets/ThemeRiskReturnMatrix"));
const ThemeMarketTiming = dynamic(() => import("./widgets/ThemeMarketTiming"));
const ThemeTopStocksPanel = dynamic(() => import("./widgets/ThemeTopStocksPanel"));
const ThemeAlertBanner = dynamic(() => import("./widgets/ThemeAlertBanner"));

interface WidgetGridProps {
  themeRanking: ThemeRanking[];
  newsAnalysis?: NewsAnalysis[];
  favorites: string[];
  onThemeClick: (code: string, name: string) => void;
  onStockClick: (code: string, name: string) => void;
}

export default function WidgetGrid({
  themeRanking,
  newsAnalysis,
  favorites,
  onThemeClick,
  onStockClick,
}: WidgetGridProps) {
  if (!themeRanking || themeRanking.length === 0) return null;

  return (
    <div className="space-y-3 sm:space-y-6">
      {/* Alert Banner */}
      <ThemeAlertBanner themes={themeRanking} />

      {/* AI + Keyword + Portfolio -- Desktop: 3col, Mobile: collapsible */}
      <div className="hidden lg:grid lg:grid-cols-3 gap-6">
        <AIThemeRecommendation themes={themeRanking} newsAnalysis={newsAnalysis} onThemeClick={onThemeClick} />
        <NewsKeywordCloud newsAnalysis={newsAnalysis} />
        <ThemePortfolioBuilder themes={themeRanking} onThemeClick={onThemeClick} />
      </div>
      <div className="lg:hidden space-y-3">
        <CollapsibleSection title="AI 추천 & 키워드" icon={<span>🤖</span>}>
          <div className="space-y-4">
            <AIThemeRecommendation themes={themeRanking} newsAnalysis={newsAnalysis} onThemeClick={onThemeClick} />
            <NewsKeywordCloud newsAnalysis={newsAnalysis} />
          </div>
        </CollapsibleSection>
        <CollapsibleSection title="포트폴리오 빌더" icon={<span>📦</span>}>
          <ThemePortfolioBuilder themes={themeRanking} onThemeClick={onThemeClick} />
        </CollapsibleSection>
      </div>

      {/* TOP Theme + Sentiment -- Desktop: 2col, Mobile: collapsible */}
      <div className="hidden lg:grid lg:grid-cols-2 gap-6">
        <ThemeDashboardWidget themes={themeRanking} newsAnalysis={newsAnalysis} onThemeClick={onThemeClick} />
        <NewsSentimentDonut newsAnalysis={newsAnalysis} />
      </div>
      <div className="lg:hidden space-y-3">
        <CollapsibleSection title="TOP 테마 & 감성" icon={<span>🏆</span>}>
          <div className="space-y-4">
            <ThemeDashboardWidget themes={themeRanking} newsAnalysis={newsAnalysis} onThemeClick={onThemeClick} />
            <NewsSentimentDonut newsAnalysis={newsAnalysis} />
          </div>
        </CollapsibleSection>
      </div>

      {/* Supply Flow + News Timeline */}
      <div className="hidden lg:grid lg:grid-cols-2 gap-6">
        <SupplyFlowChart themes={themeRanking} onThemeClick={onThemeClick} />
        <NewsTimeline newsAnalysis={newsAnalysis} />
      </div>
      <div className="lg:hidden space-y-3">
        <CollapsibleSection title="수급 흐름 & 뉴스" icon={<span>📊</span>}>
          <div className="space-y-4">
            <SupplyFlowChart themes={themeRanking} onThemeClick={onThemeClick} />
            <NewsTimeline newsAnalysis={newsAnalysis} />
          </div>
        </CollapsibleSection>
      </div>

      {/* Volume + Favorites */}
      <div className="hidden lg:grid lg:grid-cols-2 gap-6">
        <ThemeVolumeRanking themes={themeRanking} onThemeClick={onThemeClick} />
        {favorites.length > 0 && (
          <div className="p-5 bg-gradient-to-r from-amber-900/20 to-orange-900/20 rounded-2xl border border-amber-500/20">
            <h3 className="font-bold text-white flex items-center gap-2 mb-3">
              <span>⭐</span> 관심 테마
            </h3>
            <div className="flex flex-wrap gap-2">
              {themeRanking
                .filter((t) => favorites.includes(t.theme_code))
                .map((theme) => (
                  <button
                    key={theme.theme_code}
                    onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
                    className="flex items-center gap-2 px-3 py-2 bg-slate-800/50 rounded-lg hover:bg-slate-700/50 transition-colors"
                  >
                    <span className="text-sm text-white">{theme.theme_name}</span>
                    <span
                      className={`text-xs font-mono ${
                        theme.change_rate > 0 ? "text-emerald-400" : theme.change_rate < 0 ? "text-red-400" : "text-slate-400"
                      }`}
                    >
                      {theme.change_rate > 0 ? "+" : ""}
                      {theme.change_rate.toFixed(1)}%
                    </span>
                  </button>
                ))}
            </div>
          </div>
        )}
      </div>

      {/* Heatmap + Volatility + Rank Tracker */}
      <div className="hidden lg:grid lg:grid-cols-3 gap-6">
        <SupplyHeatmap themes={themeRanking} onThemeClick={onThemeClick} />
        <ThemeVolatilityIndicator themes={themeRanking} />
        <ThemeRankTracker themes={themeRanking} />
      </div>
      <div className="lg:hidden space-y-3">
        <CollapsibleSection title="수급 히트맵 & 변동성" icon={<span>🗺️</span>}>
          <div className="space-y-4">
            <SupplyHeatmap themes={themeRanking} onThemeClick={onThemeClick} />
            <ThemeVolatilityIndicator themes={themeRanking} />
            <ThemeRankTracker themes={themeRanking} />
          </div>
        </CollapsibleSection>
      </div>

      {/* Momentum + Interest + Risk Matrix */}
      <div className="hidden lg:grid lg:grid-cols-3 gap-6">
        <ThemeMomentumSparklines themes={themeRanking} onThemeClick={onThemeClick} />
        <ThemeInterestIndex themes={themeRanking} />
        <ThemeRiskReturnMatrix themes={themeRanking} onThemeClick={onThemeClick} />
      </div>
      <div className="lg:hidden space-y-3">
        <CollapsibleSection title="모멘텀 & 관심도" icon={<span>📈</span>}>
          <div className="space-y-4">
            <ThemeMomentumSparklines themes={themeRanking} onThemeClick={onThemeClick} />
            <ThemeInterestIndex themes={themeRanking} />
            <ThemeRiskReturnMatrix themes={themeRanking} onThemeClick={onThemeClick} />
          </div>
        </CollapsibleSection>
      </div>

      {/* Market Timing + Top Stocks */}
      <div className="hidden lg:grid lg:grid-cols-2 gap-6">
        <ThemeMarketTiming themes={themeRanking} />
        <ThemeTopStocksPanel themes={themeRanking} onThemeClick={onThemeClick} onStockClick={onStockClick} />
      </div>
      <div className="lg:hidden space-y-3">
        <CollapsibleSection title="마켓 타이밍 & TOP3" icon={<span>⏱️</span>}>
          <div className="space-y-4">
            <ThemeMarketTiming themes={themeRanking} />
            <ThemeTopStocksPanel themes={themeRanking} onThemeClick={onThemeClick} onStockClick={onStockClick} />
          </div>
        </CollapsibleSection>
      </div>
    </div>
  );
}
