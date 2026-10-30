"use client";

import { Fragment, useState } from "react";
import { CheckCircle2, Link2, MinusCircle } from "lucide-react";
import type { AiAnswer } from "@seo-auditor/shared";

import { ordinal, safeUrl, segments } from "@/lib/ai-visibility";

function Pill({ on, yes, no }: { on: boolean; yes: string; no: string }) {
  return on ? (
    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400"><CheckCircle2 className="h-3 w-3" aria-hidden />{yes}</span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400"><MinusCircle className="h-3 w-3" aria-hidden />{no}</span>
  );
}

export function AiAnswers({ items }: { items: AiAnswer[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No answers in this run.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
          <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Prompt</th><th className="py-2 pr-4 font-medium">Model</th>
          <th className="py-2 pr-4 font-medium">Mentioned</th><th className="py-2 pr-4 font-medium">Position</th><th className="py-2 font-medium">Cited</th></tr></thead>
        <tbody className="divide-y">
          {items.map((a) => {
            const isOpen = open === a.id;
            return (
              <Fragment key={a.id}>
                <tr className="align-top">
                  <td className="sticky left-0 max-w-[180px] bg-card py-2 pr-4 sm:max-w-[320px]">
                    <button type="button" onClick={() => setOpen(isOpen ? null : a.id)} aria-expanded={isOpen}
                            aria-label={`Show answer: ${a.prompt} (${a.provider})`} className="text-left hover:text-primary">{a.prompt}</button>
                  </td>
                  <td className="py-2 pr-4 text-muted-foreground">{a.provider}</td>
                  {a.error ? <td colSpan={3} className="py-2 text-muted-foreground">Failed: {a.error}</td> : (
                    <>
                      <td className="py-2 pr-4"><Pill on={a.mentioned} yes="Mentioned" no="Not mentioned" /></td>
                      <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{a.position ? `${ordinal(a.position)} of ${a.brands.length}` : "—"}</td>
                      <td className="py-2"><Pill on={a.cited} yes="Cited" no="Not cited" /></td>
                    </>
                  )}
                </tr>
                {isOpen && !a.error && (
                  <tr><td colSpan={5} className="bg-muted/30 px-3 py-3">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {segments(a.answer, a.highlights).map((s, i) => s.owner
                        ? <mark key={i} className="rounded bg-amber-100 px-0.5 text-foreground dark:bg-amber-900/50">{s.text}</mark>
                        : <Fragment key={i}>{s.text}</Fragment>)}
                    </p>
                    {a.citations.length > 0 && (
                      <ul className="mt-3 space-y-1 text-xs">
                        {a.citations.map((c, i) => {
                          const href = safeUrl(c.url);
                          return href ? (
                            <li key={i} className="flex items-center gap-1 break-all"><Link2 className="h-3 w-3 shrink-0" aria-hidden />
                              <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{c.title || href}</a></li>
                          ) : null;
                        })}
                      </ul>
                    )}
                  </td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
