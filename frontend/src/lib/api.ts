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
  return fetchApi<{
    state: string;
    today_pnl: number;
    today_pnl_pct: number;
    total_trades: number;
    win_rate: number;
    strategies: Array<{
      name: string;
      status: string;
      signals_today: number;
    }>;
    risk?: {
      circuit_breaker: boolean;
      daily_loss_pct: number;
    };
  }>("/api/dashboard/summary");
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
  display_name: string;
  total_pnl: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_pnl: number;
  backtest_return: string;
}

export interface PnLAnalysisData {
  summary: string;
  winning_factors: string[];
  losing_factors: string[];
  recommendations: string[];
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
}

export interface StrategyDetail {
  meta: StrategyMeta;
  enabled: boolean;
  is_active_time: boolean;
  signals_today: number;
  trades: StrategyTrade[];
  near_entry: NearEntryStock[];
}

export async function getStrategyDetail(name: string) {
  return fetchApi<StrategyDetail>(`/api/strategies/${name}/detail`);
}
