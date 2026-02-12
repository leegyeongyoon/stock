"use client";

import { useState } from "react";
import { BookOpen, ChevronDown, ChevronUp, CheckCircle2, Circle, AlertTriangle } from "lucide-react";
import type { TradingRule } from "@/lib/api";

const IMPORTANCE_STYLES: Record<string, { dot: string; text: string }> = {
  critical: { dot: "text-red-400", text: "text-red-400" },
  high: { dot: "text-orange-400", text: "text-orange-400" },
  medium: { dot: "text-slate-400", text: "text-slate-400" },
};

function groupByCategory(rules: TradingRule[]): Record<string, TradingRule[]> {
  const groups: Record<string, TradingRule[]> = {};
  for (const rule of rules) {
    const category = rule.category || "기타";
    if (!groups[category]) groups[category] = [];
    groups[category] = [...groups[category], rule];
  }
  return groups;
}

export default function TradingRules({
  rules,
  checkedCount,
  totalCount,
}: {
  rules: TradingRule[] | undefined;
  checkedCount?: number;
  totalCount?: number;
}) {
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(["3대 원칙"]));

  if (!rules || rules.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <BookOpen size={16} className="text-blue-400" />
          홍인기 매매 원칙
        </h3>
        <p className="text-sm text-slate-500">매매 원칙 데이터가 없습니다.</p>
      </div>
    );
  }

  const grouped = groupByCategory(rules);

  const toggleCategory = (category: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <BookOpen size={16} className="text-blue-400" />
          홍인기 매매 원칙
        </h3>
        {totalCount !== undefined && checkedCount !== undefined && (
          <span className="text-xs text-slate-400">
            {checkedCount}/{totalCount} 확인
          </span>
        )}
      </div>

      <div className="space-y-2">
        {Object.entries(grouped).map(([category, categoryRules]) => {
          const isExpanded = expandedCategories.has(category);
          const hasCritical = categoryRules.some((r) => r.importance === "critical");

          return (
            <div key={category} className="rounded-lg border border-slate-700 overflow-hidden">
              <button
                onClick={() => toggleCategory(category)}
                className="w-full flex items-center justify-between px-3 py-2.5 bg-slate-700/30 hover:bg-slate-700/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  {hasCritical && <AlertTriangle size={12} className="text-red-400" />}
                  <span className="text-sm font-medium text-white">{category}</span>
                  <span className="text-[10px] text-slate-500">({categoryRules.length})</span>
                </div>
                {isExpanded ? (
                  <ChevronUp size={14} className="text-slate-400" />
                ) : (
                  <ChevronDown size={14} className="text-slate-400" />
                )}
              </button>

              {isExpanded && (
                <div className="px-3 py-2 space-y-1.5">
                  {categoryRules.map((rule) => {
                    const style = IMPORTANCE_STYLES[rule.importance] || IMPORTANCE_STYLES.medium;

                    return (
                      <div
                        key={rule.id}
                        className="flex items-start gap-2 py-1"
                      >
                        {rule.is_checked ? (
                          <CheckCircle2 size={14} className="text-emerald-400 flex-shrink-0 mt-0.5" />
                        ) : (
                          <Circle size={14} className={`${style.dot} flex-shrink-0 mt-0.5`} />
                        )}
                        <span className={`text-xs ${rule.is_checked ? "text-slate-500 line-through" : style.text}`}>
                          {rule.rule}
                        </span>
                        {rule.importance === "critical" && !rule.is_checked && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-red-500/20 text-red-400 flex-shrink-0">
                            필수
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
