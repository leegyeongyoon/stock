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
import type { DayOfWeekPnL } from "@/lib/api";

interface Props {
  days: DayOfWeekPnL[];
}

export default function DayOfWeekChart({ days }: Props) {
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <h3 className="font-semibold text-sm mb-4">요일별 수익률</h3>
      {days.every((d) => d.trades === 0) ? (
        <div className="h-48 flex items-center justify-center text-sm text-slate-500">
          거래 데이터 축적 후 요일별 패턴이 표시됩니다
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="day"
              tick={{ fill: "#94a3b8", fontSize: 12 }}
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
              formatter={(value: number, _name: string) => [
                `${value.toLocaleString()}원`,
                "수익",
              ]}
              labelFormatter={(label: string) => `${label}요일`}
            />
            <Bar dataKey="total_pnl" radius={[4, 4, 0, 0]}>
              {days.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.total_pnl >= 0 ? "#3b82f6" : "#ef4444"}
                  fillOpacity={0.7}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
      {/* Mini stats */}
      <div className="mt-3 flex gap-4 justify-center">
        {days.map((d) => (
          <div key={d.day} className="text-center">
            <p className="text-xs text-slate-500">{d.day}</p>
            <p className="text-xs font-mono text-slate-400">
              {d.trades}건
            </p>
            {d.trades > 0 && (
              <p className="text-xs font-mono text-blue-400">
                {d.win_rate.toFixed(0)}%
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
