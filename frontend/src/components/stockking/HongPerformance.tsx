"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { getStockkingPerformance } from "@/lib/api";
import type {
  HongDailyPerformance,
  HongPerformanceSummary,
  HongWeeklyPerformance,
} from "@/lib/api";
import { TrendingUp, Activity, Target, Calendar } from "lucide-react";

function formatKRW(value: number): string {
  if (Math.abs(value) >= 10000) {
    return `${(value / 10000).toFixed(1)}만`;
  }
  return value.toLocaleString();
}

function SummaryCards({ summary }: { summary: HongPerformanceSummary }) {
  const cards = [
    {
      label: "총 수익",
      value: `${summary.total_pnl >= 0 ? "+" : ""}${formatKRW(summary.total_pnl)}원`,
      color: summary.total_pnl >= 0 ? "text-green-400" : "text-red-400",
      icon: TrendingUp,
      sub: `${summary.trading_days}일 거래`,
    },
    {
      label: "총 거래",
      value: `${summary.total_trades}건`,
      color: "text-blue-400",
      icon: Activity,
      sub: `승 ${summary.win_days}일 / 패 ${summary.loss_days}일`,
    },
    {
      label: "승률",
      value: `${summary.win_rate}%`,
      color: summary.win_rate >= 50 ? "text-green-400" : "text-yellow-400",
      icon: Target,
      sub: `Best ${formatKRW(summary.best_day_pnl)}원`,
    },
    {
      label: "평균 일수익",
      value: `${summary.avg_daily_pnl >= 0 ? "+" : ""}${formatKRW(summary.avg_daily_pnl)}원`,
      color: summary.avg_daily_pnl >= 0 ? "text-green-400" : "text-red-400",
      icon: Calendar,
      sub: `월추정 ${formatKRW(summary.projected_monthly)}원`,
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((c) => (
        <div
          key={c.label}
          className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-3"
        >
          <div className="flex items-center gap-2 mb-1">
            <c.icon size={14} className="text-slate-500" />
            <span className="text-xs text-slate-500">{c.label}</span>
          </div>
          <p className={`text-lg font-bold font-mono ${c.color}`}>{c.value}</p>
          <p className="text-[10px] text-slate-500 mt-0.5">{c.sub}</p>
        </div>
      ))}
    </div>
  );
}

function DailyPnLChart({ data }: { data: HongDailyPerformance[] }) {
  const chartData = data.map((d) => ({
    date: d.date.slice(5),
    pnl: d.pnl,
    trades: d.trades,
    win_rate: d.win_rate,
  }));

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="font-semibold text-sm text-slate-300 mb-3">
        일간 PnL
      </h3>
      {chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-sm text-slate-500">
          거래 데이터가 없습니다
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="date"
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              axisLine={{ stroke: "#475569" }}
              interval={Math.max(0, Math.floor(chartData.length / 8) - 1)}
            />
            <YAxis
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              axisLine={{ stroke: "#475569" }}
              tickFormatter={(v: number) => formatKRW(v)}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "1px solid #475569",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value: number, name: string) => {
                if (name === "pnl")
                  return [`${value.toLocaleString()}원`, "수익"];
                return [value, name];
              }}
              labelFormatter={(label: string) => `날짜: ${label}`}
            />
            <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
              {chartData.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.pnl >= 0 ? "#22c55e" : "#ef4444"}
                  fillOpacity={0.75}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function CumulativeChart({ data }: { data: HongDailyPerformance[] }) {
  const chartData = data.map((d) => ({
    date: d.date.slice(5),
    cumulative: d.cumulative,
  }));

  const isPositive =
    chartData.length > 0 &&
    chartData[chartData.length - 1].cumulative >= 0;

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="font-semibold text-sm text-slate-300 mb-3">
        누적 수익
      </h3>
      {chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-sm text-slate-500">
          거래 데이터가 없습니다
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="cumGrad" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="5%"
                  stopColor={isPositive ? "#22c55e" : "#ef4444"}
                  stopOpacity={0.3}
                />
                <stop
                  offset="95%"
                  stopColor={isPositive ? "#22c55e" : "#ef4444"}
                  stopOpacity={0}
                />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="date"
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              axisLine={{ stroke: "#475569" }}
              interval={Math.max(0, Math.floor(chartData.length / 8) - 1)}
            />
            <YAxis
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              axisLine={{ stroke: "#475569" }}
              tickFormatter={(v: number) => formatKRW(v)}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "1px solid #475569",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value: number) => [
                `${value.toLocaleString()}원`,
                "누적",
              ]}
              labelFormatter={(label: string) => `날짜: ${label}`}
            />
            <Area
              type="monotone"
              dataKey="cumulative"
              stroke={isPositive ? "#22c55e" : "#ef4444"}
              fill="url(#cumGrad)"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function WeeklyTable({ data }: { data: HongWeeklyPerformance[] }) {
  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="font-semibold text-sm text-slate-300 mb-3">
        주간 성과
      </h3>
      {data.length === 0 ? (
        <div className="h-24 flex items-center justify-center text-sm text-slate-500">
          데이터 없음
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700 text-slate-500">
                <th className="text-left py-2 font-medium">주차</th>
                <th className="text-right py-2 font-medium">PnL</th>
                <th className="text-right py-2 font-medium">거래</th>
                <th className="text-right py-2 font-medium">승률</th>
              </tr>
            </thead>
            <tbody>
              {data.map((w) => (
                <tr
                  key={w.week_start}
                  className="border-b border-slate-700/50"
                >
                  <td className="py-1.5 text-slate-400">
                    {w.week_start.slice(5)}
                  </td>
                  <td
                    className={`py-1.5 text-right font-mono ${
                      w.pnl >= 0 ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {w.pnl >= 0 ? "+" : ""}
                    {formatKRW(w.pnl)}
                  </td>
                  <td className="py-1.5 text-right text-slate-400">
                    {w.trades}건
                  </td>
                  <td
                    className={`py-1.5 text-right font-mono ${
                      w.win_rate >= 50 ? "text-green-400" : "text-yellow-400"
                    }`}
                  >
                    {w.win_rate}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CompoundSimulation({ summary }: { summary: HongPerformanceSummary }) {
  if (summary.trading_days === 0 || summary.total_pnl === 0) {
    return null;
  }

  const avgDailyReturn =
    summary.avg_daily_pnl / (summary.total_pnl / summary.trading_days || 1);
  const seedCapital = 10_000_000;
  const dailyRate = summary.avg_daily_pnl / seedCapital;

  const monthly = seedCapital * Math.pow(1 + dailyRate, 22) - seedCapital;
  const quarterly = seedCapital * Math.pow(1 + dailyRate, 66) - seedCapital;
  const yearly = seedCapital * Math.pow(1 + dailyRate, 250) - seedCapital;

  const rows = [
    { period: "1개월 (22일)", estimated: monthly },
    { period: "분기 (66일)", estimated: quarterly },
    { period: "1년 (250일)", estimated: yearly },
  ];

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="font-semibold text-sm text-slate-300 mb-1">
        복리 시뮬레이션
      </h3>
      <p className="text-[10px] text-slate-500 mb-3">
        시드 1,000만원 / 일평균 수익{" "}
        {summary.avg_daily_pnl >= 0 ? "+" : ""}
        {formatKRW(summary.avg_daily_pnl)}원 기준 (단순 복리)
      </p>
      <div className="space-y-2">
        {rows.map((r) => (
          <div
            key={r.period}
            className="flex justify-between items-center text-xs"
          >
            <span className="text-slate-400">{r.period}</span>
            <span
              className={`font-mono font-medium ${
                r.estimated >= 0 ? "text-green-400" : "text-red-400"
              }`}
            >
              {r.estimated >= 0 ? "+" : ""}
              {formatKRW(Math.round(r.estimated))}원
            </span>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-slate-600 mt-2">
        * 실제 수익은 시장 상황에 따라 크게 달라질 수 있습니다
      </p>
    </div>
  );
}

export default function HongPerformance() {
  const { data, isLoading } = useQuery({
    queryKey: ["stockking-performance"],
    queryFn: getStockkingPerformance,
    refetchInterval: 60000,
    retry: 2,
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="animate-pulse h-24 bg-slate-800 rounded-xl" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div className="animate-pulse h-64 bg-slate-800 rounded-xl" />
          <div className="animate-pulse h-64 bg-slate-800 rounded-xl" />
        </div>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const { daily, weekly, summary } = data;

  if (daily.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-6 text-center">
        <TrendingUp size={32} className="text-slate-600 mx-auto mb-2" />
        <p className="text-sm text-slate-400">
          아직 홍인기 전략 거래 기록이 없습니다
        </p>
        <p className="text-xs text-slate-500 mt-1">
          자동매매를 시작하면 성과가 여기에 표시됩니다
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <SummaryCards summary={summary} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <DailyPnLChart data={daily} />
        <CumulativeChart data={daily} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <WeeklyTable data={weekly} />
        <CompoundSimulation summary={summary} />
      </div>
    </div>
  );
}
