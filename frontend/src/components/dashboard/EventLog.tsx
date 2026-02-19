"use client";

import type { SystemEvent } from "@/lib/api";

interface Props {
  events: SystemEvent[];
}

const severityColor: Record<string, string> = {
  INFO: "text-blue-400",
  WARNING: "text-yellow-400",
  ERROR: "text-red-400",
  CRITICAL: "text-red-500 font-bold",
};

const typeIcon: Record<string, string> = {
  INIT: "SYS",
  ENGINE_STARTED: "ON",
  ENGINE_STOPPED: "OFF",
  EMERGENCY_STOP: "SOS",
  START_FAILED: "ERR",
  MARKET_CLOSE: "END",
  SIGNAL: "SIG",
  ORDER: "ORD",
  TRADE: "TRD",
};

export default function EventLog({ events }: Props) {
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700">
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <h3 className="font-semibold">이벤트 로그</h3>
        <span className="text-xs text-slate-500">{events.length}건</span>
      </div>
      <div className="max-h-64 overflow-y-auto">
        {events.length === 0 ? (
          <div className="p-4 text-center text-sm text-slate-500">
            이벤트 없음
          </div>
        ) : (
          <div className="divide-y divide-slate-700/30">
            {events.map((evt, i) => {
              const color = severityColor[evt.severity] || "text-slate-400";
              const icon =
                typeIcon[evt.event_type] || evt.event_type.slice(0, 3).toUpperCase();
              const time = new Date(evt.timestamp).toLocaleTimeString("ko-KR", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              });

              return (
                <div
                  key={`${evt.timestamp}-${evt.event_type}-${i}`}
                  className="px-4 py-2 flex items-start gap-3 text-xs hover:bg-slate-700/20"
                >
                  <span className="text-slate-600 font-mono shrink-0 w-16">
                    {time}
                  </span>
                  <span
                    className={`font-mono shrink-0 w-8 text-center rounded px-1 ${
                      evt.severity === "ERROR" || evt.severity === "CRITICAL"
                        ? "bg-red-500/20 text-red-400"
                        : evt.severity === "WARNING"
                        ? "bg-yellow-500/20 text-yellow-400"
                        : "bg-blue-500/10 text-blue-400"
                    }`}
                  >
                    {icon}
                  </span>
                  <span className={color}>{evt.message}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
