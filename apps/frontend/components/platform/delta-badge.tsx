import { cn } from "@/lib/utils";

/** `value` is new minus old. For ranks a lower number is better, so pass
 *  `lowerIsBetter` and a drop from 9 to 4 (value -5) shows as an improvement. */
export function DeltaBadge({ value, lowerIsBetter = false, suffix = "" }: {
  value: number | null | undefined; lowerIsBetter?: boolean; suffix?: string;
}) {
  if (value == null || value === 0) return null;
  const improved = lowerIsBetter ? value < 0 : value > 0;
  const size = Math.round(Math.abs(value) * 10) / 10;
  return (
    <span
      aria-label={`${improved ? "improved" : "worse"} by ${size}${suffix}`}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
        improved ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" : "bg-rose-500/10 text-rose-700 dark:text-rose-400",
      )}
    >
      {improved ? "▲" : "▼"}{size}{suffix}
    </span>
  );
}
