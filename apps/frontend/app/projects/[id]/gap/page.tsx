"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { GapResult } from "@seo-auditor/shared";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { PageHeader } from "@/components/platform/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function GapPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const competitors = useApi(() => Platform.listCompetitors(projectId), [projectId]);
  const [picked, setPicked] = useState<string[]>([]);
  const [country, setCountry] = useState("US");
  const [limit, setLimit] = useState(500);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<GapResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (competitors.data) setPicked(competitors.data.items.slice(0, 5).map((c) => c.domain));
  }, [competitors.data]);

  const run = async () => {
    setRunning(true); setError(null);
    try {
      setResult(await Platform.contentGap(projectId, { competitors: picked, country, language: "en", limit }));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Content Gap" description="Keywords your competitors rank for in the top 20 that you don't rank for at all." />
      <AsyncState state={competitors} isEmpty={(d) => d.items.length === 0} emptyTitle="Add competitors first"
                  emptyText="Content gap compares this site with its competitors."
                  emptyAction={<Link href={`/projects/${projectId}/ranks`} className="text-sm text-primary hover:underline">Add competitors in Rank Tracker</Link>}>
        {(d) => (
          <section className="flex flex-col gap-4 rounded-[18px] border bg-card p-5 lg:flex-row lg:items-end">
            <fieldset className="flex flex-wrap gap-3 text-sm">
              <legend className="mb-2 text-xs text-muted-foreground">Competitors (up to 5)</legend>
              {d.items.map((c) => (
                <label key={c.id} className="flex items-center gap-2 rounded-full border px-3 py-1.5">
                  <input type="checkbox" aria-label={c.domain} checked={picked.includes(c.domain)}
                         disabled={!picked.includes(c.domain) && picked.length >= 5}
                         onChange={(e) => setPicked((p) => (e.target.checked ? [...p, c.domain] : p.filter((x) => x !== c.domain)))} />
                  {c.domain}
                </label>
              ))}
            </fieldset>
            <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
              <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="w-20 rounded-full" />
            </label>
            <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Keywords per domain</span>
              <Input aria-label="Keywords per domain" type="number" min={10} max={1000} value={limit}
                     onChange={(e) => setLimit(Number(e.target.value) || 500)} className="w-28 rounded-full" />
            </label>
            <Button className="rounded-full active:scale-95" disabled={running || picked.length === 0} onClick={run}>
              {running ? "Running…" : "Run gap analysis"}
            </Button>
          </section>
        )}
      </AsyncState>

      {error && <div role="alert" className="rounded-[18px] border border-rose-200 bg-rose-50/60 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-400">{error}</div>}

      {result && (
        <section className="space-y-3">
          <DryRunBanner show={result.dry_run} />
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{result.total_gaps} gaps, sorted by opportunity (volume weighted by ease)</p>
            <a className="text-sm text-primary hover:underline" href={Platform.contentGapCsvUrl(projectId, result.competitors, country, "en", limit)}>
              Download CSV{result.dry_run ? " (preview)" : ""}
            </a>
          </div>
          {result.rows.length === 0 ? <EmptyState title="No gaps found" text="Every keyword these competitors win, you rank for too." /> : (
            <div className="overflow-x-auto rounded-[18px] border bg-card">
              <table className="w-full min-w-[720px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="sticky left-0 bg-card px-4 py-3 font-medium">Keyword</th>
                    <th className="px-4 py-3 text-right font-medium">Volume</th>
                    <th className="px-4 py-3 text-right font-medium">KD</th>
                    <th className="px-4 py-3 text-right font-medium">Opportunity</th>
                    {result.competitors.map((c) => <th key={c} className="px-4 py-3 text-right font-medium">{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((r) => (
                    <tr key={r.keyword} className="border-b last:border-0">
                      <td className="sticky left-0 bg-card px-4 py-3 font-medium">{r.keyword}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{r.search_volume?.toLocaleString() ?? "—"}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{r.difficulty ?? "—"}</td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">{Math.round(r.opportunity).toLocaleString()}</td>
                      {result.competitors.map((c) => <td key={c} className="px-4 py-3 text-right tabular-nums">{r.competitors[c]?.position ?? "—"}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
