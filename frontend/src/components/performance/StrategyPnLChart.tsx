"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { StrategyPnL } from "@/lib/api";

interface Props {
  strategies: StrategyPnL[];
}

export default function StrategyPnLChart({ strategies }: Props) {
  const data = strategies.map((s) => ({
    name: (s.display_name?.replace("전략", "S")) ?? s.strategy_name,
    pnl: s.total_pnl,
    trades: s.trades,
    win_rate: s.win_rate,
    backtest: s.backtest_return,
  }));

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <h3 className="font-semibold text-sm mb-4">전략별 수익률</h3>
      {data.length === 0 || data.every((d) => d.trades === 0) ? (
        <div className="h-48 flex items-center justify-center text-sm text-slate-500">
          <div className="text-center">
            <p>아직 거래 데이터가 없습니다</p>
            <div className="mt-3 space-y-1">
              {strategies.map((s) => (
                <p key={s.strategy_name} className="text-xs">
                  <span className="text-slate-400">{s.display_name}</span>
                  {" "}
                  <span className="text-green-400 font-mono">{s.backtest_return}</span>
                  {" "}
                  <span className="text-blue-400 font-mono">{s.backtest_wr}</span>
                </p>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="name"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              axisLine={{ stroke: "#475569" }}
            />
            <YAxis
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              axisLine={{ stroke: "#475569" }}
              tickFormatter={(v: number) => `${(v / 10000).toFixed(0)}만`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "1px solid #475569",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value: number) => [`${value.toLocaleString()}원`, "수익"]}
            />
            <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
              {data.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.pnl >= 0 ? "#22c55e" : "#ef4444"}
                  fillOpacity={0.7}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
