"use client";

import { useQuery } from "@tanstack/react-query";
import { getPnLByStrategy, getPnLByDayOfWeek, getPnLAnalysis } from "@/lib/api";
import StrategyPnLChart from "@/components/performance/StrategyPnLChart";
import DayOfWeekChart from "@/components/performance/DayOfWeekChart";
import PnLAnalysis from "@/components/performance/PnLAnalysis";

export default function PerformancePage() {
  const { data: byStrategy } = useQuery({
    queryKey: ["pnl-by-strategy"],
    queryFn: getPnLByStrategy,
    refetchInterval: 10_000,
  });

  const { data: byDay } = useQuery({
    queryKey: ["pnl-by-day"],
    queryFn: getPnLByDayOfWeek,
    refetchInterval: 10_000,
  });

  const { data: analysis } = useQuery({
    queryKey: ["pnl-analysis"],
    queryFn: getPnLAnalysis,
    refetchInterval: 10_000,
  });

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-bold">수익률 현황</h2>

      <PnLAnalysis analysis={analysis} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <StrategyPnLChart strategies={byStrategy?.strategies || []} />
        <DayOfWeekChart days={byDay?.days || []} />
      </div>
    </div>
  );
}
