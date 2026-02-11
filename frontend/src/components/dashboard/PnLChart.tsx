"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { Trade } from "@/lib/api";

interface Props {
  trades: Trade[];
}

export default function PnLChart({ trades }: Props) {
  // Build cumulative PnL from trades
  const chartData = trades.reduce<{ time: string; pnl: number }[]>(
    (acc, trade) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].pnl : 0;
      const tradeTime = trade.exit_time || trade.timestamp;
      acc.push({
        time: tradeTime
          ? new Date(tradeTime).toLocaleTimeString("ko-KR", {
              hour: "2-digit",
              minute: "2-digit",
            })
          : "-",
        pnl: prev + trade.pnl,
      });
      return acc;
    },
    []
  );

  if (chartData.length === 0) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
        <h3 className="font-semibold mb-4">수익률 차트</h3>
        <div className="h-48 flex items-center justify-center text-slate-500">
          매매 데이터 대기 중...
        </div>
      </div>
    );
  }

  const maxPnl = Math.max(...chartData.map((d) => d.pnl));
  const minPnl = Math.min(...chartData.map((d) => d.pnl));
  const isPositive = chartData[chartData.length - 1]?.pnl >= 0;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <h3 className="font-semibold mb-4">일간 누적 수익</h3>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor={isPositive ? "#22c55e" : "#ef4444"}
                stopOpacity={0.3}
              />
              <stop
                offset="100%"
                stopColor={isPositive ? "#22c55e" : "#ef4444"}
                stopOpacity={0}
              />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="time"
            stroke="#475569"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
          />
          <YAxis
            stroke="#475569"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickFormatter={(v: number) =>
              v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)
            }
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1e293b",
              border: "1px solid #334155",
              borderRadius: "8px",
              color: "#f1f5f9",
            }}
            formatter={(value: number) => [
              `${value.toLocaleString()}원`,
              "누적 손익",
            ]}
          />
          <Area
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? "#22c55e" : "#ef4444"}
            fill="url(#pnlGrad)"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
