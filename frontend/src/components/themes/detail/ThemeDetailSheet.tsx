"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getThemeDetail, getThemeNews } from "@/lib/api";
import BottomSheet from "../common/BottomSheet";

export default function ThemeDetailSheet({
  themeCode,
  themeName,
  onClose,
  onStockClick,
  memo,
  onMemoChange,
}: {
  themeCode: string;
  themeName: string;
  onClose: () => void;
  onStockClick: (code: string, name: string) => void;
  memo?: string;
  onMemoChange?: (memo: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<"stocks" | "news" | "memo">("stocks");
  const [memoText, setMemoText] = useState(memo || "");

  const { data: themeDetail, isLoading: detailLoading } = useQuery({
    queryKey: ["theme-detail-modal", themeCode],
    queryFn: () => getThemeDetail(themeCode),
    enabled: !!themeCode,
  });

  const { data: newsData, isLoading: newsLoading } = useQuery({
    queryKey: ["theme-news-modal", themeName],
    queryFn: () => getThemeNews(themeName),
    enabled: !!themeName && activeTab === "news",
  });

  return (
    <BottomSheet open={true} onClose={onClose} title={themeName}>
      {detailLoading ? (
        <div className="h-64 flex items-center justify-center">
          <div className="text-center">
            <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p className="text-slate-400 text-sm">테마 분석 중...</p>
          </div>
        </div>
      ) : themeDetail ? (
        <div className="space-y-4">
          {/* Header info */}
          <div className="flex items-start gap-3 sm:gap-5">
            <div
              className={`w-14 h-14 sm:w-20 sm:h-20 rounded-xl sm:rounded-2xl flex flex-col items-center justify-center shadow-xl flex-shrink-0 ${
                (themeDetail.change_rate || 0) > 3
                  ? "bg-gradient-to-br from-emerald-400 to-emerald-600"
                  : (themeDetail.change_rate || 0) > 0
                  ? "bg-gradient-to-br from-blue-400 to-blue-600"
                  : (themeDetail.change_rate || 0) > -2
                  ? "bg-gradient-to-br from-amber-400 to-amber-600"
                  : "bg-gradient-to-br from-red-400 to-red-600"
              }`}
            >
              <span className="text-lg sm:text-2xl font-black text-white">🔥</span>
              <span className="text-[10px] sm:text-xs text-white/80">테마</span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-lg sm:text-2xl font-bold text-white">{themeDetail.name}</h2>
                <span className="px-2 py-0.5 bg-slate-700 rounded text-xs text-slate-400">{themeDetail.code}</span>
              </div>
              <div className="flex items-baseline gap-2 sm:gap-3 mt-1">
                <span
                  className={`text-xl sm:text-3xl font-bold ${
                    (themeDetail.change_rate || 0) > 0
                      ? "text-emerald-400"
                      : (themeDetail.change_rate || 0) < 0
                      ? "text-red-400"
                      : "text-white"
                  }`}
                >
                  {(themeDetail.change_rate || 0) > 0 ? "+" : ""}
                  {(themeDetail.change_rate || 0).toFixed(2)}%
                </span>
                <span className="text-xs sm:text-sm text-slate-500">
                  종목 {themeDetail.stock_count || themeDetail.stocks?.length || 0}개
                </span>
              </div>
            </div>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-4 gap-2 sm:gap-3">
            {[
              {
                label: "모멘텀",
                value:
                  themeDetail.momentum === "strong_up"
                    ? "강세"
                    : themeDetail.momentum === "up"
                    ? "상승"
                    : themeDetail.momentum === "down"
                    ? "하락"
                    : "중립",
                color:
                  themeDetail.momentum === "strong_up"
                    ? "text-emerald-400"
                    : themeDetail.momentum === "up"
                    ? "text-green-400"
                    : themeDetail.momentum === "down"
                    ? "text-red-400"
                    : "text-slate-400",
              },
              {
                label: "외인",
                value: themeDetail.foreign_buying ? "매수세" : "-",
                color: themeDetail.foreign_buying ? "text-blue-400" : "text-slate-400",
              },
              {
                label: "기관",
                value: themeDetail.inst_buying ? "매수세" : "-",
                color: themeDetail.inst_buying ? "text-purple-400" : "text-slate-400",
              },
              {
                label: "리더주",
                value: themeDetail.leader || "-",
                color: "text-white",
              },
            ].map((item) => (
              <div key={item.label} className="p-2 sm:p-3 rounded-lg sm:rounded-xl bg-slate-800/50 border border-slate-700/30 text-center">
                <p className="text-[10px] sm:text-xs text-slate-500">{item.label}</p>
                <p className={`text-xs sm:text-lg font-bold truncate ${item.color}`}>{item.value}</p>
              </div>
            ))}
          </div>

          {themeDetail.analysis_comment && (
            <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/30">
              <p className="text-xs sm:text-sm text-blue-300">{themeDetail.analysis_comment}</p>
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1.5 sm:gap-2 border-b border-slate-700/50 pb-2">
            {[
              { id: "stocks" as const, label: "종목", icon: "📊" },
              { id: "news" as const, label: "뉴스", icon: "📰" },
              { id: "memo" as const, label: "메모", icon: "📝", badge: !!memo },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1 px-3 py-1.5 sm:py-2 rounded-lg text-xs sm:text-sm font-medium transition-colors ${
                  activeTab === tab.id ? "bg-blue-500 text-white" : "text-slate-400 hover:text-white hover:bg-slate-700/50"
                }`}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
                {tab.badge && <span className="w-2 h-2 rounded-full bg-amber-400" />}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {activeTab === "stocks" && (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 sm:gap-4">
              {themeDetail.stocks?.map((stock, i) => (
                <div
                  key={stock.code}
                  onClick={() => onStockClick(stock.code, stock.name)}
                  className="p-3 sm:p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 hover:border-blue-500/50 cursor-pointer transition-all"
                >
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <span className="w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center text-[10px] font-bold text-white">
                      {i + 1}
                    </span>
                    <span className="font-semibold text-white truncate flex-1 text-xs sm:text-sm">{stock.name}</span>
                    {stock.is_leader && <span className="text-xs text-amber-400">👑</span>}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] sm:text-xs text-slate-500">{stock.code}</span>
                    <span
                      className={`text-xs sm:text-sm font-bold ${
                        stock.change_rate > 0 ? "text-emerald-400" : stock.change_rate < 0 ? "text-red-400" : "text-slate-400"
                      }`}
                    >
                      {stock.change_rate > 0 ? "+" : ""}
                      {stock.change_rate.toFixed(2)}%
                    </span>
                  </div>
                  <div className="mt-1.5 text-[10px] sm:text-xs text-slate-500">
                    거래량 {(stock.volume / 10000).toFixed(0)}만
                  </div>
                  <div className="mt-1.5 pt-1.5 border-t border-slate-700/50">
                    <span
                      className={`text-[10px] sm:text-xs px-1.5 py-0.5 rounded ${
                        stock.recommendation === "buy" || stock.recommendation === "strong_buy"
                          ? "bg-emerald-500/20 text-emerald-400"
                          : stock.recommendation === "sell"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-slate-700 text-slate-400"
                      }`}
                    >
                      {stock.recommendation === "strong_buy"
                        ? "적극 매수"
                        : stock.recommendation === "buy"
                        ? "매수"
                        : stock.recommendation === "hold"
                        ? "관망"
                        : stock.recommendation === "sell"
                        ? "매도"
                        : "관망"}
                    </span>
                  </div>
                </div>
              ))}
              {(!themeDetail.stocks || themeDetail.stocks.length === 0) && (
                <div className="col-span-full py-8 text-center text-slate-500 text-sm">종목 데이터가 없습니다</div>
              )}
            </div>
          )}

          {activeTab === "news" && (
            <div className="space-y-3">
              {newsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
                </div>
              ) : newsData && newsData.length > 0 ? (
                newsData.map((item, i) => (
                  <a
                    key={i}
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block p-3 sm:p-4 rounded-xl bg-slate-800/30 border border-slate-700/30 hover:bg-slate-800/60 transition-colors"
                  >
                    <div className="flex items-start gap-2 sm:gap-3">
                      <div
                        className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                          item.sentiment === "positive" || item.sentiment === "very_positive"
                            ? "bg-emerald-400"
                            : item.sentiment === "negative" || item.sentiment === "very_negative"
                            ? "bg-red-400"
                            : "bg-slate-400"
                        }`}
                      />
                      <div className="flex-1 min-w-0">
                        <h5 className="font-medium text-white text-xs sm:text-sm line-clamp-2">{item.title}</h5>
                        <div className="flex items-center gap-2 mt-1.5 text-xs text-slate-500">
                          <span>{item.source}</span>
                          <span>•</span>
                          <span
                            className={
                              item.sentiment === "positive" || item.sentiment === "very_positive"
                                ? "text-emerald-400"
                                : item.sentiment === "negative" || item.sentiment === "very_negative"
                                ? "text-red-400"
                                : "text-slate-400"
                            }
                          >
                            {item.sentiment === "positive" || item.sentiment === "very_positive"
                              ? "긍정"
                              : item.sentiment === "negative" || item.sentiment === "very_negative"
                              ? "부정"
                              : "중립"}
                          </span>
                        </div>
                      </div>
                    </div>
                  </a>
                ))
              ) : (
                <div className="py-8 text-center text-slate-500 text-sm">뉴스 데이터가 없습니다</div>
              )}
            </div>
          )}

          {activeTab === "memo" && (
            <div className="space-y-3">
              <textarea
                value={memoText}
                onChange={(e) => setMemoText(e.target.value)}
                placeholder="이 테마에 대한 메모를 입력하세요..."
                className="w-full h-36 sm:h-48 px-3 py-2 sm:px-4 sm:py-3 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm placeholder-slate-500 resize-none focus:outline-none focus:border-blue-500"
              />
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">{memoText.length}자</span>
                <button
                  onClick={() => onMemoChange?.(memoText)}
                  className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  저장
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="h-48 flex items-center justify-center">
          <p className="text-slate-400 text-sm">테마 정보를 불러올 수 없습니다</p>
        </div>
      )}
    </BottomSheet>
  );
}
