import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import type { VitalsRating, VitalsRow, VitalsStatus } from "@seo-auditor/shared";

import { formatVitalsMetric } from "@/lib/platform-charts";

const PILL: Record<VitalsRating, { label: string; className: string; Icon: typeof CheckCircle2 }> = {
  good: { label: "Good", Icon: CheckCircle2, className: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400" },
  needs_improvement: { label: "Needs improvement", Icon: AlertTriangle, className: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400" },
  poor: { label: "Poor", Icon: XCircle, className: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400" },
};

/** A rating as icon + text, never color alone. */
export function RatingPill({ rating }: { rating: VitalsRating | null }) {
  if (!rating) return null;
  const { label, className, Icon } = PILL[rating];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      <Icon className="h-3 w-3" aria-hidden />{label}
    </span>
  );
}

export const VITALS_NOT_CONFIGURED =
  "Core Web Vitals not measured. Set PSI_API_KEY or LIGHTHOUSE_ENABLED=true on the backend.";

function Metric({ row, metric }: { row: VitalsRow; metric: "lcp_ms" | "inp_ms" | "cls" | "tbt_ms" }) {
  const value = row[metric];
  if (value == null) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap items-center gap-1.5 tabular-nums">
      {formatVitalsMetric(metric, value)} <RatingPill rating={row.metric_ratings[metric]} />
    </span>
  );
}

export function VitalsTable({ rows, status }: { rows: VitalsRow[]; status: VitalsStatus }) {
  if (status === "not_configured") return <p className="text-sm text-muted-foreground">{VITALS_NOT_CONFIGURED}</p>;
  if (status === "disabled") return <p className="text-sm text-muted-foreground">Core Web Vitals were turned off for this audit.</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No pages were measured.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th>
            <th className="py-2 pr-4 font-medium">Score</th>
            <th className="py-2 pr-4 font-medium">LCP</th>
            <th className="py-2 pr-4 font-medium">INP</th>
            <th className="py-2 pr-4 font-medium">CLS</th>
            <th className="py-2 pr-4 font-medium">TBT (lab)</th>
            <th className="py-2 font-medium">Data</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={r.url} className="align-top">
              <td className="sticky left-0 max-w-[260px] break-all bg-card py-2 pr-4">{r.url}</td>
              {r.error ? (
                <td colSpan={6} className="py-2 text-muted-foreground">Not measured: {r.error}</td>
              ) : (
                <>
                  <td className="py-2 pr-4 tabular-nums">{r.performance_score ?? "—"}</td>
                  <td className="py-2 pr-4"><Metric row={r} metric="lcp_ms" /></td>
                  <td className="py-2 pr-4"><Metric row={r} metric="inp_ms" /></td>
                  <td className="py-2 pr-4"><Metric row={r} metric="cls" /></td>
                  <td className="py-2 pr-4"><Metric row={r} metric="tbt_ms" /></td>
                  <td className="py-2 text-muted-foreground">{r.data_kind} · {r.source}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
