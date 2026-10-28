"use client";

import { Fragment, useState } from "react";
import { AlertOctagon, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, XCircle } from "lucide-react";
import type { A11yImpact, A11yResult, A11yStatus } from "@seo-auditor/shared";

const ROSE = "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400";
const AMBER = "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400";
const SLATE = "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400";
const EMERALD = "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400";

const IMPACT: Record<A11yImpact, { label: string; className: string; Icon: typeof Info }> = {
  critical: { label: "Critical", className: ROSE, Icon: XCircle },
  serious: { label: "Serious", className: ROSE, Icon: AlertOctagon },
  moderate: { label: "Moderate", className: AMBER, Icon: AlertTriangle },
  minor: { label: "Minor", className: SLATE, Icon: Info },
};

function Pill({ className, Icon, label }: { className: string; Icon: typeof Info; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      <Icon className="h-3 w-3" aria-hidden />{label}
    </span>
  );
}

function ScorePill({ score }: { score: number }) {
  if (score >= 90) return <Pill className={EMERALD} Icon={CheckCircle2} label="Good" />;
  if (score >= 50) return <Pill className={AMBER} Icon={AlertTriangle} label="Needs work" />;
  return <Pill className={ROSE} Icon={XCircle} label="Poor" />;
}

const ORDER: A11yImpact[] = ["critical", "serious", "moderate", "minor"];

export function AccessibilityTable({ rows, status, reason }: { rows: A11yResult[]; status: A11yStatus; reason: string | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (status === "disabled") return <p className="text-sm text-muted-foreground">Not scanned. Run an audit with <em>Accessibility audit</em> on.</p>;
  if (status === "unavailable") return <p className="text-sm text-muted-foreground">Browser not available on this server: {reason ?? "unknown reason"}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No pages were scanned.</p>;
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th>
              <th className="py-2 pr-4 font-medium">Score</th>
              {ORDER.map((i) => <th key={i} className="py-2 pr-4 font-medium">{IMPACT[i].label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => {
              const isOpen = open === r.url;
              const expandable = r.status === "scanned" && r.violations.length > 0;
              return (
                <Fragment key={r.url}>
                  <tr className="align-top">
                    <td className="sticky left-0 max-w-[140px] break-all bg-card py-2 pr-4 sm:max-w-[260px]">
                      {expandable ? (
                        <button type="button" onClick={() => setOpen(isOpen ? null : r.url)} aria-expanded={isOpen}
                                aria-label={`Show issues for ${r.url}`} className="flex items-start gap-1 text-left hover:text-primary">
                          {isOpen ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
                          {r.url}
                        </button>
                      ) : r.url}
                    </td>
                    {r.status === "failed" ? (
                      <td colSpan={5} className="py-2 text-muted-foreground">Couldn&apos;t scan: {r.error}</td>
                    ) : (
                      <>
                        <td className="whitespace-nowrap py-2 pr-4">
                          <span className="flex items-center gap-1.5 tabular-nums">{r.score}{r.score != null && <ScorePill score={r.score} />}</span>
                        </td>
                        {ORDER.map((i) => <td key={i} className="py-2 pr-4 tabular-nums">{r.counts[i]}</td>)}
                      </>
                    )}
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={6} className="bg-muted/30 px-3 py-3">
                        <ul className="space-y-3">
                          {r.violations.map((v) => {
                            const impact = IMPACT[v.impact];
                            return (
                              <li key={v.id} className="space-y-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Pill className={impact.className} Icon={impact.Icon} label={impact.label} />
                                  <span className="font-medium">{v.help}</span>
                                  <span className="text-muted-foreground">{v.nodes_count} {v.nodes_count === 1 ? "element" : "elements"}</span>
                                  {v.help_url && (
                                    <a href={v.help_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">How to fix</a>
                                  )}
                                </div>
                                {v.wcag.length > 0 && (
                                  <div className="flex flex-wrap gap-1">{v.wcag.map((t) => <span key={t} className="rounded border px-1 text-[10px] text-muted-foreground">{t}</span>)}</div>
                                )}
                                {v.targets.length > 0 && (
                                  <ul className="space-y-0.5">{v.targets.map((t, i) => <li key={i} className="break-all font-mono text-[11px] text-muted-foreground">{t}</li>)}</ul>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Score: 100 minus 10/7/3/1 per failed rule (critical/serious/moderate/minor). Automated checks find about a
        third of accessibility problems, so this is not a full WCAG audit.
      </p>
    </div>
  );
}
