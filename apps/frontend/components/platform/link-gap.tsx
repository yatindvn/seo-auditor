"use client";

import { useEffect, useState } from "react";
import type { LinkGapResult } from "@seo-auditor/shared";

import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export function LinkGap({ projectId }: { projectId: number }) {
  const competitors = useApi(() => Platform.listCompetitors(projectId), [projectId]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<LinkGapResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  useEffect(() => { setChosen((competitors.data?.items ?? []).slice(0, 5).map((c) => c.domain)); }, [competitors.data]);

  const run = async () => {
    setRunning(true); setError(null);
    try { setResult(await Platform.backlinkGap(projectId, chosen)); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Link gap failed"); }
    finally { setRunning(false); }
  };

  const all = competitors.data?.items ?? [];
  return (
    <section className="min-w-0 space-y-3 rounded-[18px] border bg-card p-5">
      <h2 className="font-semibold tracking-tight">Link gap</h2>
      <p className="text-sm text-muted-foreground">Domains that link to your competitors but not to you: outreach targets.</p>
      {all.length === 0 ? <p className="text-sm text-muted-foreground">Add competitors in the Rank Tracker tab first.</p> : (
        <div className="flex flex-wrap items-center gap-3">
          {all.map((c) => (
            <label key={c.domain} className="flex items-center gap-2 rounded-full border px-3 py-1 text-sm">
              <input type="checkbox" aria-label={c.domain} checked={chosen.includes(c.domain)} disabled={!chosen.includes(c.domain) && chosen.length >= 5}
                     onChange={(e) => setChosen((cur) => e.target.checked ? [...cur, c.domain] : cur.filter((d) => d !== c.domain))} />
              {c.domain}
            </label>
          ))}
          <button type="button" onClick={run} disabled={running || chosen.length === 0} aria-label="Run link gap"
                  className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
            {running ? "Running…" : "Run"}
          </button>
          <span className="text-xs text-muted-foreground">about $0.05–0.10 per run</span>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
      {result && (
        <>
          <DryRunBanner show={result.dry_run} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-[13px]">
              <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                <th className="py-2 pr-4 font-medium">Domain</th><th className="py-2 pr-4 font-medium">DataForSEO rank</th>
                <th className="py-2 pr-4 font-medium">Links to</th><th className="py-2 font-medium">Backlinks per competitor</th></tr></thead>
              <tbody className="divide-y">{result.rows.map((r) => (
                <tr key={r.domain} className="align-top">
                  <td className="break-all py-2 pr-4">{r.domain}</td><td className="py-2 pr-4 tabular-nums">{r.rank ?? "—"}</td>
                  <td className="whitespace-nowrap py-2 pr-4">{r.linked_count} of {result.competitors.length}</td>
                  <td className="py-2 text-muted-foreground">{Object.entries(r.backlinks_by_competitor).map(([c, n]) => `${c}: ${n}`).join(", ")}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
