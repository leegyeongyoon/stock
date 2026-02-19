"use client";

import { useQuery, useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { getDashboardSummary, getStrategyDetail, toggleStrategy } from "@/lib/api";
import StrategyDetailCard from "@/components/strategies/StrategyDetailCard";

export default function StrategiesPage() {
  const queryClient = useQueryClient();

  const { data: dashboard } = useQuery({
    queryKey: ["dashboard"],
    queryFn: getDashboardSummary,
    refetchInterval: 30_000,
  });

  const strategyNames = (dashboard?.strategies ?? []).map((s) => s.name).filter(Boolean);

  const results = useQueries({
    queries: strategyNames.map((name) => ({
      queryKey: ["strategy-detail", name],
      queryFn: () => getStrategyDetail(name),
      refetchInterval: 15_000,
      enabled: !!name,
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
      {strategyNames.length === 0 ? (
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center text-slate-500">
          전략 로딩 중...
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {strategyNames.map((name, i) => (
            <StrategyDetailCard
              key={name}
              name={name}
              detail={results[i]?.data}
              onToggle={(n) => mutation.mutate(n)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
