"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { RenderComparison, RenderStatus } from "@seo-auditor/shared";

const LABELS = { title: "Title", meta_description: "Description", canonical: "Canonical", meta_robots: "Robots", h1: "H1" } as const;
type Field = keyof typeof LABELS;

/** Mirrors JS_CONTENT_DEPENDENT in app/rendering/compare.py. */
function contentDependent(r: RenderComparison): boolean {
  const raw = r.raw_word_count ?? 0, rendered = r.rendered_word_count ?? 0;
  return rendered >= 2 * raw && rendered - raw >= 200;
}

function Chip({ children, tone = "amber" }: { children: React.ReactNode; tone?: "amber" | "slate" }) {
  const cls = tone === "amber"
    ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400"
    : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400";
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

const shown = (v: string | null) => (v && v.trim() ? v : "(none)");

export function RenderingTable({ rows, status, reason }: { rows: RenderComparison[]; status: RenderStatus; reason: string | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (status === "disabled") return <p className="text-sm text-muted-foreground">Not rendered. Run an audit with <em>Render JavaScript</em> on.</p>;
  if (status === "unavailable") return <p className="text-sm text-muted-foreground">Browser not available on this server: {reason ?? "unknown reason"}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No pages were rendered.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th>
            <th className="py-2 pr-4 font-medium">Words (raw → rendered)</th>
            <th className="py-2 pr-4 font-medium">What changed</th>
            <th className="py-2 pr-4 font-medium">JS-only links</th>
            <th className="py-2 font-medium">Time</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => {
            const fields = Object.keys(r.changes) as Field[];
            const expandable = r.status === "rendered" && (fields.length > 0 || r.js_only_links.length > 0);
            const isOpen = open === r.url;
            return (
              <Fragment key={r.url}>
                <tr className="align-top">
                  <td className="sticky left-0 max-w-[140px] break-all bg-card py-2 pr-4 sm:max-w-[260px]">
                    {expandable ? (
                      <button type="button" onClick={() => setOpen(isOpen ? null : r.url)} aria-expanded={isOpen}
                              aria-label={`Show changes for ${r.url}`} className="flex items-start gap-1 text-left hover:text-primary">
                        {isOpen ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
                        {r.url}
                      </button>
                    ) : r.url}
                  </td>
                  {r.status === "failed" ? (
                    <td colSpan={4} className="py-2 text-muted-foreground">Couldn&apos;t render: {r.error}</td>
                  ) : (
                    <>
                      <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{r.raw_word_count ?? "—"} → {r.rendered_word_count ?? "—"}</td>
                      <td className="py-2 pr-4">
                        <span className="flex flex-wrap gap-1">
                          {contentDependent(r) && <Chip>Content</Chip>}
                          {fields.map((f) => <Chip key={f}>{LABELS[f]}</Chip>)}
                          {!contentDependent(r) && fields.length === 0 && r.js_only_links_count === 0 && <Chip tone="slate">No differences</Chip>}
                        </span>
                      </td>
                      <td className="py-2 pr-4 tabular-nums">{r.js_only_links_count}</td>
                      <td className="whitespace-nowrap py-2 tabular-nums">{r.render_ms != null ? `${(r.render_ms / 1000).toFixed(1)} s` : "—"}</td>
                    </>
                  )}
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={5} className="bg-muted/30 px-3 py-3">
                      <dl className="space-y-2">
                        {fields.map((f) => (
                          <div key={f} className="grid gap-1 sm:grid-cols-[120px_1fr_1fr]">
                            <dt className="text-xs font-medium text-muted-foreground">{LABELS[f]}</dt>
                            <dd className="break-all"><span className="text-xs text-muted-foreground">Raw: </span>{shown(r.changes[f]!.raw)}</dd>
                            <dd className="break-all"><span className="text-xs text-muted-foreground">Rendered: </span>{shown(r.changes[f]!.rendered)}</dd>
                          </div>
                        ))}
                        {r.js_only_links.length > 0 && (
                          <div>
                            <dt className="text-xs font-medium text-muted-foreground">Links only after JavaScript ({r.js_only_links_count})</dt>
                            <dd><ul className="mt-1 space-y-0.5">{r.js_only_links.slice(0, 10).map((l) => <li key={l} className="break-all">{l}</li>)}</ul></dd>
                          </div>
                        )}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
