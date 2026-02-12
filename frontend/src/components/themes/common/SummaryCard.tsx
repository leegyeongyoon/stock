export default function SummaryCard({
  title,
  value,
  subtitle,
  trend,
  icon,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
  icon: React.ReactNode;
}) {
  return (
    <div className="relative overflow-hidden bg-gradient-to-br from-slate-800 to-slate-900 rounded-2xl p-3 sm:p-5 border border-slate-700/50">
      <div className="absolute top-0 right-0 w-20 h-20 bg-gradient-to-br from-blue-500/10 to-purple-500/10 rounded-full blur-2xl" />
      <div className="relative">
        <div className="flex items-center justify-between mb-2 sm:mb-3">
          <span className="text-xl sm:text-2xl">{icon}</span>
          {trend && (
            <span
              className={`text-xs px-2 py-1 rounded-full ${
                trend === "up"
                  ? "bg-emerald-500/20 text-emerald-400"
                  : trend === "down"
                  ? "bg-red-500/20 text-red-400"
                  : "bg-slate-500/20 text-slate-400"
              }`}
            >
              {trend === "up" ? "▲" : trend === "down" ? "▼" : "—"}
            </span>
          )}
        </div>
        <p className="text-xs sm:text-sm text-slate-400 mb-1">{title}</p>
        <p className="text-xl sm:text-2xl font-bold text-white">{value}</p>
        {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
      </div>
    </div>
  );
}
