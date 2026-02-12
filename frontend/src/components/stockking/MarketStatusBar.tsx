import { Clock, AlertTriangle, Activity } from "lucide-react";
import type { MarketCondition } from "@/lib/api";

const CONDITION_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  "유동성장세": { bg: "bg-emerald-500/20", text: "text-emerald-400", border: "border-emerald-500/30" },
  "강세": { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
  "보통": { bg: "bg-slate-500/20", text: "text-slate-400", border: "border-slate-500/30" },
  "약세": { bg: "bg-orange-500/20", text: "text-orange-400", border: "border-orange-500/30" },
  "매매자제": { bg: "bg-red-500/20", text: "text-red-400", border: "border-red-500/30" },
};

function getTimePhaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    pre_market: "장 시작 전",
    morning_opening: "장초반 (9:00-9:30)",
    golden_time: "골든타임 (9:30-11:00)",
    midday: "점심 시간대 (11:00-13:00)",
    afternoon: "오후 시간대 (13:00-14:30)",
    closing: "장마감 (14:30-15:30)",
    after_market: "장 종료",
  };
  return labels[phase] || phase;
}

export default function MarketStatusBar({ condition }: { condition: MarketCondition | undefined }) {
  if (!condition) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <div className="flex items-center gap-2 text-slate-500">
          <Clock size={16} />
          <span className="text-sm">시장 데이터를 불러오는 중...</span>
        </div>
      </div>
    );
  }

  const style = CONDITION_STYLES[condition.condition] || CONDITION_STYLES["보통"];

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-6">
        {/* Time phase */}
        <div className="flex items-center gap-2">
          <Clock size={16} className="text-slate-400" />
          <span className="text-sm text-white font-medium">
            {getTimePhaseLabel(condition.phase)}
          </span>
        </div>

        {/* Market condition */}
        <div className={`flex items-center gap-2 px-3 py-1 rounded-full ${style.bg} border ${style.border}`}>
          <Activity size={14} className={style.text} />
          <span className={`text-sm font-medium ${style.text}`}>{condition.condition}</span>
        </div>

        {/* Sector concentration */}
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">섹터 집중도</span>
          <span className="text-white font-mono">
            {(condition.sector_concentration * 100).toFixed(0)}%
          </span>
        </div>

        {/* Caution warning */}
        {condition.is_caution_day && (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-red-500/20 border border-red-500/30 ml-auto">
            <AlertTriangle size={14} className="text-red-400" />
            <span className="text-sm text-red-400 font-medium">
              {condition.caution_reason || "매매 자제일"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
