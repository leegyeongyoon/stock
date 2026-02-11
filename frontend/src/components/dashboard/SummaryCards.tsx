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

export default function SummaryCards({ data }: Props) {
  if (!data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
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

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card
        label="오늘 수익"
        value={`${pnlSign}${portfolio.daily_pnl.toLocaleString()}원`}
        sub={`총 수익률: ${pnlSign}${portfolio.total_pnl_pct.toFixed(2)}%`}
        color={pnlColor}
      />
      <Card
        label="매매 횟수"
        value={`${portfolio.trades_today}회`}
        sub={`보유: ${portfolio.positions}종목`}
      />
      <Card
        label="승률"
        value={`${portfolio.win_rate.toFixed(1)}%`}
        sub={`오늘 매매 기준`}
      />
      <Card
        label="총 자산"
        value={`${portfolio.total_equity.toLocaleString()}원`}
        sub={`현금: ${portfolio.cash.toLocaleString()}원`}
      />
    </div>
  );
}
