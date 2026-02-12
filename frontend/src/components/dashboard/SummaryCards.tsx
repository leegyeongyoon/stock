"use client";

import type { DashboardSummary } from "@/lib/api";

interface Props {
  data: DashboardSummary | undefined;
}

function Card({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <p className="text-sm text-slate-400">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color || "text-white"}`}>
        {value}
      </p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

interface SummaryProps {
  data: DashboardSummary | undefined;
  holdingsSummary?: {
    count: number;
    total_cost: number;
    total_market_value: number;
    total_unrealized_pnl: number;
    total_unrealized_pnl_pct: number;
  };
}

export default function SummaryCards({ data, holdingsSummary }: SummaryProps) {
  if (!data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div
            key={i}
            className="bg-slate-800 rounded-lg p-4 border border-slate-700 animate-pulse h-24"
          />
        ))}
      </div>
    );
  }

  const portfolio = {
    daily_pnl: data.portfolio?.daily_pnl ?? data.today_pnl ?? 0,
    total_pnl_pct: data.portfolio?.total_pnl_pct ?? data.today_pnl_pct ?? 0,
    trades_today: data.portfolio?.trades_today ?? data.total_trades ?? 0,
    positions: data.portfolio?.positions ?? 0,
    win_rate: data.portfolio?.win_rate ?? data.win_rate ?? 0,
    total_equity: data.portfolio?.total_equity ?? 0,
    cash: data.portfolio?.cash ?? 0,
  };
  const pnlColor =
    portfolio.daily_pnl >= 0 ? "text-green-400" : "text-red-400";
  const pnlSign = portfolio.daily_pnl >= 0 ? "+" : "";

  const invested = holdingsSummary?.total_cost ?? 0;
  const marketVal = holdingsSummary?.total_market_value ?? 0;
  const unrealPnl = holdingsSummary?.total_unrealized_pnl ?? 0;
  const unrealPct = holdingsSummary?.total_unrealized_pnl_pct ?? 0;
  const unrealColor = unrealPnl >= 0 ? "text-green-400" : "text-red-400";
  const unrealSign = unrealPnl >= 0 ? "+" : "";

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <Card
        label="총 자산"
        value={`${portfolio.total_equity.toLocaleString()}원`}
        sub={`현금: ${portfolio.cash.toLocaleString()}원`}
      />
      <Card
        label="투자금액"
        value={`${invested.toLocaleString()}원`}
        sub={`${portfolio.positions}종목 보유`}
      />
      <Card
        label="평가금액"
        value={`${marketVal.toLocaleString()}원`}
        sub={`${unrealSign}${unrealPnl.toLocaleString()}원 (${unrealSign}${unrealPct.toFixed(2)}%)`}
        color={unrealColor}
      />
      <Card
        label="오늘 수익"
        value={`${pnlSign}${portfolio.daily_pnl.toLocaleString()}원`}
        sub={`총 수익률: ${pnlSign}${portfolio.total_pnl_pct.toFixed(2)}%`}
        color={pnlColor}
      />
      <Card
        label="매매 횟수"
        value={`${portfolio.trades_today}회`}
        sub={`승률: ${portfolio.win_rate.toFixed(1)}%`}
      />
      <Card
        label="현금 비중"
        value={`${portfolio.total_equity > 0 ? ((portfolio.cash / portfolio.total_equity) * 100).toFixed(1) : "0"}%`}
        sub={`${portfolio.cash.toLocaleString()}원`}
      />
    </div>
  );
}
