"use client";

import { useMemo } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeVolumeRanking({
  themes,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  // 거래대금 시뮬레이션 (실제로는 API에서)
  const volumeData = useMemo(() => {
    return themes
      .slice(0, 8)
      .map((theme) => ({
        ...theme,
        volume: Math.floor(Math.random() * 5000 + 500), // 억 단위
        volumeChange: (Math.random() - 0.3) * 100,
      }))
      .sort((a, b) => b.volume - a.volume);
  }, [themes]);

  const maxVolume = Math.max(...volumeData.map((d) => d.volume));

  return (
    <div className="p-5 bg-slate-800/30 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>💰</span>
        테마별 거래대금
      </h3>

      <div className="space-y-2">
        {volumeData.map((theme, i) => (
          <div
            key={theme.theme_code}
            onClick={() => onThemeClick(theme.theme_code, theme.theme_name)}
            className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-700/30 cursor-pointer transition-colors"
          >
            <span className="w-5 text-center text-sm font-bold text-slate-500">
              {i + 1}
            </span>
            <span className="text-sm text-white truncate flex-1">
              {theme.theme_name}
            </span>
            <div className="w-24 h-2 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-amber-500 to-orange-500"
                style={{ width: `${(theme.volume / maxVolume) * 100}%` }}
              />
            </div>
            <div className="text-right w-20">
              <p className="text-sm font-mono text-white">
                {theme.volume.toLocaleString()}억
              </p>
              <p
                className={`text-xs ${
                  theme.volumeChange > 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {theme.volumeChange > 0 ? "+" : ""}
                {theme.volumeChange.toFixed(0)}%
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
