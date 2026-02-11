"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getDashboardSummary,
  getPnL,
  getPositions,
  getEvents,
  getHoldings,
} from "@/lib/api";
import { useWebSocket } from "@/hooks/useWebSocket";
import SummaryCards from "@/components/dashboard/SummaryCards";
import PnLChart from "@/components/dashboard/PnLChart";
import PositionTable from "@/components/dashboard/PositionTable";
import ActiveTriggers from "@/components/dashboard/ActiveTriggers";
import EventLog from "@/components/dashboard/EventLog";
import HoldingsPanel from "@/components/dashboard/HoldingsPanel";

export default function DashboardPage() {
  const { data: summary } = useQuery({
    queryKey: ["dashboard"],
    queryFn: getDashboardSummary,
    refetchInterval: 5000,
  });

  const { data: pnl } = useQuery({
    queryKey: ["pnl"],
    queryFn: getPnL,
  });

  const { data: positionsData } = useQuery({
    queryKey: ["positions"],
    queryFn: getPositions,
    refetchInterval: 5000,
  });

  const { data: holdingsData } = useQuery({
    queryKey: ["holdings"],
    queryFn: getHoldings,
    refetchInterval: 5000,
  });

  const { data: eventsData } = useQuery({
    queryKey: ["events"],
    queryFn: () => getEvents(50),
    refetchInterval: 3000,
  });

  const { data: wsSignal } = useWebSocket<{
    stock_code: string;
    strategy_name: string;
    reason: string;
  }>("signals");

  const isError = summary?.state === "ERROR";

  return (
    <div className="space-y-6">
      {/* Error banner */}
      {isError && (
        <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-3 text-sm text-red-400">
          엔진 오류 상태입니다. KIS API 키를 .env에 설정한 후 "매매 시작"을
          눌러주세요.
        </div>
      )}

      {/* Summary Cards */}
      <SummaryCards data={summary} />

      {/* Holdings */}
      <HoldingsPanel
        holdings={holdingsData?.holdings || []}
        summary={holdingsData?.summary}
      />

      {/* Chart + Strategies row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <PnLChart trades={pnl?.trades || []} />
        </div>
        <div>
          <ActiveTriggers strategies={summary?.strategies || []} />
        </div>
      </div>

      {/* Positions */}
      <PositionTable positions={positionsData?.positions || []} />

      {/* Bottom row: Events + Signal feed */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <EventLog events={eventsData?.events || []} />

        <div className="bg-slate-800 rounded-lg border border-slate-700">
          <div className="px-4 py-3 border-b border-slate-700">
            <h3 className="font-semibold">실시간 시그널</h3>
          </div>
          <div className="p-4">
            {wsSignal ? (
              <div className="text-sm">
                <span className="text-blue-400 font-mono">
                  {wsSignal.stock_code}
                </span>{" "}
                <span className="text-slate-400">{wsSignal.strategy_name}</span>
                <p className="text-xs text-slate-500 mt-1">
                  {wsSignal.reason}
                </p>
              </div>
            ) : (
              <p className="text-sm text-slate-500">
                매매 시작 후 전략 시그널이 여기에 표시됩니다
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Circuit breaker warning */}
      {summary?.risk?.circuit_breaker && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4">
          <p className="text-red-400 font-semibold">
            서킷브레이커 발동 - 매매가 중단되었습니다
          </p>
          <p className="text-sm text-red-300 mt-1">
            일일 손실 한도를 초과하여 자동으로 매매가 중단되었습니다.
          </p>
        </div>
      )}
    </div>
  );
}
