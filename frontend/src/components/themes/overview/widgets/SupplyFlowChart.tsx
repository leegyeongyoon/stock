"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function SupplyFlowChart({
  themes,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  // 외인/기관 매수세가 있는 테마 필터링 (실제 데이터 기반으로 시뮬레이션)
  const supplyData = useMemo(() => {
    return themes.slice(0, 10).map((theme) => {
      // 수급 예측 기반 데이터 생성
      const isForeignBuy =
        theme.supply_prediction.includes("외인") &&
        theme.supply_prediction.includes("매수");
      const isInstBuy =
        theme.supply_prediction.includes("기관") &&
        theme.supply_prediction.includes("매수");
      const isForeignSell =
        theme.supply_prediction.includes("외인") &&
        theme.supply_prediction.includes("매도");
      const isInstSell =
        theme.supply_prediction.includes("기관") &&
        theme.supply_prediction.includes("매도");

      return {
        ...theme,
        foreignFlow: isForeignBuy
          ? Math.random() * 100 + 50
          : isForeignSell
            ? -(Math.random() * 100 + 50)
            : (Math.random() - 0.5) * 40,
        instFlow: isInstBuy
          ? Math.random() * 80 + 30
          : isInstSell
            ? -(Math.random() * 80 + 30)
            : (Math.random() - 0.5) * 30,
      };
    });
  }, [themes]);

  const maxFlow = Math.max(
    ...supplyData.map((d) =>
      Math.max(Math.abs(d.foreignFlow), Math.abs(d.instFlow))
    )
  );

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-white flex items-center gap-2">
          <span>📊</span>
          외인/기관 수급 흐름
        </h3>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-blue-500" />
            <span className="text-slate-400">외인</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-purple-500" />
            <span className="text-slate-400">기관</span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {supplyData.map((theme) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className="group cursor-pointer hover:bg-slate-700/30 rounded-lg p-2 transition-colors"
          >
            <div className="flex items-center gap-3 mb-2">
              <span className="text-sm font-medium text-white truncate w-24">
                {theme.theme_name}
              </span>
              <div className="flex-1 relative h-6">
                {/* 중앙선 */}
                <div className="absolute left-1/2 top-0 bottom-0 w-px bg-slate-600" />

                {/* 외인 바 */}
                <div
                  className={`absolute top-0 h-3 rounded-sm transition-all ${
                    theme.foreignFlow >= 0
                      ? "bg-blue-500 left-1/2"
                      : "bg-blue-500/60 right-1/2"
                  }`}
                  style={{
                    width: `${(Math.abs(theme.foreignFlow) / maxFlow) * 45}%`,
                    ...(theme.foreignFlow < 0
                      ? { right: "50%" }
                      : { left: "50%" }),
                  }}
                />

                {/* 기관 바 */}
                <div
                  className={`absolute bottom-0 h-3 rounded-sm transition-all ${
                    theme.instFlow >= 0
                      ? "bg-purple-500 left-1/2"
                      : "bg-purple-500/60 right-1/2"
                  }`}
                  style={{
                    width: `${(Math.abs(theme.instFlow) / maxFlow) * 45}%`,
                    ...(theme.instFlow < 0
                      ? { right: "50%" }
                      : { left: "50%" }),
                  }}
                />
              </div>
              <span
                className={`text-xs font-mono w-16 text-right ${
                  theme.change_rate > 0
                    ? "text-emerald-400"
                    : theme.change_rate < 0
                      ? "text-red-400"
                      : "text-slate-400"
                }`}
              >
                {theme.change_rate > 0 ? "+" : ""}
                {theme.change_rate.toFixed(1)}%
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-center gap-6 text-xs text-slate-500">
        <span>← 매도</span>
        <span>|</span>
        <span>매수 →</span>
      </div>
    </div>
  );
}
