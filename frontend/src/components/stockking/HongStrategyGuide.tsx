"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getStockkingStrategyGuide,
  type HongStrategySection,
  type HongStrategyRule,
} from "@/lib/api";
import {
  ChevronDown,
  ChevronUp,
  Target,
  Zap,
  Clock,
  Shield,
  EyeOff,
  BarChart3,
  Brain,
  BookOpen,
} from "lucide-react";

const SECTION_ICONS: Record<string, typeof Target> = {
  target: Target,
  zap: Zap,
  clock: Clock,
  shield: Shield,
  "eye-off": EyeOff,
  "bar-chart": BarChart3,
  brain: Brain,
};

const SECTION_COLORS: Record<string, string> = {
  stock_selection: "from-blue-500 to-cyan-500",
  trading_methods: "from-orange-500 to-yellow-500",
  time_strategy: "from-purple-500 to-pink-500",
  risk_management: "from-red-500 to-rose-500",
  minute_patterns: "from-amber-500 to-orange-500",
  market_judgment: "from-green-500 to-emerald-500",
  psychology: "from-indigo-500 to-violet-500",
};

const IMPORTANCE_STYLES: Record<string, string> = {
  "핵심": "bg-red-500/15 text-red-400 border border-red-500/20",
  "중요": "bg-yellow-500/15 text-yellow-400 border border-yellow-500/20",
  "참고": "bg-slate-500/15 text-slate-400 border border-slate-500/20",
};

function ImportanceBadge({ importance }: { importance: string }) {
  return (
    <span
      className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium shrink-0 ${
        IMPORTANCE_STYLES[importance] ?? IMPORTANCE_STYLES["참고"]
      }`}
    >
      {importance}
    </span>
  );
}

function RuleItem({ rule }: { rule: HongStrategyRule }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="group">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-start gap-2.5 py-2 px-2 -mx-2 rounded-lg text-left hover:bg-slate-700/30 transition-colors"
      >
        <ImportanceBadge importance={rule.importance} />
        <span className="text-xs text-slate-200 flex-1 leading-relaxed">
          {rule.rule}
        </span>
        <div className="shrink-0 mt-0.5 text-slate-600 group-hover:text-slate-400 transition-colors">
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </div>
      </button>
      {expanded && (
        <div className="ml-[52px] mr-6 mb-2 text-[11px] text-slate-400 bg-slate-800/60 rounded-md p-2.5 leading-relaxed">
          {rule.detail}
        </div>
      )}
    </div>
  );
}

function SectionAccordion({
  section,
  isOpen,
  onToggle,
}: {
  section: HongStrategySection;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const Icon = SECTION_ICONS[section.icon] ?? Target;
  const gradient = SECTION_COLORS[section.id] ?? "from-slate-500 to-slate-600";
  const coreCount = section.rules.filter((r) => r.importance === "핵심").length;

  return (
    <div
      className={`rounded-xl border transition-all ${
        isOpen
          ? "border-slate-600 bg-slate-800/80"
          : "border-slate-700/50 bg-slate-800/40 hover:border-slate-600/50"
      }`}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-3.5 text-left"
      >
        <div
          className={`w-8 h-8 rounded-lg bg-gradient-to-br ${gradient} flex items-center justify-center shrink-0`}
        >
          <Icon size={14} className="text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-white">{section.title}</div>
          <div className="text-[10px] text-slate-500 mt-0.5">
            {section.rules.length}개 원칙 · 핵심 {coreCount}개
          </div>
        </div>
        <div className="shrink-0 text-slate-500">
          {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>

      {isOpen && (
        <div className="px-3.5 pb-3.5 border-t border-slate-700/50">
          <div className="mt-2 space-y-0.5">
            {section.rules.map((rule, idx) => (
              <RuleItem key={idx} rule={rule} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function HongStrategyGuide() {
  const [openSections, setOpenSections] = useState<Set<string>>(new Set());

  const { data: sections, isLoading } = useQuery({
    queryKey: ["stockking-strategy-guide"],
    queryFn: getStockkingStrategyGuide,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  });

  const toggleSection = (id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleAll = () => {
    if (!sections) return;
    if (openSections.size === sections.length) {
      setOpenSections(new Set());
    } else {
      setOpenSections(new Set(sections.map((s) => s.id)));
    }
  };

  const totalRules = sections?.reduce((acc, s) => acc + s.rules.length, 0) ?? 0;
  const coreRules =
    sections?.reduce(
      (acc, s) => acc + s.rules.filter((r) => r.importance === "핵심").length,
      0
    ) ?? 0;

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <BookOpen size={14} className="text-emerald-400" />
          홍인기 전략 가이드
        </h3>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-slate-500">
            {totalRules}개 원칙 · 핵심 {coreRules}개
          </span>
          {sections && sections.length > 0 && (
            <button
              onClick={toggleAll}
              className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
            >
              {openSections.size === sections.length ? "모두 접기" : "모두 펼치기"}
            </button>
          )}
        </div>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse h-14 bg-slate-700/50 rounded-xl" />
          ))}
        </div>
      )}

      {/* Sections */}
      {sections && sections.length > 0 && (
        <div className="space-y-2">
          {sections.map((section) => (
            <SectionAccordion
              key={section.id}
              section={section}
              isOpen={openSections.has(section.id)}
              onToggle={() => toggleSection(section.id)}
            />
          ))}
        </div>
      )}

      {/* Empty */}
      {!isLoading && (!sections || sections.length === 0) && (
        <div className="text-center py-8">
          <BookOpen size={24} className="text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-500">전략 가이드를 불러올 수 없습니다</p>
        </div>
      )}
    </div>
  );
}
