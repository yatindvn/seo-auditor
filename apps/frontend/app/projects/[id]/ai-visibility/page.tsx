"use client";

import { useState } from "react";

import { AiAnswers } from "@/components/platform/ai-answers";
import { MentionTrend, ShareOfVoice } from "@/components/platform/ai-charts";
import { BrandTerms, Prompts } from "@/components/platform/ai-setup";
import { AsyncState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { KpiTile } from "@/components/platform/kpi-tile";
import { PageHeader } from "@/components/platform/page-header";
import { estimate, pct } from "@/lib/ai-visibility";
import { change } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function AiVisibilityPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const overview = useApi(() => Platform.aiOverview(projectId), [projectId]);
  const prompts = useApi(() => Platform.aiPrompts(projectId), [projectId]);
  const brands = useApi(() => Platform.aiBrands(projectId), [projectId]);
  const answers = useApi(() => Platform.aiAnswers(projectId), [projectId, overview.data?.latest?.run_id]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const runNow = async () => {
    setBusy(true); setMessage(null);
    try {
      const r = await Platform.runAi(projectId);
      setMessage(r.status === "ran" ? `Ran ${r.calls} calls${r.errors ? ` (${r.errors} failed)` : ""}.`
        : r.status === "no_prompts" ? "Add a prompt first." : "No AI model is configured.");
      overview.reload();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.detail : "Run failed");
    } finally {
      setBusy(false);
    }
  };

  const toggleWeekly = async (on: boolean) => {
    await Platform.updateProject(projectId, { ai_schedule: on ? "weekly" : null });
    overview.reload();
  };

  return (
    <div className="space-y-6">
      <PageHeader title="AI Visibility" description="Do AI assistants mention and cite this site when people ask? Answers come from each model's own web search." />
      <AsyncState state={overview}>
        {(o) => {
          const configured = o.providers.filter((p) => p.configured);
          const enabledPrompts = (prompts.data?.items ?? []).filter((p) => p.enabled).length;
          const l = o.latest, p = o.previous;
          return (
            <div className="space-y-6">
              <DryRunBanner show={o.dry_run} message="Preview data. No AI keys are set, so these answers are made up." />
              <div className="grid gap-4 xl:grid-cols-2">
                {brands.data && <BrandTerms projectId={projectId} brands={brands.data} onChanged={brands.reload} />}
                {prompts.data && <Prompts projectId={projectId} prompts={prompts.data.items} onChanged={prompts.reload} />}
              </div>
              <section className="flex flex-wrap items-center gap-4 rounded-[18px] border bg-card p-5 text-sm">
                <button type="button" onClick={runNow} disabled={busy} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
                  {busy ? "Running…" : "Run now"}
                </button>
                <span className="text-xs text-muted-foreground">{o.dry_run ? `Dry run: no cost (${enabledPrompts} prompts × ${configured.length} models)`
                  : `${estimate(enabledPrompts, configured.length)}: ${enabledPrompts} prompts × ${configured.length} models × ~$0.03`}</span>
                <div className="flex flex-wrap gap-2">
                  {o.providers.map((pr) => (
                    <span key={pr.name} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                      {pr.name}{pr.configured ? `: ${pr.model}${pr.dry_run ? " (dry run)" : ""}` : `: not configured (${pr.hint})`}
                    </span>
                  ))}
                </div>
                <label className="ml-auto flex items-center gap-2">
                  <button type="button" role="switch" aria-checked={o.schedule === "weekly"} aria-label="Weekly runs" onClick={() => toggleWeekly(o.schedule !== "weekly")}
                          className={`relative h-6 w-11 rounded-full transition-colors ${o.schedule === "weekly" ? "bg-primary" : "bg-muted"}`}>
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-background transition-all ${o.schedule === "weekly" ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                  Weekly
                </label>
                {message && <p className="w-full text-muted-foreground">{message}</p>}
              </section>
              {!l ? (
                <p className="rounded-[18px] border bg-card p-5 text-sm text-muted-foreground">No runs yet. Add prompts and press <strong>Run now</strong>.</p>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <KpiTile label="Mention rate" value={pct(l.mention_rate)} hint="answers that name you"
                             delta={<DeltaBadge value={change(l.mention_rate != null ? l.mention_rate * 100 : null, p?.mention_rate != null ? p.mention_rate * 100 : null)} suffix=" pts" />} />
                    <KpiTile label="Avg. position" value={l.avg_position ?? "—"} hint="among tracked brands, when named"
                             delta={<DeltaBadge value={change(l.avg_position, p?.avg_position, 1)} lowerIsBetter />} />
                    <KpiTile label="Cited rate" value={pct(l.cited_rate)} hint="answers that cite your site"
                             delta={<DeltaBadge value={change(l.cited_rate != null ? l.cited_rate * 100 : null, p?.cited_rate != null ? p.cited_rate * 100 : null)} suffix=" pts" />} />
                  </div>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <MentionTrend trend={o.trend} />
                    <ShareOfVoice share={o.share_of_voice} />
                  </div>
                  <section className="min-w-0 rounded-[18px] border bg-card p-5">
                    <h2 className="mb-3 font-semibold tracking-tight">Top cited domains <span className="text-xs font-normal text-muted-foreground">(latest run)</span></h2>
                    <ul className="divide-y text-[13px]">{o.top_cited.map((c) => (
                      <li key={c.domain} className="flex justify-between gap-3 py-1.5"><span className="min-w-0 break-all">{c.domain}{c.is_self && <strong className="ml-2 text-xs text-primary">you</strong>}</span>
                        <span className="tabular-nums text-muted-foreground">{c.count}</span></li>))}</ul>
                  </section>
                  <section className="min-w-0 rounded-[18px] border bg-card p-5">
                    <h2 className="mb-3 font-semibold tracking-tight">Answers <span className="text-xs font-normal text-muted-foreground">(latest run)</span></h2>
                    <AsyncState state={answers}>{(a) => <AiAnswers items={a.items} />}</AsyncState>
                  </section>
                </>
              )}
            </div>
          );
        }}
      </AsyncState>
    </div>
  );
}
