"use client";

import { Fragment, useState } from "react";
import { ExternalLink } from "lucide-react";
import type { ContentResult } from "@seo-auditor/shared";

import { num } from "@/lib/content";

export function ContentResults({ results }: { results: ContentResult[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
          <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th><th className="py-2 pr-4 font-medium">Words</th>
          <th className="py-2 pr-4 font-medium">H2s</th><th className="py-2 pr-4 font-medium">Schema</th>
          <th className="py-2 pr-4 font-medium">Ref. domains</th><th className="py-2 pr-4 font-medium">Backlinks</th>
          <th className="py-2 pr-4 font-medium">Readability</th><th className="py-2 font-medium">Issues</th></tr></thead>
        <tbody className="divide-y">
          {results.map((r) => {
            const label = r.title || r.domain;
            const isOpen = open === r.position;
            const h2s = r.outline.filter((h) => h.level === 2).length;
            return (
              <Fragment key={r.position}>
                <tr className="align-top">
                  <td className="sticky left-0 max-w-[220px] bg-card py-2 pr-4 sm:max-w-[340px]">
                    <div className="flex items-start gap-2">
                      <span className="tabular-nums text-muted-foreground">{r.position}</span>
                      <div className="min-w-0">
                        {r.outline.length > 0 ? (
                          <button type="button" onClick={() => setOpen(isOpen ? null : r.position)} aria-expanded={isOpen}
                                  aria-label={`Show outline: ${label}`} className="text-left font-medium hover:text-primary">{label}</button>
                        ) : <span className="font-medium">{label}</span>}
                        <a href={/^https?:\/\//i.test(r.url) ? r.url : undefined} target="_blank" rel="noopener noreferrer"
                           className="flex items-center gap-1 break-all text-xs text-muted-foreground hover:text-primary">{r.domain}<ExternalLink className="h-3 w-3 shrink-0" aria-hidden /></a>
                      </div>
                    </div>
                  </td>
                  {r.error ? <td colSpan={7} className="py-2 text-muted-foreground">Couldn&apos;t fetch ({r.error}){r.referring_domains != null ? ` · ${num(r.referring_domains)} referring domains` : ""}</td> : (
                    <>
                      <td className="py-2 pr-4 tabular-nums">{num(r.word_count)}</td>
                      <td className="py-2 pr-4 tabular-nums">{h2s}</td>
                      <td className="py-2 pr-4"><div className="flex flex-wrap gap-1">{r.schema_types.length ? r.schema_types.map((t) => (
                        <span key={t} className="rounded-full border px-2 py-0.5 text-[11px]">{t}</span>)) : <span className="text-muted-foreground">—</span>}</div></td>
                      <td className="py-2 pr-4 tabular-nums">{num(r.referring_domains)}</td>
                      <td className="py-2 pr-4 tabular-nums">{num(r.backlinks)}</td>
                      <td className="py-2 pr-4 tabular-nums">{r.readability ?? "—"}</td>
                      <td className="py-2 tabular-nums">{num(r.issues)}</td>
                    </>
                  )}
                </tr>
                {isOpen && (
                  <tr><td colSpan={8} className="bg-muted/30 px-3 py-3">
                    <ul aria-label={`Outline of ${label}`} className="space-y-1 text-sm">
                      {r.outline.map((h, i) => (
                        <li key={i} className={h.level === 3 ? "pl-6 text-muted-foreground" : "font-medium"}>
                          <span className="mr-2 text-[11px] text-muted-foreground">H{h.level}</span>{h.text}</li>
                      ))}
                    </ul>
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
