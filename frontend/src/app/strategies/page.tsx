"use client";

import { useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { getStrategyDetail, toggleStrategy } from "@/lib/api";
import StrategyDetailCard from "@/components/strategies/StrategyDetailCard";

const STRATEGY_NAMES = [
  "modified_rsi_neutral_atr",
  "morning_rsi_neutral_atr",
];

export default function StrategiesPage() {
  const queryClient = useQueryClient();

  const results = useQueries({
    queries: STRATEGY_NAMES.map((name) => ({
      queryKey: ["strategy-detail", name],
      queryFn: () => getStrategyDetail(name),
      refetchInterval: 15_000,
    })),
  });

  const mutation = useMutation({
    mutationFn: toggleStrategy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-detail"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">전략별 모니터링</h2>
        <p className="text-xs text-slate-500">15초마다 자동 갱신</p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {STRATEGY_NAMES.map((name, i) => (
          <StrategyDetailCard
            key={name}
            name={name}
            detail={results[i]?.data}
            onToggle={(n) => mutation.mutate(n)}
          />
        ))}
      </div>
    </div>
  );
}
