"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getStockDetail, getStockNews } from "@/lib/api";
import BottomSheet from "../common/BottomSheet";

const formatNumber = (num: number) => {
  if (Math.abs(num) >= 100000000) return (num / 100000000).toFixed(1) + "억";
  if (Math.abs(num) >= 10000) return (num / 10000).toFixed(1) + "만";
  return num.toLocaleString();
};

const GRADE_COLORS: Record<string, string> = {
  A: "from-emerald-400 to-emerald-600",
  B: "from-blue-400 to-blue-600",
  C: "from-amber-400 to-amber-600",
  D: "from-orange-400 to-orange-600",
  F: "from-red-400 to-red-600",
};

export default function StockDetailSheet({
  stockCode,
  stockName,
  onClose,
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

  const { data: newsData, isLoading: newsLoading } = useQuery({
    queryKey: ["stock-news", stockCode, stockName],
    queryFn: () => getStockNews(stockCode, stockName, 14),
    enabled: !!stockCode && activeTab === "news",
  });

  return (
    <BottomSheet open={true} onClose={onClose} title={stockName}>
      {isLoading ? (
        <div className="h-64 flex items-center justify-center">
          <div className="text-center">
            <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p className="text-slate-400 text-sm">종목 분석 중...</p>
          </div>
        </div>
      ) : data ? (
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-start gap-3 sm:gap-5">
            <div className={`w-14 h-14 sm:w-20 sm:h-20 rounded-xl sm:rounded-2xl bg-gradient-to-br ${GRADE_COLORS[data.buy_signal.grade]} flex flex-col items-center justify-center shadow-xl flex-shrink-0`}>
              <span className="text-xl sm:text-3xl font-black text-white">{data.buy_signal.grade}</span>
              <span className="text-[10px] sm:text-sm text-white/80 font-medium">{data.buy_signal.score}점</span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-lg sm:text-2xl font-bold text-white">{stockName}</h2>
                <span className="px-2 py-0.5 bg-slate-700 rounded text-xs text-slate-400">{stockCode}</span>
              </div>
              <div className="flex items-baseline gap-2 mt-1">
                <span className={`text-xl sm:text-3xl font-bold ${data.change_rate > 0 ? "text-emerald-400" : data.change_rate < 0 ? "text-red-400" : "text-white"}`}>
                  {data.current_price.toLocaleString()}원
                </span>
                <span className={`text-sm ${data.change_rate > 0 ? "text-emerald-400" : data.change_rate < 0 ? "text-red-400" : "text-slate-400"}`}>
                  {data.change_rate > 0 ? "▲" : data.change_rate < 0 ? "▼" : ""} {Math.abs(data.change_rate).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>

          {/* Recommendation */}
          <div className={`p-3 sm:p-4 rounded-xl ${
            data.buy_signal.recommendation.includes("매수") ? "bg-emerald-500/10 border border-emerald-500/30" :
            data.buy_signal.recommendation.includes("비추천") ? "bg-red-500/10 border border-red-500/30" :
            "bg-amber-500/10 border border-amber-500/30"
          }`}>
            <p className={`font-semibold text-sm ${
              data.buy_signal.recommendation.includes("매수") ? "text-emerald-400" :
              data.buy_signal.recommendation.includes("비추천") ? "text-red-400" : "text-amber-400"
            }`}>
              {data.buy_signal.recommendation}
            </p>
            <p className="text-xs text-slate-400 mt-1">{data.summary}</p>
          </div>

          {/* Tabs */}
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            {[
              { id: "signal" as const, label: "투자신호" },
              { id: "technical" as const, label: "기술분석" },
              { id: "chart" as const, label: "분봉" },
              { id: "news" as const, label: "뉴스" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs sm:text-sm font-medium transition-colors whitespace-nowrap ${
                  activeTab === tab.id ? "bg-blue-500 text-white" : "text-slate-400 hover:text-white hover:bg-slate-700/50"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Signal tab */}
          {activeTab === "signal" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="p-3 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
                  <h4 className="text-xs sm:text-sm font-semibold text-emerald-400 mb-2">긍정 요인</h4>
                  <ul className="space-y-1.5">
                    {data.buy_signal.positives.map((p, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs sm:text-sm text-emerald-300">
                        <span className="text-emerald-500 flex-shrink-0">✓</span>
                        {p}
                      </li>
                    ))}
                    {data.buy_signal.positives.length === 0 && <li className="text-xs text-slate-500">없음</li>}
                  </ul>
                </div>
                <div className="p-3 rounded-xl bg-red-500/5 border border-red-500/20">
                  <h4 className="text-xs sm:text-sm font-semibold text-red-400 mb-2">주의 요인</h4>
                  <ul className="space-y-1.5">
                    {data.buy_signal.negatives.map((n, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs sm:text-sm text-red-300">
                        <span className="text-red-500 flex-shrink-0">✗</span>
                        {n}
                      </li>
                    ))}
                    {data.buy_signal.negatives.length === 0 && <li className="text-xs text-slate-500">없음</li>}
                  </ul>
                </div>
              </div>

              {/* Supply analysis */}
              <div>
                <h4 className="text-xs sm:text-sm font-semibold text-slate-300 mb-2">수급 분석</h4>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
                  {[data.supply_3d, data.supply_7d, data.supply_10d, data.supply_30d].map((supply) => (
                    <div key={supply.days} className="p-2 sm:p-3 rounded-lg sm:rounded-xl bg-slate-800/50 border border-slate-700/50">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[10px] sm:text-xs text-slate-500">{supply.days}일</span>
                        <span className={`text-[10px] sm:text-xs px-1 py-0.5 rounded ${
                          supply.trend.includes("매집") ? "bg-emerald-500/20 text-emerald-400" :
                          supply.trend.includes("매도") ? "bg-red-500/20 text-red-400" :
                          "bg-slate-600 text-slate-400"
                        }`}>
                          {supply.trend}
                        </span>
                      </div>
                      <div className="text-[10px] sm:text-xs space-y-0.5">
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

              {/* Volume & Bollinger */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
                  <h4 className="text-xs font-semibold text-slate-300 mb-2">거래량</h4>
                  <div className="flex items-baseline gap-2 mb-1">
                    <span className="text-lg font-bold text-white">{formatNumber(data.volume)}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      data.volume_analysis.trend === "급증" ? "bg-red-500/20 text-red-400" :
                      data.volume_analysis.trend === "증가" ? "bg-emerald-500/20 text-emerald-400" :
                      "bg-slate-600 text-slate-400"
                    }`}>
                      {data.volume_analysis.trend}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">{data.volume_analysis.comment}</p>
                </div>
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
                  <h4 className="text-xs font-semibold text-slate-300 mb-2">볼린저밴드</h4>
                  <div className="flex items-baseline gap-2 mb-2">
                    <span className="text-lg font-bold text-white">{data.bb_position.zone}</span>
                    <span className="text-xs text-slate-400">{data.bb_position.position_pct.toFixed(0)}%</span>
                  </div>
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

          {/* Technical tab */}
          {activeTab === "technical" && (
            <div className="space-y-4">
              <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
                <h4 className="text-xs font-semibold text-slate-300 mb-3">52주 가격 위치</h4>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <p className="text-xs text-slate-500">52주 고점</p>
                    <p className="text-base sm:text-lg font-bold text-white">{data.price_position.high_52w.toLocaleString()}</p>
                    <p className={`text-xs ${data.price_position.from_high_pct > -10 ? "text-emerald-400" : "text-red-400"}`}>
                      {data.price_position.from_high_pct.toFixed(1)}%
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">52주 저점</p>
                    <p className="text-base sm:text-lg font-bold text-white">{data.price_position.low_52w.toLocaleString()}</p>
                    <p className="text-xs text-emerald-400">+{data.price_position.from_low_pct.toFixed(1)}%</p>
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap">
                  {[
                    { label: "MA20", above: data.price_position.above_ma20 },
                    { label: "MA60", above: data.price_position.above_ma60 },
                    { label: "MA120", above: data.price_position.above_ma120 },
                  ].map((ma) => (
                    <span
                      key={ma.label}
                      className={`px-2 py-1 rounded-lg text-xs font-medium ${
                        ma.above ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
                      }`}
                    >
                      {ma.label} {ma.above ? "↑" : "↓"}
                    </span>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 sm:gap-4">
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50 text-center">
                  <p className="text-[10px] sm:text-xs text-slate-500 mb-1">RSI</p>
                  <p className={`text-lg sm:text-2xl font-bold ${
                    data.indicators.rsi14 > 70 ? "text-red-400" : data.indicators.rsi14 < 30 ? "text-emerald-400" : "text-amber-400"
                  }`}>
                    {data.indicators.rsi14.toFixed(1)}
                  </p>
                </div>
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50 text-center">
                  <p className="text-[10px] sm:text-xs text-slate-500 mb-1">MACD</p>
                  <p className={`text-lg sm:text-2xl font-bold ${data.indicators.macd_hist > 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {data.indicators.macd.toFixed(0)}
                  </p>
                </div>
                <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50 text-center">
                  <p className="text-[10px] sm:text-xs text-slate-500 mb-1">Stoch</p>
                  <p className={`text-lg sm:text-2xl font-bold ${
                    data.indicators.stoch_k > 80 ? "text-red-400" : data.indicators.stoch_k < 20 ? "text-emerald-400" : "text-slate-300"
                  }`}>
                    {data.indicators.stoch_k.toFixed(1)}
                  </p>
                </div>
              </div>

              <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
                <h4 className="text-xs font-semibold text-slate-300 mb-3">밸류에이션</h4>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: "시가총액", value: formatNumber(data.valuation.market_cap * 100000000) + "원" },
                    { label: "PER", value: data.valuation.per > 0 ? data.valuation.per.toFixed(1) + "배" : "N/A", highlight: data.valuation.per > 0 && data.valuation.per < 15 },
                    { label: "PBR", value: data.valuation.pbr > 0 ? data.valuation.pbr.toFixed(2) + "배" : "N/A", highlight: data.valuation.pbr > 0 && data.valuation.pbr < 1 },
                    { label: "배당률", value: data.valuation.dividend_yield > 0 ? data.valuation.dividend_yield.toFixed(2) + "%" : "N/A" },
                  ].map((v) => (
                    <div key={v.label}>
                      <p className="text-xs text-slate-500">{v.label}</p>
                      <p className={`text-xs sm:text-sm font-bold ${v.highlight ? "text-emerald-400" : "text-white"}`}>{v.value}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Chart tab */}
          {activeTab === "chart" && (
            <div className="space-y-3">
              <div className="grid grid-cols-4 gap-2">
                {[
                  { label: "시가", value: data.open_price, color: "text-white" },
                  { label: "고가", value: data.high_price, color: "text-red-400" },
                  { label: "저가", value: data.low_price, color: "text-blue-400" },
                  { label: "전일", value: data.prev_close, color: "text-slate-400" },
                ].map((item) => (
                  <div key={item.label} className="p-2 sm:p-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-center">
                    <p className="text-[10px] sm:text-xs text-slate-500">{item.label}</p>
                    <p className={`text-xs sm:text-sm font-mono font-bold ${item.color}`}>{item.value.toLocaleString()}</p>
                  </div>
                ))}
              </div>

              <div className="rounded-xl bg-slate-800/50 border border-slate-700/50 overflow-hidden">
                <div className="p-2 sm:p-3 border-b border-slate-700/50">
                  <h4 className="text-xs sm:text-sm font-semibold text-slate-300">5분봉</h4>
                </div>
                {data.candles_5m.length > 0 ? (
                  <div className="max-h-52 sm:max-h-64 overflow-y-auto">
                    <table className="w-full text-[10px] sm:text-xs">
                      <thead className="bg-slate-800/80 sticky top-0">
                        <tr className="text-slate-500">
                          <th className="py-1.5 px-2 text-left">시간</th>
                          <th className="py-1.5 px-2 text-right">시가</th>
                          <th className="py-1.5 px-2 text-right hidden sm:table-cell">고가</th>
                          <th className="py-1.5 px-2 text-right hidden sm:table-cell">저가</th>
                          <th className="py-1.5 px-2 text-right">종가</th>
                          <th className="py-1.5 px-2 text-right">변동</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.candles_5m.slice(-10).reverse().map((candle, i) => {
                          const change = candle.close - candle.open;
                          const rate = candle.open > 0 ? (change / candle.open) * 100 : 0;
                          return (
                            <tr key={i} className="border-t border-slate-700/30">
                              <td className="py-1.5 px-2 text-slate-400 font-mono">{candle.time}</td>
                              <td className="py-1.5 px-2 text-right font-mono text-slate-300">{candle.open.toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right font-mono text-red-400 hidden sm:table-cell">{candle.high.toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right font-mono text-blue-400 hidden sm:table-cell">{candle.low.toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right font-mono text-slate-300">{candle.close.toLocaleString()}</td>
                              <td className={`py-1.5 px-2 text-right font-mono ${change > 0 ? "text-emerald-400" : change < 0 ? "text-red-400" : "text-slate-400"}`}>
                                {rate > 0 ? "+" : ""}{rate.toFixed(2)}%
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="p-4 text-center text-slate-500 text-xs">분봉 데이터 없음</p>
                )}
              </div>
            </div>
          )}

          {/* News tab */}
          {activeTab === "news" && (
            <div className="space-y-3">
              {newsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
                </div>
              ) : newsData && newsData.news_items.length > 0 ? (
                <>
                  <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
                    <div className="grid grid-cols-3 gap-2 text-center">
                      <div>
                        <p className="text-[10px] sm:text-xs text-slate-500">핫 스코어</p>
                        <p className={`text-base sm:text-lg font-bold ${newsData.hot_score > 50 ? "text-red-400" : newsData.hot_score > 30 ? "text-amber-400" : "text-slate-400"}`}>
                          {newsData.hot_score.toFixed(0)}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] sm:text-xs text-slate-500">감성</p>
                        <p className={`text-base sm:text-lg font-bold ${
                          newsData.sentiment.includes("positive") ? "text-emerald-400" :
                          newsData.sentiment.includes("negative") ? "text-red-400" : "text-slate-400"
                        }`}>
                          {newsData.sentiment === "very_positive" ? "매우 긍정" :
                           newsData.sentiment === "positive" ? "긍정" :
                           newsData.sentiment === "negative" ? "부정" : "중립"}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] sm:text-xs text-slate-500">기사수</p>
                        <p className="text-base sm:text-lg font-bold text-blue-400">{newsData.news_count}</p>
                      </div>
                    </div>
                  </div>
                  <div className="space-y-2">
                    {newsData.news_items.map((item, i) => (
                      <a
                        key={i}
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block p-3 rounded-xl bg-slate-800/30 border border-slate-700/30 hover:bg-slate-800/60 transition-colors"
                      >
                        <h5 className="text-xs sm:text-sm font-medium text-white line-clamp-2">{item.title}</h5>
                        <div className="flex items-center gap-2 mt-1.5 text-xs text-slate-500">
                          <span>{item.source}</span>
                          {item.published_at && <span>{new Date(item.published_at).toLocaleDateString("ko-KR")}</span>}
                        </div>
                      </a>
                    ))}
                  </div>
                </>
              ) : (
                <div className="py-8 text-center text-slate-500 text-sm">최근 2주간 관련 뉴스가 없습니다</div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="h-48 flex items-center justify-center">
          <p className="text-slate-400 text-sm">데이터를 불러올 수 없습니다</p>
        </div>
      )}
    </BottomSheet>
  );
}
