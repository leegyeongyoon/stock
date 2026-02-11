"use client";

interface Props {
  conditions_met: string[];
  conditions_unmet: string[];
  score: number;
  max_score: number;
}

export default function ConditionGauge({
  conditions_met,
  conditions_unmet,
  score,
  max_score,
}: Props) {
  const pct = max_score > 0 ? (score / max_score) * 100 : 0;
  const barColor =
    pct >= 80
      ? "bg-green-500"
      : pct >= 60
      ? "bg-yellow-500"
      : "bg-slate-600";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-xs font-mono text-slate-400 shrink-0">
          {score}/{max_score}
        </span>
      </div>
      <div className="space-y-0.5">
        {conditions_met.map((c, i) => (
          <p key={i} className="text-xs text-green-400/80 pl-1">
            <span className="mr-1">&#10003;</span>
            {c}
          </p>
        ))}
        {conditions_unmet.map((c, i) => (
          <p key={i} className="text-xs text-slate-500 pl-1">
            <span className="mr-1">&#10007;</span>
            {c}
          </p>
        ))}
      </div>
    </div>
  );
}
