"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getMarketAnalysis,
  getNewsAnalysis,
  getThemeRanking,
  getThemeDetail,
  getHotThemesByPeriod,
} from "@/lib/api";

type TabType = "overview" | "themes" | "stocks" | "news";
type PeriodType = "1d" | "3d" | "7d" | "30d";

const PERIOD_DAYS_MAP: Record<PeriodType, number> = {
  "1d": 1,
  "3d": 3,
  "7d": 7,
  "30d": 30,
};

export function useMarketAnalysis() {
  return useQuery({
    queryKey: ["market-analysis"],
    queryFn: () => getMarketAnalysis(false),
    refetchInterval: 60000,
    retry: 2,
    retryDelay: 5000,
  });
}

export function useNewsAnalysis(activeTab: TabType) {
  return useQuery({
    queryKey: ["news-analysis"],
    queryFn: () => getNewsAnalysis(),
    refetchInterval: 300000,
    enabled: activeTab === "overview" || activeTab === "news",
    retry: 1,
    retryDelay: 3000,
  });
}

export function useThemeRanking(activeTab: TabType) {
  return useQuery({
    queryKey: ["theme-ranking"],
    queryFn: () => getThemeRanking(30),
    enabled: activeTab === "themes" || activeTab === "overview",
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchInterval: 300000,
    retry: 1,
    retryDelay: 5000,
  });
}

export function useThemeDetail(themeCode: string | null, activeTab: TabType) {
  return useQuery({
    queryKey: ["theme-detail", themeCode],
    queryFn: () => getThemeDetail(themeCode!),
    enabled: !!themeCode && activeTab === "themes",
    retry: 1,
  });
}

export function usePeriodHotThemes(period: PeriodType, activeTab: TabType) {
  return useQuery({
    queryKey: ["hot-themes-period", period],
    queryFn: () => getHotThemesByPeriod(PERIOD_DAYS_MAP[period], 20),
    enabled: activeTab === "overview",
    staleTime: 5 * 60 * 1000,
    refetchInterval: 300000,
    retry: 1,
    retryDelay: 5000,
  });
}
