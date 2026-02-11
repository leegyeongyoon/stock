"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getDashboardSummary,
  startEngine,
  stopEngine,
  emergencyStop,
} from "@/lib/api";

export default function Header() {
  const queryClient = useQueryClient();
  const [clock, setClock] = useState("");

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString("ko-KR"));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const { data: summary } = useQuery({
    queryKey: ["dashboard"],
    queryFn: getDashboardSummary,
    refetchInterval: 5000,
  });

  const startMutation = useMutation({
    mutationFn: startEngine,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: stopEngine,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
    },
  });

  const emergencyMutation = useMutation({
    mutationFn: emergencyStop,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
    },
  });

  const isRunning = summary?.state === "RUNNING";
  const state = summary?.state || "IDLE";

  const stateStyles: Record<string, string> = {
    RUNNING: "bg-green-500/20 text-green-400",
    IDLE: "bg-slate-700 text-slate-400",
    ERROR: "bg-red-500/20 text-red-400",
    STARTING: "bg-yellow-500/20 text-yellow-400",
    STOPPING: "bg-yellow-500/20 text-yellow-400",
    STOPPED: "bg-slate-700 text-slate-500",
  };

  const portfolio = {
    total_equity: 0,
    cash: 0,
    daily_pnl: 0,
    ...summary?.portfolio,
  };

  return (
    <header className="bg-slate-900/80 backdrop-blur border-b border-slate-700 px-6 py-2.5 sticky top-0 z-50">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold tracking-tight">Auto-Trading</h1>
          <span
            className={`px-2 py-0.5 rounded text-xs font-medium ${
              stateStyles[state] || stateStyles.IDLE
            }`}
          >
            {state}
          </span>
          {summary?.state === "RUNNING" && (
            <span className="text-xs text-slate-500">
              자산{" "}
              <span className="text-white font-mono">
                {portfolio.total_equity.toLocaleString()}원
              </span>
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500 font-mono">
            {clock}
          </span>

          {!isRunning ? (
            <button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium transition-colors disabled:opacity-50"
            >
              {startMutation.isPending ? "연결 중..." : "매매 시작"}
            </button>
          ) : (
            <>
              <button
                onClick={() => stopMutation.mutate()}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-sm font-medium transition-colors"
              >
                중지
              </button>
              <button
                onClick={() => {
                  if (
                    confirm(
                      "긴급 정지: 모든 포지션을 즉시 청산합니다. 계속하시겠습니까?"
                    )
                  ) {
                    emergencyMutation.mutate();
                  }
                }}
                className="px-3 py-1.5 bg-red-600 hover:bg-red-500 rounded text-sm font-medium transition-colors"
              >
                긴급 정지
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
