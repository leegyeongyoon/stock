"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getGyleeConviction,
  type ConvictionItem,
} from "@/lib/api";
import {
  Target,
  Star,
  ChevronDown,
  ChevronUp,
  Crown,
  ShieldCheck,
  ShieldX,
  Clock,
} from "lucide-react";

const POSITION_COLORS: Record<string, string> = {
  "신고가": "text-red-400 bg-red-500/10",
  "전고점돌파": "text-orange-400 bg-orange-500/10",
  "바닥반등": "text-green-400 bg-green-500/10",
  "빈집": "text-blue-400 bg-blue-500/10",
  "해당없음": "text-slate-500 bg-slate-500/10",
};

const METHOD_COLORS: Record<string, string> = {
  "돌파매매": "text-orange-400",
  "눌림매매": "text-cyan-400",
};

function ScoreBar({ score, max = 1 }: { score: number; max?: number }) {
  const pct = Math.min((score / max) * 100, 100);
  return (
    <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full transition-all ${
          pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-yellow-500" : "bg-red-500"
        }`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function FilterBadge({ pass, label }: { pass: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded ${
      pass ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"
    }`}>
      {pass ? <ShieldCheck size={8} /> : <ShieldX size={8} />}
      {label}
    </span>
  );
}

function ConvictionRow({ item, expanded, onToggle }: {
  item: ConvictionItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  const posColor = POSITION_COLORS[item.daily_position] ?? POSITION_COLORS["해당없음"];
  const methodColor = METHOD_COLORS[item.method] ?? "text-slate-400";

  // 경윤 필터 상태 (API에서 제공되면 사용, 없으면 표시 안 함)
  const filters = (item as unknown as Record<string, unknown>).filter_status as {
    cap: boolean; inst: boolean; time: boolean;
  } | undefined;

  return (
    <div className={`rounded-lg border transition-all ${
      item.is_top
        ? "border-purple-500/30 bg-purple-500/5"
        : item.is_buyable
          ? "border-slate-700 bg-slate-900/40"
          : "border-slate-800 bg-slate-900/20 opacity-60"
    }`}>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-3 text-left hover:bg-slate-800/30 transition-colors"
      >
        {/* Rank */}
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
          item.is_top
            ? "bg-purple-500/20 text-purple-400 border border-purple-500/30"
            : "bg-slate-800 text-slate-500"
        }`}>
          {item.rank}
        </div>

        {/* Stock name + badges */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium text-white truncate">
              {item.stock_name}
            </span>
            {item.is_leader && (
              <Star size={10} className="text-yellow-400 shrink-0" fill="currentColor" />
            )}
            {item.is_top && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-purple-500/20 text-purple-400 font-medium shrink-0">
                TOP {item.rank}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${posColor}`}>
              {item.daily_position}
            </span>
            <span className={`text-[10px] ${methodColor}`}>
              {item.method}
            </span>
          </div>
        </div>

        {/* Score */}
        <div className="text-right shrink-0 w-20">
          <div className="text-sm font-bold text-white">{item.score.toFixed(3)}</div>
          <div className="mt-0.5">
            <ScoreBar score={item.score} />
          </div>
        </div>

        {/* Alloc */}
        <div className={`shrink-0 text-right w-12 ${
          item.alloc_label === "확신" ? "text-green-400" : "text-slate-400"
        }`}>
          <div className="text-xs font-bold">{Math.round(item.alloc_pct * 100)}%</div>
          <div className="text-[9px]">{item.alloc_label}</div>
        </div>

        {/* Expand */}
        <div className="shrink-0 text-slate-500">
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-3 pb-3 pt-0 border-t border-slate-700/50">
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-2 text-xs">
            <div>
              <span className="text-slate-500">확신도</span>
              <span className="text-white ml-2 font-mono">{item.confidence.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-slate-500">끼 점수</span>
              <span className="text-white ml-2 font-mono">{item.ki_score.toFixed(1)}</span>
            </div>
            <div>
              <span className="text-slate-500">대장주 보너스</span>
              <span className={`ml-2 font-mono ${item.is_leader ? "text-yellow-400" : "text-slate-500"}`}>
                x{item.leader_bonus.toFixed(1)}
              </span>
            </div>
            <div>
              <span className="text-slate-500">계산</span>
              <span className="text-slate-300 ml-2 font-mono text-[10px]">
                {item.confidence.toFixed(2)} x {(item.ki_score / 100).toFixed(2)} x {item.leader_bonus.toFixed(1)} = {item.score.toFixed(3)}
              </span>
            </div>
          </div>

          {/* 경윤 3대 필터 상태 */}
          {filters && (
            <div className="mt-2 flex gap-1.5 flex-wrap">
              <FilterBadge pass={filters.cap} label="시총5000억+" />
              <FilterBadge pass={filters.inst} label="기관50~200억" />
              <FilterBadge pass={filters.time} label="시간대" />
            </div>
          )}

          {/* Reason */}
          <div className="mt-2 text-[11px] text-slate-400 bg-slate-800/50 rounded-md p-2">
            {item.reason}
          </div>
          {/* Patterns */}
          {item.patterns.length > 0 && (
            <div className="mt-1.5 flex gap-1 flex-wrap">
              {item.patterns.map((p) => (
                <span key={p} className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400">
                  {p}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function GyleeConvictionPanel() {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["gylee-conviction"],
    queryFn: getGyleeConviction,
    refetchInterval: 30000,
    retry: 2,
  });

  const ranking = data?.ranking ?? [];
  const topN = data?.top_n ?? 5;
  const maxPos = data?.max_positions ?? 2;
  const highAlloc = data?.high_alloc_pct ?? 0.5;
  const lowAlloc = data?.low_alloc_pct ?? 0.3;

  const buyableCount = ranking.filter((r) => r.is_buyable).length;
  const topCount = ranking.filter((r) => r.is_top).length;

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Crown size={14} className="text-purple-400" />
          경윤 확신도 순위
        </h3>
        <div className="flex items-center gap-2 text-[10px]">
          <span className="text-slate-500">
            분석 {ranking.length}종목
          </span>
          {buyableCount > 0 && (
            <span className="text-purple-400 font-medium">
              매수가능 {buyableCount} / TOP{topN} {topCount}종목
            </span>
          )}
        </div>
      </div>

      {/* Config summary */}
      <div className="grid grid-cols-4 gap-2">
        <div className="bg-slate-900/60 rounded-lg p-2 text-center">
          <div className="text-[9px] text-slate-500">최대 보유</div>
          <div className="text-xs font-bold text-white">{maxPos}종목</div>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2 text-center">
          <div className="text-[9px] text-slate-500">확신 배분</div>
          <div className="text-xs font-bold text-green-400">{Math.round(highAlloc * 100)}%</div>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2 text-center">
          <div className="text-[9px] text-slate-500">보통 배분</div>
          <div className="text-xs font-bold text-slate-300">{Math.round(lowAlloc * 100)}%</div>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2 text-center">
          <div className="text-[9px] text-slate-500">진입 대상</div>
          <div className="text-xs font-bold text-purple-400">TOP {topN}</div>
        </div>
      </div>

      {/* 필터 파이프라인 요약 */}
      <div className="flex items-center gap-1.5 text-[10px] text-slate-500 overflow-x-auto">
        <Clock size={10} className="shrink-0" />
        <span>홍인기분석</span>
        <span className="text-slate-600">→</span>
        <span className="text-purple-400">시총</span>
        <span className="text-slate-600">→</span>
        <span className="text-purple-400">기관</span>
        <span className="text-slate-600">→</span>
        <span className="text-purple-400">눌림</span>
        <span className="text-slate-600">→</span>
        <span className="text-purple-400">시간대</span>
        <span className="text-slate-600">→</span>
        <span>확신도순위</span>
        <span className="text-slate-600">→</span>
        <span className="text-yellow-400">TOP{topN} 매수</span>
      </div>

      {/* Loading */}
      {isLoading && ranking.length === 0 && (
        <div className="space-y-2">
          <div className="animate-pulse h-14 bg-slate-700/50 rounded-lg" />
          <div className="animate-pulse h-14 bg-slate-700/50 rounded-lg" />
        </div>
      )}

      {/* Empty */}
      {!isLoading && ranking.length === 0 && (
        <div className="text-center py-6">
          <Target size={20} className="text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-500">매매를 시작하면 확신도 순위가 표시됩니다</p>
          <p className="text-[10px] text-slate-600 mt-1">3분 간격 스캔 시 업데이트</p>
        </div>
      )}

      {/* Ranking list */}
      {ranking.length > 0 && (
        <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
          {ranking.map((item, idx) => (
            <ConvictionRow
              key={item.stock_code}
              item={item}
              expanded={expandedIdx === idx}
              onToggle={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
