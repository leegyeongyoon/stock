const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8088";

// Types
export interface Holding {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  cost_basis: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  pnl_amount?: number;
  pnl_pct?: number;
  strategy_name?: string;
  sl_price?: number;
  tp_price?: number;
  stop_loss_price?: number;
  take_profit_price?: number;
}

export interface HoldingsSummary {
  count: number;
  total_cost: number;
  total_market_value: number;
  total_unrealized_pnl: number;
  total_unrealized_pnl_pct: number;
}

export interface Trade {
  stock_code: string;
  stock_name: string;
  strategy_name: string;
  side: string;
  quantity: number;
  price: number;
  pnl: number;
  timestamp: string;
  exit_time?: string;
}

export interface Strategy {
  strategy_name: string;
  display_name: string;
  backtest_return: string;
  backtest_wr: string;
  trades: number;
  wins: number;
  losses: number;
  total_pnl: number;
  avg_pnl: number;
  max_win: number;
  max_loss: number;
  win_rate: number;
}

export interface DashboardStrategy {
  name: string;
  status: string;
  signals_today: number;
  enabled?: boolean;
  display_name?: string;
  time_window?: string;
  backtest_return?: string;
  backtest_wr?: string;
  backtest_trades?: number;
  description?: string;
  sl?: string;
  tp?: string;
  conditions?: string[];
}

export interface SystemEvent {
  timestamp: string;
  event_type: string;
  message: string;
  severity: string;
}

export interface DashboardSummary {
  state: string;
  today_pnl: number;
  today_pnl_pct: number;
  total_trades: number;
  win_rate: number;
  strategies: DashboardStrategy[];
  risk?: {
    circuit_breaker: boolean;
    daily_loss_pct: number;
  };
  portfolio?: {
    daily_pnl: number;
    total_pnl_pct: number;
    trades_today: number;
    positions: number;
    win_rate: number;
    total_equity: number;
    cash: number;
  };
}

export interface Position {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  strategy_name: string;
  stop_loss_price?: number;
  take_profit_price?: number;
}

export interface DayOfWeekPnL {
  day: string;
  trades: number;
  wins: number;
  total_pnl: number;
  win_rate: number;
}

async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}

async function postApi<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}

// Dashboard
export async function getDashboardSummary() {
  return fetchApi<DashboardSummary>("/api/dashboard/summary");
}

export async function getPnL() {
  return fetchApi<{
    daily_pnl: number;
    total_pnl_pct: number;
    total_equity: number;
    cash: number;
    trades: Array<{
      stock_code: string;
      stock_name: string;
      strategy_name: string;
      side: string;
      quantity: number;
      price: number;
      pnl: number;
      timestamp: string;
    }>;
  }>("/api/dashboard/pnl");
}

// Positions
export async function getPositions() {
  return fetchApi<{
    positions: Array<{
      stock_code: string;
      stock_name: string;
      quantity: number;
      avg_price: number;
      current_price: number;
      market_value: number;
      unrealized_pnl: number;
      unrealized_pnl_pct: number;
      strategy_name: string;
    }>;
  }>("/api/positions");
}

export async function getHoldings() {
  return fetchApi<{
    holdings: Array<{
      stock_code: string;
      stock_name: string;
      quantity: number;
      avg_price: number;
      current_price: number;
      cost_basis: number;
      market_value: number;
      unrealized_pnl: number;
      unrealized_pnl_pct: number;
    }>;
    summary: {
      count: number;
      total_cost: number;
      total_market_value: number;
      total_unrealized_pnl: number;
      total_unrealized_pnl_pct: number;
    };
  }>("/api/positions/holdings");
}

// System
export async function getEvents(limit = 50) {
  return fetchApi<{
    events: Array<{
      timestamp: string;
      event_type: string;
      message: string;
      severity: string;
    }>;
  }>(`/api/system/events?limit=${limit}`);
}

export async function getSystemStatus() {
  return fetchApi<{
    engine_state: string;
    universe_count: number;
    data_bars?: {
      total_stocks_with_data: number;
    };
    risk?: {
      circuit_breaker: boolean;
      daily_loss_pct: number;
    };
    ws_subscriptions?: number;
  }>("/api/system/status");
}

export async function startTrading() {
  return postApi<{ message: string; state: string }>("/api/system/start");
}

export async function stopTrading() {
  return postApi<{ message: string; state: string }>("/api/system/stop");
}

export async function emergencyStop() {
  return postApi<{ message: string; state: string }>("/api/system/emergency-stop");
}

// Aliases for Header component
export const startEngine = startTrading;
export const stopEngine = stopTrading;

// Analysis
export async function getStrategies() {
  return fetchApi<{
    strategies: Array<{
      name: string;
      strategy_name: string;
      display_name: string;
      backtest_return: string;
      backtest_wr: string;
      trades: number;
      wins: number;
      losses: number;
      total_pnl: number;
      avg_pnl: number;
      max_win: number;
      max_loss: number;
      win_rate: number;
    }>;
  }>("/api/analysis/by-strategy");
}

export async function getDailyReport() {
  return fetchApi<{
    total_trades: number;
    total_pnl: number;
    win_rate: number;
    by_strategy: Record<
      string,
      {
        trades: number;
        wins: number;
        pnl: number;
      }
    >;
    trades: Array<{
      stock_code: string;
      stock_name: string;
      strategy_name: string;
      side: string;
      quantity: number;
      price: number;
      pnl: number;
      timestamp: string;
    }>;
  }>("/api/analysis/daily-report");
}

export async function getPnLByDayOfWeek() {
  return fetchApi<{
    days: Array<{
      day: string;
      trades: number;
      wins: number;
      total_pnl: number;
      win_rate: number;
    }>;
  }>("/api/analysis/by-day-of-week");
}

// Trade History
export interface TradeHistoryItem {
  id: number;
  stock_code: string;
  stock_name: string;
  strategy_name: string;
  side: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  entry_time: string;
  exit_time: string;
  hold_days: number;
  exit_reason: string;
}

export async function getTradeHistory(params?: {
  strategy?: string;
  sort_by?: string;
  order?: string;
  limit?: number;
  offset?: number;
}) {
  const searchParams = new URLSearchParams();
  if (params?.strategy) searchParams.set("strategy", params.strategy);
  if (params?.sort_by) searchParams.set("sort_by", params.sort_by);
  if (params?.order) searchParams.set("order", params.order);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));

  const query = searchParams.toString();
  return fetchApi<{
    trades: TradeHistoryItem[];
    total: number;
  }>(`/api/trades/history${query ? `?${query}` : ""}`);
}

// Strategy toggle
export async function toggleStrategy(strategyName: string) {
  return postApi<{ message: string }>(`/api/strategies/${strategyName}/toggle`);
}

// Performance types
export interface StrategyPnL {
  name: string;
  strategy_name: string;
  display_name: string;
  total_pnl: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_pnl: number;
  backtest_return: string;
  backtest_wr: string;
}

export interface PnLAnalysisData {
  summary: string;
  winning_factors: string[];
  losing_factors: string[];
  recommendations: string[];
  recommendation: string;
  best_strategy: string;
  worst_strategy: string;
}

export async function getPnLByStrategy() {
  return fetchApi<{
    strategies: StrategyPnL[];
  }>("/api/analysis/by-strategy");
}

export async function getPnLAnalysis() {
  return fetchApi<PnLAnalysisData>("/api/analysis/pnl-analysis");
}

// Strategy detail
export interface StrategyMeta {
  name: string;
  display_name: string;
  time_window: string;
  description: string;
  sl: string;
  tp: string;
  conditions: string[];
  backtest_return: string;
  backtest_wr: string;
  backtest_trades: number;
}

export interface StrategyTrade {
  stock_code: string;
  stock_name: string;
  side: string;
  price: number;
  quantity: number;
  pnl: number;
  timestamp: string;
}

export interface NearEntryStock {
  stock_code: string;
  stock_name: string;
  current_price: number;
  rsi: number;
  distance_pct: number;
  reason: string;
  score: number;
  max_score: number;
  conditions_met: string[];
  conditions_unmet: string[];
}

export interface StrategyPosition {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export interface StrategyDetail {
  meta: StrategyMeta;
  enabled: boolean;
  is_active_time: boolean;
  signals_today: number;
  trades: StrategyTrade[];
  near_entry: NearEntryStock[];
  positions: StrategyPosition[];
}

export async function getStrategyDetail(name: string) {
  return fetchApi<StrategyDetail>(`/api/strategies/${name}/detail`);
}

// Theme Analysis Types
export interface ThemeStock {
  code: string;
  name: string;
  theme_name?: string;
  score?: number;
  total_score?: number;
  change_rate: number;
  volume: number;
  foreign_change: number;
  inst_change: number;
  is_leader: boolean;
  recommendation: string;
  scores?: {
    momentum: number;
    volume: number;
    foreign: number;
    inst: number;
    leader: number;
  };
}

export interface Theme {
  code: string;
  name: string;
  change_rate: number;
  score: number;
  momentum: string;
  is_hot: boolean;
  stock_count: number;
  up_count: number;
  down_count: number;
  leader: string | null;
  foreign_buying: boolean;
  inst_buying: boolean;
}

export interface ThemeDetail extends Theme {
  volume_surge: boolean;
  analysis_comment: string;
  stocks: ThemeStock[];
  top_stocks?: ThemeStock[];
}

export interface NewsItem {
  title: string;
  source: string;
  url: string;
  summary: string;
  sentiment: string;
  relevance_score: number;
}

export interface NewsAnalysis {
  theme_name: string;
  news_count: number;
  hot_score: number;
  sentiment: string;
  key_issues: string[];
  supply_prediction: string;
  confidence: number;
}

export interface SupplyFlow {
  theme_name: string;
  current_supply: string;
  foreign_flow: string;
  inst_flow: string;
  volume_change: number;
  is_surging: boolean;
  alert_message: string;
}

export interface MarketAnalysis {
  timestamp: string;
  phase: string;
  phase_label: string;
  market_sentiment: string;
  top_sectors: string[];
  caution_message: string;
  hot_themes: ThemeDetail[];
  recommended_stocks: ThemeStock[];
}

export interface PremarketAnalysis {
  analysis_time: string;
  market_phase: string;
  previous_hot_themes: string[];
  previous_rising_themes: string[];
  top_themes: Array<{ name: string; change_rate: number }>;
  news_analysis: NewsAnalysis[];
  predicted_hot_themes: string[];
  recommendation: string;
}

export interface SupplyPrediction {
  timestamp: string;
  phase: string;
  predictions: Array<{
    rank: number;
    theme: string;
    hot_score: number;
    sentiment: string;
    supply_prediction: string;
    confidence: number;
    key_issues: string[];
  }>;
  summary: {
    predicted_hot: string[];
    buy_expected: string[];
    caution: string[];
  };
}

// Theme Analysis API
export async function getMarketAnalysis(refresh = false) {
  return fetchApi<MarketAnalysis>(`/api/themes/analysis?refresh=${refresh}`);
}

export async function getPremarketAnalysis() {
  return fetchApi<PremarketAnalysis>("/api/themes/premarket");
}

export async function getMarketPhase() {
  return fetchApi<{ phase: string; label: string; timestamp: string }>("/api/themes/phase");
}

export async function getTopStocks(limit = 10) {
  return fetchApi<{
    timestamp: string;
    phase: string;
    sentiment: string;
    stocks: ThemeStock[];
  }>(`/api/themes/top-stocks?limit=${limit}`);
}

export async function getThemesList() {
  return fetchApi<{ timestamp: string; themes: Theme[] }>("/api/themes/themes");
}

export async function getThemeDetail(themeCode: string) {
  return fetchApi<ThemeDetail>(`/api/themes/themes/${themeCode}`);
}

export async function getThemeNews(themeName: string) {
  return fetchApi<NewsItem[]>(`/api/themes/news/${encodeURIComponent(themeName)}`);
}

export async function getNewsAnalysis(themes: string[] = ["AI", "반도체", "2차전지", "로봇", "바이오"]) {
  return fetchApi<NewsAnalysis[]>(`/api/themes/news-analysis?themes=${themes.join(",")}`);
}

export async function getThemeSupply(themeName: string) {
  return fetchApi<SupplyFlow>(`/api/themes/supply/${encodeURIComponent(themeName)}`);
}

export async function getAllSupply() {
  return fetchApi<SupplyFlow[]>("/api/themes/supply-all");
}

export async function getSupplyPrediction() {
  return fetchApi<SupplyPrediction>("/api/themes/prediction");
}

// 기간별 핫 테마
export interface PeriodHotTheme {
  rank: number;
  theme_code: string;
  theme_name: string;
  period_days: number;
  change_rate: number;
  avg_change_rate: number;
  stock_count: number;
  up_count: number;
  down_count: number;
  up_ratio: number;
  top_gainers: Array<{
    code: string;
    name: string;
    change_rate: number;
    start_price: number;
    end_price: number;
  }>;
  leader_stock: string;
  momentum: string;
  strength: string;
}

export async function getHotThemesByPeriod(days: number = 1, topN: number = 20) {
  return fetchApi<PeriodHotTheme[]>(`/api/themes/hot-themes/${days}?top_n=${topN}`);
}

// Stock Detail Types
export interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TechnicalIndicators {
  ma5: number;
  ma10: number;
  ma20: number;
  ma60: number;
  ma120: number;
  rsi14: number;
  macd: number;
  macd_signal: number;
  macd_hist: number;
  stoch_k: number;
  stoch_d: number;
}

export interface MultiDaySupply {
  days: number;
  foreign_total: number;
  inst_total: number;
  foreign_avg: number;
  inst_avg: number;
  trend: string;
}

export interface VolumeAnalysis {
  today: number;
  avg_5d: number;
  avg_20d: number;
  ratio_vs_5d: number;
  ratio_vs_20d: number;
  trend: string;
  comment: string;
}

export interface BollingerPosition {
  upper: number;
  middle: number;
  lower: number;
  current: number;
  position_pct: number;
  zone: string;
  comment: string;
}

export interface PricePosition {
  current: number;
  high_52w: number;
  low_52w: number;
  from_high_pct: number;
  from_low_pct: number;
  ma_20: number;
  ma_60: number;
  ma_120: number;
  above_ma20: boolean;
  above_ma60: boolean;
  above_ma120: boolean;
  position_comment: string;
}

export interface Valuation {
  market_cap: number;
  per: number;
  pbr: number;
  eps: number;
  bps: number;
  dividend_yield: number;
  comment: string;
}

export interface BuySignal {
  score: number;
  grade: string;
  positives: string[];
  negatives: string[];
  recommendation: string;
  risk_level: string;
}

export interface StockDetailFull {
  code: string;
  name: string;
  current_price: number;
  change_rate: number;
  change_amount: number;
  volume: number;
  trading_value: number;
  open_price: number;
  high_price: number;
  low_price: number;
  prev_close: number;

  // 다일간 수급 분석
  supply_3d: MultiDaySupply;
  supply_7d: MultiDaySupply;
  supply_10d: MultiDaySupply;
  supply_30d: MultiDaySupply;

  // 거래량 분석
  volume_analysis: VolumeAnalysis;

  // 볼린저밴드 위치
  bb_position: BollingerPosition;

  // 가격 위치
  price_position: PricePosition;

  // 밸류에이션
  valuation: Valuation;

  // 기술적 지표
  indicators: TechnicalIndicators;

  // 분봉 데이터
  candles_1m: CandleData[];
  candles_5m: CandleData[];

  // 매수 신호 분석
  buy_signal: BuySignal;

  // 종합 코멘트
  summary: string;
}

export interface NewsDetailItem {
  title: string;
  source: string;
  url: string;
  summary: string;
  sentiment: string;
  relevance_score: number;
  published_at: string | null;
}

export interface NewsDetailResponse {
  theme_name: string;
  keywords: string[];
  analysis: {
    news_count: number;
    hot_score: number;
    sentiment: string;
    supply_prediction: string;
    confidence: number;
    key_issues: string[];
  };
  news_items: NewsDetailItem[];
}

export async function getStockDetail(code: string, name: string = "") {
  return fetchApi<StockDetailFull>(`/api/themes/stock/${code}?name=${encodeURIComponent(name)}`);
}

export async function getNewsDetail(themeName: string) {
  return fetchApi<NewsDetailResponse>(`/api/themes/news-detail/${encodeURIComponent(themeName)}`);
}

// Stock News Types
export interface StockNewsResponse {
  stock_code: string;
  stock_name: string;
  news_count: number;
  hot_score: number;
  sentiment: string;
  key_issues: string[];
  news_items: NewsDetailItem[];
}

export async function getStockNews(code: string, name: string = "", days: number = 14) {
  return fetchApi<StockNewsResponse>(`/api/themes/stock-news/${code}?name=${encodeURIComponent(name)}&days=${days}`);
}

// Theme Ranking Types
export interface ThemeRanking {
  rank: number;
  theme_name: string;
  theme_code: string;
  total_score: number;
  grade: string;

  // 세부 점수
  momentum_score: number;
  news_score: number;
  sentiment_score: number;
  supply_score: number;

  // 원본 데이터
  change_rate: number;
  news_count: number;
  news_hot_score: number;
  sentiment: string;
  supply_prediction: string;
  confidence: number;

  // 분석
  key_issues: string[];
  recommendation: string;
}

export async function getThemeRanking(topN: number = 30) {
  return fetchApi<ThemeRanking[]>(`/api/themes/ranking?top_n=${topN}`);
}
