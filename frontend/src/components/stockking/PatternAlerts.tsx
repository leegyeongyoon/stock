import { ShieldAlert, Clock } from "lucide-react";
import type { PatternAlert } from "@/lib/api";

const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  high: { bg: "bg-red-500/10", text: "text-red-400", border: "border-red-500/20" },
  medium: { bg: "bg-orange-500/10", text: "text-orange-400", border: "border-orange-500/20" },
  low: { bg: "bg-yellow-500/10", text: "text-yellow-400", border: "border-yellow-500/20" },
};

const SEVERITY_LABELS: Record<string, string> = {
  high: "높음",
  medium: "보통",
  low: "낮음",
};

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return timestamp;
  }
}

export default function PatternAlerts({ alerts }: { alerts: PatternAlert[] | undefined }) {
  if (!alerts || alerts.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <ShieldAlert size={16} className="text-orange-400" />
          위험 패턴 알림
        </h3>
        <p className="text-sm text-slate-500">감지된 위험 패턴이 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
        <ShieldAlert size={16} className="text-orange-400" />
        위험 패턴 알림
        <span className="text-xs text-slate-500 font-normal ml-1">({alerts.length}건)</span>
      </h3>

      <div className="space-y-2 max-h-60 overflow-y-auto">
        {alerts.map((alert, idx) => {
          const style = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.low;

          return (
            <div
              key={`${alert.stock_code}-${alert.pattern_name}-${idx}`}
              className={`rounded-lg border p-3 ${style.bg} ${style.border}`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${style.bg} ${style.text} border ${style.border}`}>
                    {alert.pattern_name}
                  </span>
                  <span className="text-white text-sm font-medium">{alert.stock_name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] ${style.text}`}>
                    {SEVERITY_LABELS[alert.severity] || alert.severity}
                  </span>
                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <Clock size={10} />
                    {formatTime(alert.detected_at)}
                  </div>
                </div>
              </div>
              <p className="text-xs text-slate-400">{alert.description}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
