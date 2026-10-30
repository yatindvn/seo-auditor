"use client";

import { FormEvent, useState } from "react";
import type { ContentSearchResult } from "@seo-auditor/shared";

import { EmptyState } from "@/components/platform/async-state";
import { SchemaChart, WordsChart } from "@/components/platform/content-charts";
import { ContentResults } from "@/components/platform/content-results";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { KpiTile } from "@/components/platform/kpi-tile";
import { PageHeader } from "@/components/platform/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ago, num, topSchema } from "@/lib/content";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function ContentPage() {
  const [topic, setTopic] = useState("");
  const [country, setCountry] = useState("US");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ContentSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recent = useApi(() => Platform.contentRecent(), [result?.id]);

  const go = async (fn: () => Promise<ContentSearchResult>) => {
    setRunning(true); setError(null);
    try { setResult(await fn()); } catch (err) { setError(err instanceof ApiError ? err.detail : String(err)); }
    finally { setRunning(false); }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (topic.trim()) go(() => Platform.contentSearch({ topic, country, language: "en" }));
  };

  const fetched = result ? result.results.filter((r) => r.word_count != null).length : 0;
  const schema = result ? topSchema(result.summary) : null;

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title="Content Explorer" description="What the top 10 results for a topic look like: length, headings, schema and backlinks." />
      <form onSubmit={submit} className="space-y-3 rounded-[18px] border bg-card p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <label className="flex-1 space-y-1 text-sm"><span className="text-xs text-muted-foreground">Topic</span>
            <Input aria-label="Topic" placeholder="rare books" value={topic} maxLength={80} onChange={(e) => setTopic(e.target.value)} className="rounded-full" />
          </label>
          <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
            <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="w-20 rounded-full" />
          </label>
          <Button type="submit" className="rounded-full active:scale-95" disabled={running || !topic.trim()}>{running ? "Exploring…" : "Explore"}</Button>
        </div>
        <p className="text-xs text-muted-foreground">{result?.dry_run ? "Dry run: no cost" : "≈ $0.05–0.08 per new search · cached 7 days (free)"}</p>
        {recent.data && recent.data.items.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Recent:</span>
            {recent.data.items.map((r) => (
              <button key={r.id} type="button" onClick={() => go(() => Platform.contentGet(r.id))}
                      className="rounded-full border px-2.5 py-0.5 hover:bg-muted active:scale-95">{r.topic}</button>
            ))}
          </div>
        )}
      </form>

      {error && <div role="alert" className="rounded-[18px] border border-rose-200 bg-rose-50/60 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-400">{error}</div>}
      {!result && !error && <EmptyState title="Enter a topic" text="You'll see the top 10 results analysed with the same checks as a site audit, plus their backlinks." />}

      {result && (
        <div className="space-y-6">
          <DryRunBanner show={result.dry_run} message="Preview data. The SERP or backlink provider isn't live, so these results are made up." />
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <p className="min-w-0 flex-1">Top {result.results.length} for <strong>&ldquo;{result.topic}&rdquo;</strong> · {result.country} · fetched {ago(result.created_at)}{result.cached ? " (cached)" : ""}</p>
            <Button type="button" variant="outline" className="rounded-full active:scale-95" disabled={running}
                    onClick={() => go(() => Platform.contentSearch({ topic: result.topic, country: result.country, language: result.language, refresh: true }))}>Refresh</Button>
            <a href={Platform.contentCsvUrl(result.id)} className="rounded-full border px-4 py-2 text-sm hover:bg-muted">Export CSV</a>
          </div>
          {result.notes.map((n) => <p key={n} className="text-sm text-muted-foreground">{n}</p>)}
          <div className="grid gap-4 sm:grid-cols-3">
            <KpiTile label="Median words" value={num(result.summary.median_words)} hint={`across ${fetched} fetched results`} />
            <KpiTile label="Top schema type" value={schema ? schema.type : "—"} hint={schema ? `used by ${schema.count} of ${fetched} fetched` : "no JSON-LD found"} />
            <KpiTile label="Median referring domains" value={num(result.summary.median_referring_domains)} hint="per ranking URL" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <WordsChart results={result.results} />
            <SchemaChart summary={result.summary} />
          </div>
          <section className="min-w-0 rounded-[18px] border bg-card p-5">
            <h2 className="mb-3 font-semibold tracking-tight">Results</h2>
            <ContentResults results={result.results} />
          </section>
          {result.summary.common_h2_terms.length > 0 && (
            <section className="min-w-0 rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Common H2 terms <span className="text-xs font-normal text-muted-foreground">(pages using each)</span></h2>
              <ul className="flex flex-wrap gap-2 text-[13px]">{result.summary.common_h2_terms.map((t) => (
                <li key={t.term} className="rounded-full border px-3 py-1"><span>{t.term}</span> <span className="tabular-nums text-muted-foreground">{t.count}</span></li>))}</ul>
            </section>
          )}
        </div>
      )}
    </main>
  );
}
