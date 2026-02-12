export default function ChangeRate({
  value,
  size = "md",
  showSign = true,
}: {
  value: number;
  size?: "sm" | "md" | "lg";
  showSign?: boolean;
}) {
  const isPositive = value > 0;
  const isNegative = value < 0;

  const colorClass = isPositive
    ? "text-emerald-400"
    : isNegative
    ? "text-red-400"
    : "text-slate-400";

  const sizeClasses = {
    sm: "text-xs",
    md: "text-sm",
    lg: "text-xl",
  };

  return (
    <span className={`font-bold font-mono ${colorClass} ${sizeClasses[size]}`}>
      {showSign && isPositive ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}
