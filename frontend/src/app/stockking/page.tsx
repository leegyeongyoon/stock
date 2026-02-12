"use client";

import { useQuery } from "@tanstack/react-query";
import { getStockkingDashboard } from "@/lib/api";
import MarketStatusBar from "@/components/stockking/MarketStatusBar";
import LeadingSectorPanel from "@/components/stockking/LeadingSectorPanel";
import LeaderStockTable from "@/components/stockking/LeaderStockTable";
import SignalBoard from "@/components/stockking/SignalBoard";
import PatternAlerts from "@/components/stockking/PatternAlerts";
import DPlusCandidates from "@/components/stockking/DPlusCandidates";
import TradingRules from "@/components/stockking/TradingRules";
import TradingPanel from "@/components/stockking/TradingPanel";
import TradeHistory from "@/components/stockking/TradeHistory";
import HongPerformance from "@/components/stockking/HongPerformance";
import ConvictionPanel from "@/components/stockking/ConvictionPanel";
import HongStrategyGuide from "@/components/stockking/HongStrategyGuide";
import { StockDetailSheet } from "@/components/themes";

import { useState } from "react";
import { Crown, RefreshCw, Search, Swords } from "lucide-react";

export default function StockkingPage() {
  const [stockModal, setStockModal] = useState<{ code: string; name: string } | null>(null);
  const [activeTab, setActiveTab] = useState<"analysis" | "trading">("analysis");

  const {
    data: dashboard,
    isLoading,
    isError,
    refetch,
    dataUpdatedAt,
  } = useQuery({
    queryKey: ["stockking-dashboard"],
    queryFn: getStockkingDashboard,
    refetchInterval: 15000,
    retry: 2,
    retryDelay: 5000,
  });

  const handleStockClick = (code: string, name: string) => {
    setStockModal({ code, name });
  };

  const lastUpdate = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  return (
    <div className="min-h-screen p-3 space-y-3 sm:p-4 sm:space-y-4 lg:p-6 lg:space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-yellow-500 to-orange-600 flex items-center justify-center">
            <Crown size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg sm:text-xl font-bold text-white">홍인기 전략</h1>
            <p className="text-xs text-slate-500">주도주 매매 시스템</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && (
            <span className="text-[10px] text-slate-500">
              {lastUpdate.toLocaleTimeString("ko-KR")} 업데이트
            </span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isLoading}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={14} className={`text-slate-400 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-slate-800/50 p-1 rounded-lg w-fit">
        <button
          onClick={() => setActiveTab("analysis")}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === "analysis"
              ? "bg-slate-700 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Search size={14} />
          분석
        </button>
        <button
          onClick={() => setActiveTab("trading")}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === "trading"
              ? "bg-slate-700 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Swords size={14} />
          트레이딩
        </button>
      </div>

      {/* Analysis Tab */}
      {activeTab === "analysis" && (
        <>
          {/* Loading state */}
          {isLoading && !dashboard && (
            <div className="space-y-4">
              <div className="animate-pulse h-16 bg-slate-800 rounded-xl" />
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2 space-y-4">
                  <div className="animate-pulse h-48 bg-slate-800 rounded-xl" />
                  <div className="animate-pulse h-64 bg-slate-800 rounded-xl" />
                </div>
                <div className="space-y-4">
                  <div className="animate-pulse h-48 bg-slate-800 rounded-xl" />
                  <div className="animate-pulse h-48 bg-slate-800 rounded-xl" />
                </div>
              </div>
            </div>
          )}

          {/* Error state */}
          {isError && !dashboard && (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <p className="text-slate-400">서버에서 데이터를 불러오지 못했습니다.</p>
              <p className="text-xs text-slate-500">홍인기 전략 API가 아직 준비되지 않았을 수 있습니다.</p>
              <button
                onClick={() => refetch()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm text-white transition-colors"
              >
                다시 시도
              </button>
            </div>
          )}

          {/* Dashboard content */}
          {(dashboard || (!isLoading && !isError)) && (
            <>
              {/* Market Status Bar */}
              <MarketStatusBar condition={dashboard?.market_condition} />

              {/* Main grid: Left 2/3 + Right 1/3 */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4 lg:gap-6">
                {/* Left side */}
                <div className="lg:col-span-2 space-y-3 sm:space-y-4 lg:space-y-6">
                  <LeadingSectorPanel sectors={dashboard?.leading_sectors} />
                  <LeaderStockTable
                    stocks={dashboard?.leader_stocks}
                    onStockClick={handleStockClick}
                  />
                </div>

                {/* Right side */}
                <div className="space-y-3 sm:space-y-4 lg:space-y-6">
                  <SignalBoard signals={dashboard?.signals} />
                  <PatternAlerts alerts={dashboard?.pattern_alerts} />
                </div>
              </div>

              {/* Bottom section */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4 lg:gap-6">
                <DPlusCandidates candidates={dashboard?.d_plus_candidates} />
                <TradingRules
                  rules={dashboard?.rules_status?.critical_rules}
                  checkedCount={dashboard?.rules_status?.checked}
                  totalCount={dashboard?.rules_status?.total}
                />
              </div>
            </>
          )}

          {/* Stock Detail Modal */}
          {stockModal && (
            <StockDetailSheet
              stockCode={stockModal.code}
              stockName={stockModal.name}
              onClose={() => setStockModal(null)}
            />
          )}
        </>
      )}

      {/* Trading Tab */}
      {activeTab === "trading" && (
        <div className="space-y-3 sm:space-y-4 lg:space-y-6">
          {/* 상단: 제어 + 매매내역 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4 lg:gap-6">
            <TradingPanel />
            <TradeHistory />
          </div>
          {/* 성과 차트 */}
          <HongPerformance />
          {/* 하단: 확신도 순위 + 알고리즘 */}
          <ConvictionPanel />
          {/* 전략 가이드 */}
          <HongStrategyGuide />
        </div>
      )}
    </div>
  );
}
