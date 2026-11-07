"use client";

import { FormEvent, useState } from "react";
import type { ExploreResult } from "@seo-auditor/shared";

import { EmptyState } from "@/components/platform/async-state";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { PageHeader } from "@/components/platform/page-header";
import { PageGuide } from "@/components/platform/page-guide";
import { KEYWORDS_GUIDE } from "@/lib/page-guides";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, Platform } from "@/services/platform";

const SOURCE = { seed: "Seed", autocomplete: "Autocomplete", people_also_ask: "People Also Ask" } as const;
const n = (v: number | null) => (v == null ? "—" : v.toLocaleString());

export default function KeywordsPage() {
  const [seed, setSeed] = useState("");
  const [country, setCountry] = useState("US");
  const [cluster, setCluster] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ExploreResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!seed.trim()) return;
    setRunning(true); setError(null);
    try {
      setResult(await Platform.explore({ seed, country, language: "en", cluster }));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title="Keywords Explorer" description="Ideas, search volume, difficulty and a traffic estimate for any seed keyword." />
      <form onSubmit={submit} className="flex flex-col gap-4 rounded-[18px] border bg-card p-5 lg:flex-row lg:items-end">
        <label className="flex-1 space-y-1 text-sm"><span className="text-xs text-muted-foreground">Seed keyword</span>
          <Input aria-label="Seed keyword" placeholder="espresso machine" value={seed} maxLength={80}
                 onChange={(e) => setSeed(e.target.value)} className="rounded-full" />
        </label>
        <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
          <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="w-20 rounded-full" />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" aria-label="Group into clusters" checked={cluster} onChange={(e) => setCluster(e.target.checked)} />
          Group into clusters <span className="text-xs text-muted-foreground">(one search per keyword)</span>
        </label>
        <Button type="submit" className="rounded-full active:scale-95" disabled={running || !seed.trim()}>
          {running ? "Exploring…" : "Explore"}
        </Button>
      </form>

      {error && <div role="alert" className="rounded-[18px] border border-rose-200 bg-rose-50/60 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-400">{error}</div>}

      {!result && !error && <EmptyState title="Enter a seed keyword" text="You'll get related ideas from Google Autocomplete and People Also Ask, with their metrics." />}

      {result && (
        <section className="space-y-4">
          <DryRunBanner show={result.dry_run} />
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{result.keywords.length} keywords for “{result.seed}”</p>
            <a className="text-sm text-primary hover:underline" href={Platform.exploreCsvUrl(result.seed, result.country, result.language)}>
              Download CSV{result.dry_run ? " (preview)" : ""}
            </a>
          </div>
          <div className="overflow-x-auto rounded-[18px] border bg-card">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="sticky left-0 bg-card px-4 py-3 font-medium">Keyword</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 text-right font-medium">Volume</th>
                  <th className="px-4 py-3 text-right font-medium">KD</th>
                  <th className="px-4 py-3 text-right font-medium">CPC</th>
                  <th className="px-4 py-3 text-right font-medium" title="Search volume × typical click-through rate of the #1 result">Traffic (est.)</th>
                </tr>
              </thead>
              <tbody>
                {result.keywords.map((k) => (
                  <tr key={k.keyword} className="border-b last:border-0">
                    <td className="sticky left-0 bg-card px-4 py-3 font-medium">{k.keyword}</td>
                    <td className="px-4 py-3 text-muted-foreground">{SOURCE[k.source]}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{n(k.search_volume)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{k.difficulty ?? "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{k.cpc != null ? `$${k.cpc.toFixed(2)}` : "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{n(k.traffic_potential_estimate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.clusters.length > 0 && (
            <div className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Clusters</h2>
              <div className="space-y-3">
                {result.clusters.map((group) => (
                  <div key={group[0]} className="flex flex-wrap gap-2">
                    {group.map((k, i) => <span key={k} className={`rounded-full border px-3 py-1 text-xs ${i === 0 ? "font-semibold" : ""}`}>{k}</span>)}
                  </div>
                ))}
              </div>
            </div>
          )}
          {result.notes.length > 0 && <ul className="text-xs text-muted-foreground">{result.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
        </section>
      )}
      <PageGuide {...KEYWORDS_GUIDE} />
    </main>
  );
}
