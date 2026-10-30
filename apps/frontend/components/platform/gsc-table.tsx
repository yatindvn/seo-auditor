"use client";

import { useState } from "react";
import type { GscSort } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { formatCount, formatCtr, formatPosition } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

const COLUMNS: { key: GscSort; label: string }[] = [
  { key: "clicks", label: "Clicks" }, { key: "impressions", label: "Impressions" },
  { key: "ctr", label: "CTR" }, { key: "position", label: "Position" },
];

export function GscTable({ projectId, kind }: { projectId: number; kind: "pages" | "queries" }) {
  const [sort, setSort] = useState<GscSort>("clicks");
  const [offset, setOffset] = useState(0);
  const fetcher = kind === "pages" ? Platform.gscPages : Platform.gscQueries;
  const state = useApi(() => fetcher(projectId, sort, offset), [projectId, kind, sort, offset]);
  return (
    <section className="rounded-[18px] border bg-card p-5">
      <h2 className="mb-3 font-semibold tracking-tight">{kind === "pages" ? "Top pages" : "Top queries"} <span className="text-xs font-normal text-muted-foreground">(28 days)</span></h2>
      <AsyncState state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No data yet" emptyText="Run a sync to load Search Console data.">
        {(d) => (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="sticky left-0 bg-card py-2 pr-4 font-medium">{kind === "pages" ? "Page" : "Query"}</th>
                    {COLUMNS.map((c) => (
                      <th key={c.key} className="py-2 pr-4 font-medium">
                        <button type="button" onClick={() => { setSort(c.key); setOffset(0); }}
                                aria-pressed={sort === c.key} className={sort === c.key ? "text-foreground underline" : "hover:text-foreground"}>{c.label}</button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {d.items.map((r) => (
                    <tr key={r.key}>
                      <td className="sticky left-0 max-w-[160px] break-all bg-card py-2 pr-4 sm:max-w-[360px]">{r.key}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatCount(r.clicks)}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatCount(r.impressions)}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatCtr(r.ctr)}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatPosition(r.position)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.total > 50 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))} className="rounded-full border px-3 py-1 disabled:opacity-50">Previous</button>
                <span>{offset + 1}–{Math.min(offset + 50, d.total)} of {d.total}</span>
                <button type="button" disabled={offset + 50 >= d.total} onClick={() => setOffset(offset + 50)} className="rounded-full border px-3 py-1 disabled:opacity-50">Next</button>
              </div>
            )}
          </>
        )}
      </AsyncState>
    </section>
  );
}
