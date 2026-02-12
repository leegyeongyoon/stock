"use client";

import { useState, useEffect } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemeAlertBanner({
  themes,
}: {
  themes?: ThemeRanking[];
}) {
  const [alerts, setAlerts] = useState<
    { theme: string; change: number; type: "surge" | "drop" }[]
  >([]);
  const [currentAlert, setCurrentAlert] = useState(0);

  useEffect(() => {
    if (!themes) return;

    // 급등/급락 테마 필터링 (3% 이상)
    const newAlerts = themes
      .filter((t) => Math.abs(t.change_rate) >= 3)
      .map((t) => ({
        theme: t.theme_name,
        change: t.change_rate,
        type: (t.change_rate > 0 ? "surge" : "drop") as "surge" | "drop",
      }))
      .slice(0, 5);

    setAlerts(newAlerts);
  }, [themes]);

  useEffect(() => {
    if (alerts.length === 0) return;
    const timer = setInterval(() => {
      setCurrentAlert((prev) => (prev + 1) % alerts.length);
    }, 4000);
    return () => clearInterval(timer);
  }, [alerts.length]);

  if (alerts.length === 0) return null;

  const alert = alerts[currentAlert];

  return (
    <div
      className={`px-4 py-2 rounded-lg flex items-center justify-between ${
        alert.type === "surge"
          ? "bg-gradient-to-r from-emerald-900/50 to-emerald-800/30 border border-emerald-500/30"
          : "bg-gradient-to-r from-red-900/50 to-red-800/30 border border-red-500/30"
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="text-lg">
          {alert.type === "surge" ? "🚀" : "📉"}
        </span>
        <div>
          <span className="text-sm font-medium text-white">
            {alert.theme}
          </span>
          <span
            className={`ml-2 text-sm font-bold ${
              alert.type === "surge" ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {alert.change > 0 ? "+" : ""}
            {alert.change.toFixed(2)}%
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {alerts.map((_, i) => (
          <div
            key={i}
            className={`w-1.5 h-1.5 rounded-full transition-all ${
              i === currentAlert ? "bg-white" : "bg-white/30"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
