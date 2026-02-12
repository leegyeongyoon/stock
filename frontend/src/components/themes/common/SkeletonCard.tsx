/** Skeleton placeholder components for theme analysis loading states */

function Pulse({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-slate-700/60 ${className}`}
    />
  );
}

/** Matches SummaryCard shape */
export function SummaryCardSkeleton() {
  return (
    <div className="relative overflow-hidden bg-gradient-to-br from-slate-800 to-slate-900 rounded-2xl p-3 sm:p-5 border border-slate-700/50">
      <div className="absolute top-0 right-0 w-20 h-20 bg-gradient-to-br from-blue-500/10 to-purple-500/10 rounded-full blur-2xl" />
      <div className="relative">
        <div className="flex items-center justify-between mb-2 sm:mb-3">
          <Pulse className="w-8 h-8 rounded-lg" />
          <Pulse className="w-10 h-5 rounded-full" />
        </div>
        <Pulse className="w-16 h-3 mb-2" />
        <Pulse className="w-24 h-7 mb-1" />
        <Pulse className="w-20 h-3 mt-1" />
      </div>
    </div>
  );
}

/** Matches a theme card in HotThemeSection */
export function ThemeCardSkeleton() {
  return (
    <div className="bg-slate-800/50 rounded-xl p-3 sm:p-4 border border-slate-700/50">
      <div className="flex items-center justify-between mb-2">
        <Pulse className="w-28 h-5" />
        <Pulse className="w-14 h-5 rounded-full" />
      </div>
      <Pulse className="w-full h-3 mb-2" />
      <Pulse className="w-3/4 h-3 mb-3" />
      <div className="flex gap-2">
        <Pulse className="w-16 h-6 rounded" />
        <Pulse className="w-16 h-6 rounded" />
        <Pulse className="w-16 h-6 rounded" />
      </div>
    </div>
  );
}

/** Matches a theme ranking row */
export function RankingRowSkeleton() {
  return (
    <div className="bg-slate-800/50 rounded-xl p-3 sm:p-4 border border-slate-700/50 flex items-center gap-3">
      <Pulse className="w-8 h-8 rounded-lg shrink-0" />
      <div className="flex-1 space-y-2">
        <Pulse className="w-32 h-4" />
        <Pulse className="w-48 h-3" />
      </div>
      <div className="flex gap-2">
        <Pulse className="w-12 h-6 rounded" />
        <Pulse className="w-12 h-6 rounded" />
      </div>
    </div>
  );
}

/** Full overview skeleton grid: 4 summary cards + 3 theme cards */
export function OverviewSkeleton() {
  return (
    <div className="space-y-3 sm:space-y-4 lg:space-y-6">
      <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-4 md:gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SummaryCardSkeleton key={i} />
        ))}
      </div>

      {/* AI Insight placeholder */}
      <div className="bg-slate-800/50 rounded-xl p-4 sm:p-6 border border-slate-700/50">
        <Pulse className="w-40 h-5 mb-3" />
        <Pulse className="w-full h-3 mb-2" />
        <Pulse className="w-5/6 h-3 mb-2" />
        <Pulse className="w-2/3 h-3" />
      </div>

      {/* Theme cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <ThemeCardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}

/** Ranking tab skeleton: list of ranking rows */
export function RankingSkeleton() {
  return (
    <div className="space-y-3">
      <Pulse className="w-48 h-3 mb-2" />
      {Array.from({ length: 6 }).map((_, i) => (
        <RankingRowSkeleton key={i} />
      ))}
    </div>
  );
}
