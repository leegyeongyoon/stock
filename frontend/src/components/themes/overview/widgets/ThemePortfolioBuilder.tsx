"use client";

import { useMemo, useState } from "react";
import type { ThemeRanking } from "@/lib/api";

export default function ThemePortfolioBuilder({
  themes,
  onThemeClick,
}: {
  themes: ThemeRanking[];
  onThemeClick: (code: string, name: string) => void;
}) {
  const [portfolio, setPortfolio] = useState<
    { code: string; name: string; weight: number }[]
  >([]);
  const [totalInvestment, setTotalInvestment] = useState(10000000);

  const addToPortfolio = (theme: ThemeRanking) => {
    if (portfolio.length >= 5) return;
    if (portfolio.find((p) => p.code === theme.theme_code)) return;

    const newWeight = Math.floor(100 / (portfolio.length + 1));
    const updated = portfolio.map((p) => ({ ...p, weight: newWeight }));
    updated.push({
      code: theme.theme_code,
      name: theme.theme_name,
      weight: newWeight,
    });
    setPortfolio(updated);
  };

  const removeFromPortfolio = (code: string) => {
    const filtered = portfolio.filter((p) => p.code !== code);
    if (filtered.length > 0) {
      const newWeight = Math.floor(100 / filtered.length);
      setPortfolio(filtered.map((p) => ({ ...p, weight: newWeight })));
    } else {
      setPortfolio([]);
    }
  };

  const updateWeight = (code: string, weight: number) => {
    setPortfolio(
      portfolio.map((p) =>
        p.code === code
          ? { ...p, weight: Math.min(100, Math.max(0, weight)) }
          : p
      )
    );
  };

  const totalWeight = portfolio.reduce((sum, p) => sum + p.weight, 0);

  const expectedReturn = useMemo(() => {
    let totalReturn = 0;
    portfolio.forEach((p) => {
      const theme = themes.find((t) => t.theme_code === p.code);
      if (theme) {
        totalReturn += (theme.change_rate * p.weight) / 100;
      }
    });
    return totalReturn;
  }, [portfolio, themes]);

  return (
    <div className="p-5 bg-gradient-to-br from-slate-800/50 to-slate-900/50 rounded-2xl border border-slate-700/50">
      <h3 className="font-bold text-white flex items-center gap-2 mb-4">
        <span>📦</span>
        테마 포트폴리오 빌더
        <span className="text-xs text-slate-500 ml-auto">
          {portfolio.length}/5
        </span>
      </h3>

      {/* 투자금액 */}
      <div className="mb-4">
        <label className="text-xs text-slate-500 block mb-1">
          총 투자금액
        </label>
        <input
          type="number"
          value={totalInvestment}
          onChange={(e) => setTotalInvestment(Number(e.target.value))}
          className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm"
          step={1000000}
        />
      </div>

      {/* 포트폴리오 목록 */}
      {portfolio.length > 0 ? (
        <div className="space-y-2 mb-4">
          {portfolio.map((p) => {
            return (
              <div
                key={p.code}
                className="flex items-center gap-2 p-2 bg-slate-800/50 rounded-lg"
              >
                <span className="text-sm text-white flex-1 truncate">
                  {p.name}
                </span>
                <input
                  type="number"
                  value={p.weight}
                  onChange={(e) =>
                    updateWeight(p.code, Number(e.target.value))
                  }
                  className="w-16 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-white text-sm text-center"
                />
                <span className="text-xs text-slate-500">%</span>
                <span className="text-xs text-slate-400 w-20 text-right">
                  {((totalInvestment * p.weight) / 100).toLocaleString()}원
                </span>
                <button
                  onClick={() => removeFromPortfolio(p.code)}
                  className="text-red-400 hover:text-red-300"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-slate-500 text-center py-4 mb-4">
          아래 테마를 클릭하여 포트폴리오에 추가하세요
        </p>
      )}

      {/* 요약 */}
      {portfolio.length > 0 && (
        <div className="p-3 bg-slate-900/50 rounded-lg mb-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">총 비중</span>
            <span
              className={
                totalWeight === 100 ? "text-emerald-400" : "text-amber-400"
              }
            >
              {totalWeight}%
            </span>
          </div>
          <div className="flex items-center justify-between text-sm mt-1">
            <span className="text-slate-400">예상 수익률</span>
            <span
              className={
                expectedReturn > 0 ? "text-emerald-400" : "text-red-400"
              }
            >
              {expectedReturn > 0 ? "+" : ""}
              {expectedReturn.toFixed(2)}%
            </span>
          </div>
          <div className="flex items-center justify-between text-sm mt-1">
            <span className="text-slate-400">예상 수익금</span>
            <span
              className={
                expectedReturn > 0 ? "text-emerald-400" : "text-red-400"
              }
            >
              {((totalInvestment * expectedReturn) / 100).toLocaleString()}원
            </span>
          </div>
        </div>
      )}

      {/* 추가 가능한 테마 */}
      <div className="flex flex-wrap gap-1">
        {themes.slice(0, 8).map((theme) => (
          <button
            key={theme.theme_code}
            onClick={() => addToPortfolio(theme)}
            disabled={
              portfolio.length >= 5 ||
              portfolio.find((p) => p.code === theme.theme_code) !== undefined
            }
            className={`px-2 py-1 rounded text-xs transition-colors ${
              portfolio.find((p) => p.code === theme.theme_code)
                ? "bg-blue-500/20 text-blue-400"
                : "bg-slate-700 text-slate-400 hover:bg-slate-600 disabled:opacity-50"
            }`}
          >
            {theme.theme_name}
          </button>
        ))}
      </div>
    </div>
  );
}
