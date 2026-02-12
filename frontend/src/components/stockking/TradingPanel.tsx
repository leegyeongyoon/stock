"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Power,
  PowerOff,
  AlertTriangle,
  Activity,
  TrendingUp,
  TrendingDown,
  Clock,
  Shield,
} from "lucide-react";
import {
  getStockkingTradingStatus,
  startStockkingTrading,
  stopStockkingTrading,
  getStockkingPositions,
  type HongTradingStatus,
  type HongPosition,
  type HongEvent,
} from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8088";

const STATE_LABELS: Record<string, { label: string; color: string; dotColor: string }> = {
  IDLE: { label: "대기", color: "text-slate-400", dotColor: "bg-slate-400" },
  SCANNING: { label: "스캔중", color: "text-blue-400", dotColor: "bg-blue-500 animate-pulse" },
  TRADING: { label: "매매중", color: "text-green-400", dotColor: "bg-green-500 animate-pulse" },
  STOPPED: { label: "정지", color: "text-red-400", dotColor: "bg-red-500" },
  DAY_STOPPED: { label: "당일종료", color: "text-yellow-400", dotColor: "bg-yellow-500" },
};

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return timestamp;
  }
}

function formatPrice(price: number): string {
  return price.toLocaleString("ko-KR");
}

function formatPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}${pnl.toLocaleString("ko-KR")}`;
}

function formatPnlPct(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export default function TradingPanel() {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const [wsEvents, setWsEvents] = useState<HongEvent[]>([]);

  const { data: status } = useQuery({
    queryKey: ["stockking-trading-status"],
    queryFn: getStockkingTradingStatus,
    refetchInterval: 5000,
    retry: 2,
  });

  const { data: positionsData } = useQuery({
    queryKey: ["stockking-positions"],
    queryFn: getStockkingPositions,
    refetchInterval: 5000,
    retry: 2,
  });

  const startMutation = useMutation({
    mutationFn: startStockkingTrading,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stockking-trading-status"] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: stopStockkingTrading,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stockking-trading-status"] });
    },
  });

  const connectWebSocket = useCallback(() => {
    try {
      const wsUrl = API_BASE.replace(/^http/, "ws");
      const ws = new WebSocket(`${wsUrl}/ws/stockking`);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as HongEvent;
          setWsEvents((prev) => [data, ...prev].slice(0, 20));
          queryClient.invalidateQueries({ queryKey: ["stockking-trading-status"] });
          queryClient.invalidateQueries({ queryKey: ["stockking-positions"] });
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setTimeout(connectWebSocket, 5000);
      };

      wsRef.current = ws;
    } catch {
      // WebSocket not available
    }
  }, [queryClient]);

  useEffect(() => {
    connectWebSocket();
    return () => {
      wsRef.current?.close();
    };
  }, [connectWebSocket]);

  const isEnabled = status?.enabled ?? false;
  const stateInfo = STATE_LABELS[status?.state ?? "STOPPED"] ?? STATE_LABELS.STOPPED;
  const positions = Array.isArray(positionsData) ? positionsData : [];
  const isToggling = startMutation.isPending || stopMutation.isPending;

  const handleToggle = () => {
    if (isEnabled) {
      stopMutation.mutate();
    } else {
      startMutation.mutate();
    }
  };

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className={`w-2 h-2 rounded-full ${stateInfo.dotColor}`} />
          <h3 className="text-sm font-semibold text-white">홍인기 자동매매</h3>
          <span className={`text-xs font-medium ${stateInfo.color}`}>{stateInfo.label}</span>
        </div>
        <button
          onClick={handleToggle}
          disabled={isToggling}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all disabled:opacity-50 ${
            isEnabled
              ? "bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30"
              : "bg-green-500/20 text-green-400 hover:bg-green-500/30 border border-green-500/30"
          }`}
        >
          {isEnabled ? <PowerOff size={12} /> : <Power size={12} />}
          {isEnabled ? "정지" : "시작"}
        </button>
      </div>

      {/* Caution Day Warning */}
      {status?.is_caution_day && (
        <div className="flex items-center gap-2 p-2.5 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
          <AlertTriangle size={14} className="text-yellow-400 shrink-0" />
          <span className="text-xs text-yellow-400 font-medium">경계일 - 매매 사이즈 축소 적용</span>
        </div>
      )}

      {/* Risk Info Row */}
      <div className="grid grid-cols-4 gap-2">
        <div className="bg-slate-900/60 rounded-lg p-2.5 text-center">
          <div className="flex items-center justify-center gap-1 mb-1">
            <Shield size={10} className="text-slate-500" />
            <span className="text-[10px] text-slate-500">연속손실</span>
          </div>
          <span className={`text-sm font-bold ${
            (status?.consecutive_losses ?? 0) >= 2 ? "text-red-400" : "text-white"
          }`}>
            {status?.consecutive_losses ?? 0}
          </span>
          {(status?.consecutive_losses ?? 0) >= 2 && (
            <span className="block text-[9px] text-red-400 mt-0.5">경고</span>
          )}
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2.5 text-center">
          <div className="flex items-center justify-center gap-1 mb-1">
            <Activity size={10} className="text-slate-500" />
            <span className="text-[10px] text-slate-500">금일매매</span>
          </div>
          <span className="text-sm font-bold text-white">{status?.trades_today ?? 0}</span>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2.5 text-center">
          <div className="flex items-center justify-center gap-1 mb-1">
            <TrendingUp size={10} className="text-slate-500" />
            <span className="text-[10px] text-slate-500">보유</span>
          </div>
          <span className="text-sm font-bold text-white">{status?.positions_count ?? 0}</span>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2.5 text-center">
          <div className="flex items-center justify-center gap-1 mb-1">
            {(status?.day_pnl ?? 0) >= 0 ? (
              <TrendingUp size={10} className="text-green-500" />
            ) : (
              <TrendingDown size={10} className="text-red-500" />
            )}
            <span className="text-[10px] text-slate-500">당일PnL</span>
          </div>
          <span className={`text-sm font-bold ${
            (status?.day_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"
          }`}>
            {formatPnl(status?.day_pnl ?? 0)}
          </span>
        </div>
      </div>

      {/* Last Scan Time */}
      {status?.last_scan_time && (
        <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
          <Clock size={10} />
          마지막 스캔: {formatTime(status.last_scan_time)}
        </div>
      )}

      {/* Positions Table */}
      {positions.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-medium text-slate-400">보유 포지션</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-1.5 font-medium">종목</th>
                  <th className="text-right py-1.5 font-medium">수량</th>
                  <th className="text-right py-1.5 font-medium">평단</th>
                  <th className="text-right py-1.5 font-medium">현재가</th>
                  <th className="text-right py-1.5 font-medium">수익률</th>
                  <th className="text-center py-1.5 font-medium">상태</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr key={pos.stock_code} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                    <td className="py-2">
                      <div className="text-white font-medium">{pos.stock_name}</div>
                      <div className="text-[10px] text-slate-500">{pos.strategy_name}</div>
                    </td>
                    <td className="text-right text-slate-300">
                      {pos.quantity}
                      {pos.partial_sold && (
                        <span className="text-[9px] text-yellow-400 ml-1">
                          /{pos.original_quantity}
                        </span>
                      )}
                    </td>
                    <td className="text-right text-slate-300 font-mono">
                      {formatPrice(pos.avg_price)}
                    </td>
                    <td className="text-right text-slate-300 font-mono">
                      {formatPrice(pos.current_price)}
                    </td>
                    <td className={`text-right font-mono font-medium ${
                      pos.unrealized_pnl_pct >= 0 ? "text-green-400" : "text-red-400"
                    }`}>
                      {formatPnlPct(pos.unrealized_pnl_pct)}
                    </td>
                    <td className="text-center">
                      {pos.partial_sold ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">
                          반익절
                        </span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">
                          보유
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty positions state */}
      {positions.length === 0 && isEnabled && (
        <div className="text-center py-4">
          <Activity size={20} className="text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-500">보유 포지션 없음</p>
        </div>
      )}

      {/* Recent WS Events */}
      {wsEvents.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-medium text-slate-400">실시간 이벤트</h4>
          <div className="max-h-32 overflow-y-auto space-y-1">
            {wsEvents.slice(0, 5).map((evt, idx) => (
              <div
                key={`${evt.timestamp}-${idx}`}
                className={`flex items-start gap-2 text-[10px] p-1.5 rounded ${
                  evt.severity === "error"
                    ? "bg-red-500/10 text-red-400"
                    : evt.severity === "warning"
                    ? "bg-yellow-500/10 text-yellow-400"
                    : "bg-slate-900/40 text-slate-400"
                }`}
              >
                <span className="text-slate-500 shrink-0">{formatTime(evt.timestamp)}</span>
                <span>{evt.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
