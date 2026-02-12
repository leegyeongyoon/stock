"use client";

import { useState, useMemo, useEffect } from "react";
import { LayoutDashboard, Flame, TrendingUp, Newspaper } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ThemeRanking } from "@/lib/api";
import {
  useMarketAnalysis,
  useNewsAnalysis,
  useThemeRanking,
  usePeriodHotThemes,
} from "@/components/themes/hooks/useThemeQueries";
import useFavoriteThemes from "@/components/themes/hooks/useFavoriteThemes";
import useThemeMemos from "@/components/themes/hooks/useThemeMemos";
import {
  MarketHeader,
  UpdateIndicator,
  AIInsight,
  HotThemeSection,
  RecommendedStocks,
  WidgetGrid,
  SummaryCard,
  StockCard,
  ThemeRankingList,
  ThemeSearchFilter,
  ThemeScreener,
  ThemeHeatmap,
  ThemeComparison,
  NewsSection,
  ThemeDetailSheet,
  StockDetailSheet,
  OverviewSkeleton,
  RankingSkeleton,
} from "@/components/themes";
import type { PeriodType } from "@/components/themes/overview/HotThemeSection";
import type {
  FilterGrade,
  FilterSentiment,
} from "@/components/themes/ranking/ThemeSearchFilter";

type TabType = "overview" | "themes" | "stocks" | "news";

const TABS: { id: TabType; label: string; Icon: LucideIcon }[] = [
  { id: "overview", label: "대시보드", Icon: LayoutDashboard },
  { id: "themes", label: "핫테마", Icon: Flame },
  { id: "stocks", label: "추천종목", Icon: TrendingUp },
  { id: "news", label: "뉴스분석", Icon: Newspaper },
];

export default function ThemesPage() {
  const [activeTab, setActiveTab] = useState<TabType>("overview");
  const [stockModal, setStockModal] = useState<{
    code: string;
    name: string;
  } | null>(null);
  const [themeModal, setThemeModal] = useState<{
    code: string;
    name: string;
  } | null>(null);
  const [hotPeriod, setHotPeriod] = useState<PeriodType>("1d");

  // Search & filter state (themes tab)
  const [searchQuery, setSearchQuery] = useState("");
  const [gradeFilter, setGradeFilter] = useState<FilterGrade>("all");
  const [sentimentFilter, setSentimentFilter] =
    useState<FilterSentiment>("all");
  const [compareThemes, setCompareThemes] = useState<string[]>([]);
  const [screenerThemes, setScreenerThemes] = useState<ThemeRanking[] | null>(
    null
  );
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  // Hooks
  const { favorites, toggleFavorite, isFavorite } = useFavoriteThemes();
  const { setMemo, getMemo } = useThemeMemos();

  // Data queries
  const {
    data: analysis,
    isLoading,
    isError: analysisError,
    dataUpdatedAt,
    refetch: refetchAnalysis,
  } = useMarketAnalysis();
  const { data: newsAnalysis } = useNewsAnalysis(activeTab);
  const { data: themeRanking, isLoading: rankingLoading, isError: rankingError, refetch: refetchRanking } =
    useThemeRanking(activeTab);
  const { data: periodHotThemes, isLoading: periodLoading } =
    usePeriodHotThemes(hotPeriod, activeTab);

  useEffect(() => {
    if (dataUpdatedAt) setLastUpdate(new Date(dataUpdatedAt));
  }, [dataUpdatedAt]);

  // Filtered themes for ranking tab
  const filteredThemes = useMemo(() => {
    const base = screenerThemes || themeRanking;
    if (!base) return [];
    return base.filter((theme) => {
      if (
        searchQuery &&
        !theme.theme_name.toLowerCase().includes(searchQuery.toLowerCase())
      )
        return false;
      if (gradeFilter !== "all" && theme.grade !== gradeFilter) return false;
      if (
        sentimentFilter === "positive" &&
        !theme.sentiment.includes("positive")
      )
        return false;
      if (
        sentimentFilter === "negative" &&
        !theme.sentiment.includes("negative")
      )
        return false;
      if (
        sentimentFilter === "neutral" &&
        (theme.sentiment.includes("positive") ||
          theme.sentiment.includes("negative"))
      )
        return false;
      return true;
    });
  }, [themeRanking, screenerThemes, searchQuery, gradeFilter, sentimentFilter]);

  const toggleCompare = (code: string) => {
    setCompareThemes((prev) => {
      if (prev.includes(code)) return prev.filter((c) => c !== code);
      if (prev.length >= 3) return prev;
      return [...prev, code];
    });
  };

  const handleThemeClick = (code: string, name: string) =>
    setThemeModal({ code, name });
  const handleStockClick = (code: string, name: string) =>
    setStockModal({ code, name });

  return (
    <div className="min-h-screen p-3 space-y-3 sm:p-4 sm:space-y-4 lg:p-6 lg:space-y-6 pb-20 md:pb-6">
      {/* Header */}
      {analysis ? (
        <div className="flex items-center justify-between flex-wrap gap-2">
          <MarketHeader
            phase={analysis.phase}
            label={analysis.phase_label}
            sentiment={analysis.market_sentiment}
          />
          <UpdateIndicator lastUpdate={lastUpdate} isLoading={isLoading} />
        </div>
      ) : isLoading ? (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="animate-pulse w-10 h-10 rounded-lg bg-slate-700/60" />
            <div>
              <div className="animate-pulse w-24 h-4 rounded bg-slate-700/60 mb-1" />
              <div className="animate-pulse w-16 h-3 rounded bg-slate-700/60" />
            </div>
          </div>
          <p className="text-xs text-slate-500">시장 분석 데이터를 불러오는 중...</p>
        </div>
      ) : null}

      {/* Desktop tabs */}
      <div className="hidden md:flex gap-1 p-1 bg-slate-800/50 rounded-xl">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium transition-all ${
              activeTab === tab.id
                ? "bg-white text-slate-900 shadow-lg"
                : "text-slate-400 hover:text-white hover:bg-slate-700/50"
            }`}
          >
            <tab.Icon size={18} />
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* === Overview Tab === */}
      {activeTab === "overview" && isLoading && !analysis && <OverviewSkeleton />}
      {activeTab === "overview" && !isLoading && analysisError && !analysis && (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <p className="text-slate-400">서버에서 데이터를 불러오지 못했습니다.</p>
          <p className="text-xs text-slate-500">서버 시작 직후에는 캐시 준비에 1~2분 소요됩니다.</p>
          <button
            onClick={() => refetchAnalysis()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm text-white transition-colors"
          >
            다시 시도
          </button>
        </div>
      )}
      {activeTab === "overview" && (analysis || (!isLoading && !analysisError)) && (
        <div className="space-y-3 sm:space-y-4 lg:space-y-6">
          <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-4 md:gap-4">
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

          <AIInsight
            hotThemes={analysis?.hot_themes}
            newsAnalysis={newsAnalysis}
            sentiment={analysis?.market_sentiment}
          />

          <WidgetGrid
            themeRanking={themeRanking || []}
            newsAnalysis={newsAnalysis}
            favorites={favorites}
            onThemeClick={handleThemeClick}
            onStockClick={handleStockClick}
          />

          <HotThemeSection
            periodHotThemes={periodHotThemes}
            fallbackThemes={analysis?.hot_themes}
            periodLoading={periodLoading}
            hotPeriod={hotPeriod}
            onHotPeriodChange={setHotPeriod}
            onThemeClick={handleThemeClick}
            onViewAll={() => setActiveTab("themes")}
          />

          <RecommendedStocks
            stocks={analysis?.recommended_stocks}
            onStockClick={handleStockClick}
            onViewAll={() => setActiveTab("stocks")}
          />
        </div>
      )}

      {/* === Themes Tab === */}
      {activeTab === "themes" && (
        <div className="space-y-3 sm:space-y-4 lg:space-y-6">
          <div>
            <h2 className="text-lg sm:text-xl font-bold text-white">
              테마 종합 순위
            </h2>
            <p className="text-xs sm:text-sm text-slate-400 mt-1">
              가격 모멘텀 + 뉴스 핫스코어 + 감성 + 수급 예측 종합 분석
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:gap-4">
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
                    초기화
                  </button>
                )}
              </div>
            )}
          </div>

          {themeRanking && themeRanking.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-6">
              <ThemeHeatmap
                themes={themeRanking}
                onThemeClick={handleThemeClick}
              />
              <ThemeComparison
                themes={themeRanking}
                selectedThemes={compareThemes}
                onToggleTheme={toggleCompare}
                onClear={() => setCompareThemes([])}
              />
            </div>
          )}

          {rankingLoading && !themeRanking ? (
            <RankingSkeleton />
          ) : rankingError && !themeRanking ? (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <p className="text-slate-400">테마 순위를 불러오지 못했습니다.</p>
              <p className="text-xs text-slate-500">서버 캐시 준비 중일 수 있습니다. 잠시 후 다시 시도해주세요.</p>
              <button
                onClick={() => refetchRanking()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm text-white transition-colors"
              >
                다시 시도
              </button>
            </div>
          ) : filteredThemes.length > 0 ? (
            <>
              <p className="text-xs sm:text-sm text-slate-500">
                {filteredThemes.length}개 테마
              </p>
              <ThemeRankingList
                rankings={filteredThemes}
                onThemeClick={handleThemeClick}
                compareThemes={compareThemes}
                onToggleCompare={toggleCompare}
                favorites={favorites}
                onToggleFavorite={toggleFavorite}
              />
            </>
          ) : (
            <div className="flex items-center justify-center py-20 text-slate-500">
              <p>
                {themeRanking
                  ? "검색 결과가 없습니다"
                  : "테마 순위 데이터를 불러올 수 없습니다"}
              </p>
            </div>
          )}
        </div>
      )}

      {/* === Stocks Tab === */}
      {activeTab === "stocks" && (
        <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-3 lg:grid-cols-4 md:gap-4">
          {analysis?.recommended_stocks.map((stock, i) => (
            <StockCard
              key={stock.code}
              stock={stock}
              rank={i + 1}
              onClick={() => handleStockClick(stock.code, stock.name)}
            />
          ))}
        </div>
      )}

      {/* === News Tab === */}
      {activeTab === "news" && <NewsSection newsAnalysis={newsAnalysis} />}

      {/* Modals (BottomSheet on mobile, Modal on desktop) */}
      {stockModal && (
        <StockDetailSheet
          stockCode={stockModal.code}
          stockName={stockModal.name}
          onClose={() => setStockModal(null)}
        />
      )}
      {themeModal && (
        <ThemeDetailSheet
          themeCode={themeModal.code}
          themeName={themeModal.name}
          onClose={() => setThemeModal(null)}
          onStockClick={(code, name) => {
            setThemeModal(null);
            setStockModal({ code, name });
          }}
          memo={getMemo(themeModal.code)}
          onMemoChange={(memo) => setMemo(themeModal.code, memo)}
        />
      )}

      {/* Mobile bottom navigation */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 md:hidden bg-slate-900/95 backdrop-blur-md border-t border-slate-700 pb-[env(safe-area-inset-bottom)]">
        <div className="flex justify-around py-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex flex-col items-center gap-0.5 px-3 py-1 transition-colors ${
                activeTab === tab.id ? "text-blue-400" : "text-slate-500"
              }`}
            >
              <tab.Icon size={20} />
              <span className="text-[10px]">{tab.label}</span>
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}
