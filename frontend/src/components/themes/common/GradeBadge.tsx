const GRADE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  A: { bg: "bg-emerald-500", text: "text-emerald-100", border: "border-emerald-500/30" },
  B: { bg: "bg-blue-500", text: "text-blue-100", border: "border-blue-500/30" },
  C: { bg: "bg-amber-500", text: "text-amber-100", border: "border-amber-500/30" },
  D: { bg: "bg-orange-500", text: "text-orange-100", border: "border-orange-500/30" },
  F: { bg: "bg-red-500", text: "text-red-100", border: "border-red-500/30" },
};

export function getGradeColors(grade: string) {
  return GRADE_COLORS[grade] || GRADE_COLORS.C;
}

export default function GradeBadge({ grade, size = "md" }: { grade: string; size?: "sm" | "md" | "lg" }) {
  const colors = getGradeColors(grade);
  const sizeClasses = {
    sm: "w-6 h-6 text-xs",
    md: "w-8 h-8 text-sm",
    lg: "w-10 h-10 text-base",
  };

  return (
    <div className={`${sizeClasses[size]} rounded-lg ${colors.bg} flex items-center justify-center`}>
      <span className={`font-bold ${colors.text}`}>{grade}</span>
    </div>
  );
}
