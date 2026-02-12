"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function SupplyHeatmap({
  themes,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  // 시간대별 수급 데이터 시뮬레이션 (실제로는 API에서)
  const heatmapData = useMemo(() => {
    const hours = [
      "09:00",
      "10:00",
      "11:00",
      "12:00",
      "13:00",
      "14:00",
      "15:00",
    ];
    return themes.slice(0, 8).map((theme) => ({
      ...theme,
      hourlyFlow: hours.map(() => {
        const isBuy = theme.supply_prediction.includes("매수세");
        const base = isBuy ? 30 : -30;
        return base + (Math.random() - 0.5) * 60;
      }),
    }));
  }, [themes]);

  const getHeatColor = (value: number) => {
    if (value > 40) return "bg-emerald-500";
    if (value > 20) return "bg-emerald-500/70";
    if (value > 0) return "bg-emerald-500/40";
    if (value > -20) return "bg-red-500/40";
    if (value > -40) return "bg-red-500/70";
    return "bg-red-500";
  };

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>🗺️</span>
        시간대별 수급 히트맵
      </h3>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="text-left text-xs text-slate-500 pb-2 w-24">
                테마
              </th>
              {["09", "10", "11", "12", "13", "14", "15"].map((h) => (
                <th
                  key={h}
                  className="text-center text-xs text-slate-500 pb-2 w-10"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {heatmapData.map((theme) => (
              <tr
                key={theme.theme_code}
                onClick={() =>
                  onThemeClick(theme.theme_code, theme.theme_name)
                }
                className="cursor-pointer hover:bg-slate-700/20"
              >
                <td className="py-1 pr-2">
                  <span className="text-xs text-white truncate block w-20">
                    {theme.theme_name}
                  </span>
                </td>
                {theme.hourlyFlow.map((flow, i) => (
                  <td key={i} className="p-0.5">
                    <div
                      className={`w-8 h-6 rounded ${getHeatColor(flow)} flex items-center justify-center`}
                      title={`${flow > 0 ? "+" : ""}${flow.toFixed(0)}`}
                    >
                      <span className="text-[9px] text-white/80">
                        {flow > 0 ? "+" : ""}
                        {flow.toFixed(0)}
                      </span>
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-center gap-4 text-xs text-slate-500">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-emerald-500" />
          <span>강한 매수</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-slate-600" />
          <span>중립</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-red-500" />
          <span>강한 매도</span>
        </div>
      </div>
    </div>
  );
}
