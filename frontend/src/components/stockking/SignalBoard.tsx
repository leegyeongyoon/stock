import { ArrowUpCircle, ArrowDownCircle, Zap, Clock } from "lucide-react";
import type { TradingSignal } from "@/lib/api";

const METHOD_STYLES: Record<string, { bg: string; text: string; icon: typeof Zap }> = {
  "돌파": { bg: "bg-blue-500/20", text: "text-blue-400", icon: Zap },
  "눌림": { bg: "bg-orange-500/20", text: "text-orange-400", icon: ArrowDownCircle },
  "손절": { bg: "bg-red-500/20", text: "text-red-400", icon: ArrowDownCircle },
  "익절": { bg: "bg-emerald-500/20", text: "text-emerald-400", icon: ArrowUpCircle },
  "본전컷": { bg: "bg-slate-500/20", text: "text-slate-400", icon: ArrowDownCircle },
};

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return timestamp;
  }
}

export default function SignalBoard({ signals }: { signals: TradingSignal[] | undefined }) {
  if (!signals || signals.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Zap size={16} className="text-yellow-400" />
          매매 시그널
        </h3>
        <p className="text-sm text-slate-500">현재 활성 시그널이 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
        <Zap size={16} className="text-yellow-400" />
        매매 시그널
        <span className="text-xs text-slate-500 font-normal ml-1">({signals.length}건)</span>
      </h3>

      <div className="space-y-2 max-h-80 overflow-y-auto">
        {signals.map((signal, idx) => {
          const isEntry = signal.signal_type === "entry";
          const methodStyle = METHOD_STYLES[signal.method] || METHOD_STYLES["돌파"];
          const MethodIcon = methodStyle.icon;

          return (
            <div
              key={`${signal.stock_code}-${signal.timestamp}-${idx}`}
              className={`rounded-lg border p-3 ${
                isEntry
                  ? "bg-emerald-500/5 border-emerald-500/20"
                  : "bg-red-500/5 border-red-500/20"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                    isEntry
                      ? "bg-emerald-500/20 text-emerald-400"
                      : "bg-red-500/20 text-red-400"
                  }`}>
                    {isEntry ? "진입" : "청산"}
                  </span>
                  <span className="text-white font-medium text-sm">{signal.stock_name}</span>
                </div>
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <Clock size={10} />
                  {formatTime(signal.timestamp)}
                </div>
              </div>

              <div className="flex items-center gap-2 mb-2">
                <span className={`text-xs px-2 py-0.5 rounded flex items-center gap-1 ${methodStyle.bg} ${methodStyle.text}`}>
                  <MethodIcon size={10} />
                  {signal.method}
                </span>
                {/* Confidence gauge */}
                <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      signal.confidence >= 0.7
                        ? "bg-emerald-500"
                        : signal.confidence >= 0.4
                        ? "bg-yellow-500"
                        : "bg-red-500"
                    }`}
                    style={{ width: `${signal.confidence * 100}%` }}
                  />
                </div>
                <span className="text-xs text-slate-400 font-mono">
                  {(signal.confidence * 100).toFixed(0)}%
                </span>
              </div>

              <p className="text-xs text-slate-400">{signal.reason}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
