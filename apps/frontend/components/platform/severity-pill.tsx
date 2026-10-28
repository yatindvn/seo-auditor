import { AlertTriangle, Info, XCircle } from "lucide-react";
import type { RuleSeverity } from "@seo-auditor/shared";

const SEVERITY: Record<RuleSeverity, { label: string; className: string; Icon: typeof Info }> = {
  critical: { label: "Critical", Icon: XCircle, className: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400" },
  warning: { label: "Warning", Icon: AlertTriangle, className: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400" },
  info: { label: "Info", Icon: Info, className: "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400" },
};

export function SeverityPill({ severity }: { severity: RuleSeverity }) {
  const s = SEVERITY[severity];
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${s.className}`}><s.Icon className="h-3 w-3" aria-hidden />{s.label}</span>;
}
