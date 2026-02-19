"use client";

import { useQuery } from "@tanstack/react-query";
import { getGyleeFilters, type GyleeFilterStats } from "@/lib/api";
import { Shield, Building2, TrendingDown, RefreshCw } from "lucide-react";

function FilterCard({
  icon: Icon,
  name,
  condition,
  description,
  passCount,
  passRate,
  color,
}: {
  icon: typeof Shield;
  name: string;
  condition: string;
  description: string;
  passCount: number;
  passRate: number;
  color: string;
}) {
  return (
    <div className={`bg-slate-800/50 rounded-xl border p-4 ${color}`}>
      <div className="flex items-center gap-2 mb-2">
        <Icon size={16} className="shrink-0" />
        <h4 className="text-sm font-semibold text-white">{name}</h4>
      </div>
      <p className="text-[10px] text-slate-500 mb-3">{condition}</p>
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">{description}</span>
        <div className="text-right">
          <div className="text-lg font-bold text-white font-mono">
            {typeof passRate === "number" ? passRate.toFixed(1) : passRate}%
          </div>
          <div className="text-[10px] text-slate-500">{passCount}종목</div>
        </div>
      </div>
    </div>
  );
}

export default function FilterStatusPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["gylee-filters"],
    queryFn: getGyleeFilters,
    refetchInterval: 30000,
    retry: 2,
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="animate-pulse h-8 w-48 bg-slate-800 rounded" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse h-32 bg-slate-800 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  const filters = data?.filters ?? [];
  const scanStats = data?.scan_stats;
  const dataDate = data?.data_date;

  const filterConfigs = [
    {
      icon: Building2,
      color: "border-purple-500/30",
      fallback: { name: "시가총액 5000억+", condition: "시가총액 >= 5,000억원", description: "WR +10%p", pass_count: 0, pass_rate: 0 },
    },
    {
      icon: Shield,
      color: "border-blue-500/30",
      fallback: { name: "기관 순매수 50~200억", condition: "50억 <= 기관 <= 200억", description: "WR +5%p", pass_count: 0, pass_rate: 0 },
    },
    {
      icon: TrendingDown,
      color: "border-emerald-500/30",
      fallback: { name: "눌림 95%깊이+거래량", condition: "깊이>=5% & 거래량>=중간값", description: "48건 제거", pass_count: 0, pass_rate: 0 },
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Shield size={16} className="text-purple-400" />
          3대 필터 현황
        </h3>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          {dataDate && (
            <span>데이터: {dataDate.slice(0, 4)}-{dataDate.slice(4, 6)}-{dataDate.slice(6, 8)}</span>
          )}
          {data?.last_refresh && (
            <span className="flex items-center gap-1">
              <RefreshCw size={10} />
              {new Date(data.last_refresh).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {filterConfigs.map((cfg, idx) => {
          const f = filters[idx] ?? cfg.fallback;
          return (
            <FilterCard
              key={idx}
              icon={cfg.icon}
              name={f.name}
              condition={f.condition}
              description={f.description}
              passCount={f.pass_count}
              passRate={f.pass_rate}
              color={cfg.color}
            />
          );
        })}
      </div>

      {/* 스캔 통계 */}
      {scanStats && scanStats.total_candidates > 0 && (
        <div className="bg-slate-800/30 rounded-lg p-3 flex items-center gap-4 text-[11px]">
          <span className="text-slate-500">최근 스캔:</span>
          <span className="text-slate-400">후보 {scanStats.total_candidates}</span>
          <span className="text-purple-400">시총 -{scanStats.cap_filtered}</span>
          <span className="text-blue-400">기관 -{scanStats.inst_filtered}</span>
          <span className="text-emerald-400">눌림 -{scanStats.pullback_filtered}</span>
          <span className="text-white font-medium">통과 {scanStats.passed}</span>
        </div>
      )}
    </div>
  );
}
