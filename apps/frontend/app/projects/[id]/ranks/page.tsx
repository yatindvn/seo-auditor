"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import type { RankPreview, TrackedKeyword } from "@seo-auditor/shared";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { PageHeader } from "@/components/platform/page-header";
import { RankHistoryChart } from "@/components/platform/rank-history-chart";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function RanksPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const keywords = useApi(() => Platform.listKeywords(projectId), [projectId]);
  const competitors = useApi(() => Platform.listCompetitors(projectId), [projectId]);
  const projects = useApi(() => Platform.listProjects(), []);
  const project = projects.data?.items.find((p) => p.id === projectId);

  const [text, setText] = useState("");
  const [country, setCountry] = useState("US");
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [competitorInput, setCompetitorInput] = useState("");
  const [selected, setSelected] = useState<TrackedKeyword | null>(null);
  const [preview, setPreview] = useState<RankPreview | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const history = useApi(selected ? () => Platform.keywordHistory(selected.id, 90) : null, [selected?.id]);
  const domains = (competitors.data?.items ?? []).map((c) => c.domain);

  const act = async (fn: () => Promise<unknown>, after?: () => void) => {
    setMessage(null);
    try { await fn(); after?.(); } catch (e) { setMessage(e instanceof ApiError ? e.detail : String(e)); }
  };

  const addKeywords = () => {
    const phrases = text.split("\n").map((p) => p.trim()).filter(Boolean);
    if (!phrases.length) return;
    act(() => Platform.addKeywords(projectId, phrases.map((phrase) => ({ phrase, country, device }))),
        () => { setText(""); keywords.reload(); });
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Rank Tracker" description="Daily Google positions for this site and its competitors."
        actions={<Button variant="outline" className="rounded-full active:scale-95"
                         onClick={() => act(async () => setPreview(await Platform.previewRankCheck(projectId)))}>Preview check</Button>} />
      {message && <p role="status" className="rounded-[18px] border px-4 py-3 text-sm">{message}</p>}

      <section className="grid gap-4 rounded-[18px] border bg-card p-5 lg:grid-cols-[2fr_1fr_1fr_auto] lg:items-end">
        <label className="space-y-1 text-sm">
          <span className="text-xs text-muted-foreground">Keywords to track (one per line)</span>
          <textarea aria-label="Keywords to track" value={text} onChange={(e) => setText(e.target.value)} rows={2}
                    className="w-full rounded-xl border bg-background px-3 py-2 text-sm" />
        </label>
        <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
          <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="rounded-full" />
        </label>
        <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Device</span>
          <select aria-label="Device" value={device} onChange={(e) => setDevice(e.target.value as "desktop" | "mobile")}
                  className="h-10 w-full rounded-full border bg-background px-3 text-sm">
            <option value="desktop">Desktop</option><option value="mobile">Mobile</option>
          </select>
        </label>
        <Button className="rounded-full active:scale-95" onClick={addKeywords}>Add keywords</Button>
      </section>

      <AsyncState state={keywords} isEmpty={(d) => d.items.length === 0} emptyTitle="No keywords tracked yet"
                  emptyText="Add a few keywords above. They're checked daily once a live rank provider is configured.">
        {(d) => (
          <div className="overflow-x-auto rounded-[18px] border bg-card">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="sticky left-0 bg-card px-4 py-3 font-medium">Keyword</th>
                  <th className="px-4 py-3 font-medium">Where</th>
                  <th className="px-4 py-3 text-right font-medium">Position</th>
                  <th className="px-4 py-3 font-medium">Ranking URL</th>
                  <th className="px-4 py-3 font-medium">Tracking</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {d.items.map((k) => (
                  <tr key={k.id} className={`border-b last:border-0 ${selected?.id === k.id ? "bg-muted/40" : ""}`}>
                    <td className="sticky left-0 bg-card px-4 py-3">
                      <button type="button" className="text-left font-medium hover:text-primary" onClick={() => setSelected(k)}>{k.phrase}</button>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{k.country}/{k.device}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      <span className="mr-2">{k.latest?.position ?? (k.latest ? "—" : "not checked")}</span>
                      <DeltaBadge value={k.change != null ? -k.change : null} lowerIsBetter />
                    </td>
                    <td className="max-w-[240px] truncate px-4 py-3 text-muted-foreground">{k.latest?.ranking_url ?? ""}</td>
                    <td className="px-4 py-3">
                      <input type="checkbox" aria-label={`Track ${k.phrase}`} checked={k.enabled}
                             onChange={(e) => act(() => Platform.setKeywordEnabled(k.id, e.target.checked), keywords.reload)} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button type="button" aria-label={`Delete ${k.phrase}`} className="inline-flex h-11 w-11 items-center justify-center rounded-full hover:bg-muted"
                              onClick={() => act(() => Platform.deleteKeyword(k.id), keywords.reload)}><Trash2 className="h-4 w-4" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncState>

      {selected && (
        <section className="rounded-[18px] border bg-card p-5">
          <h2 className="mb-2 font-semibold tracking-tight">“{selected.phrase}” over the last 90 days</h2>
          <AsyncState state={history} isEmpty={(h) => h.items.length === 0} emptyTitle="No checks yet">
            {(h) => <RankHistoryChart history={h.items} competitors={domains} myDomain={project?.domain ?? "this site"} />}
          </AsyncState>
        </section>
      )}

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-[18px] border bg-card p-5">
          <h2 className="mb-3 font-semibold tracking-tight">Competitors</h2>
          <div className="flex gap-2">
            <Input aria-label="Competitor domain" placeholder="rival.com" value={competitorInput}
                   onChange={(e) => setCompetitorInput(e.target.value)} className="rounded-full" />
            <Button className="rounded-full active:scale-95"
                    onClick={() => act(() => Platform.addCompetitor(projectId, competitorInput), () => { setCompetitorInput(""); competitors.reload(); })}>Add</Button>
          </div>
          <ul className="mt-3 divide-y text-sm">
            {(competitors.data?.items ?? []).map((c) => (
              <li key={c.id} className="flex items-center justify-between py-2">{c.domain}
                <button type="button" aria-label={`Remove ${c.domain}`} className="text-muted-foreground hover:text-foreground"
                        onClick={() => act(() => Platform.deleteCompetitor(projectId, c.id), competitors.reload)}><Trash2 className="h-4 w-4" /></button>
              </li>
            ))}
          </ul>
        </div>
        <AlertSettingsForm projectId={projectId} initial={project?.alert_settings ?? {}} onError={setMessage} />
      </section>

      {preview && (
        <section className="space-y-3 rounded-[18px] border bg-card p-5">
          <h2 className="font-semibold tracking-tight">Preview</h2>
          <DryRunBanner show={preview.dry_run} />
          <ul className="divide-y text-sm">
            {preview.results.map((r) => <li key={r.phrase} className="flex justify-between py-2"><span>{r.phrase}</span><span className="tabular-nums">{r.position ?? "not ranked"}</span></li>)}
          </ul>
        </section>
      )}
    </div>
  );
}

function AlertSettingsForm({ projectId, initial, onError }: {
  projectId: number; initial: { drop_threshold?: number; top10_alerts?: boolean; gain_threshold?: number | null }; onError: (m: string) => void;
}) {
  const [drop, setDrop] = useState(String(initial.drop_threshold ?? 3));
  const [top10, setTop10] = useState(initial.top10_alerts ?? true);
  const [gain, setGain] = useState(initial.gain_threshold != null ? String(initial.gain_threshold) : "");
  const [saved, setSaved] = useState(false);
  const save = async () => {
    setSaved(false);
    try {
      await Platform.updateProject(projectId, { alert_settings: {
        drop_threshold: Number(drop) || 3, top10_alerts: top10, gain_threshold: gain ? Number(gain) : null } });
      setSaved(true);
    } catch (e) { onError(e instanceof ApiError ? e.detail : String(e)); }
  };
  return (
    <div className="space-y-3 rounded-[18px] border bg-card p-5 text-sm">
      <h2 className="font-semibold tracking-tight">Alerts</h2>
      <label className="flex items-center justify-between gap-3">Alert when a keyword drops by at least
        <Input aria-label="Drop threshold" type="number" min={1} value={drop} onChange={(e) => setDrop(e.target.value)} className="w-20 rounded-full" />
      </label>
      <label className="flex items-center justify-between gap-3">Alert when a keyword leaves the top 10
        <input type="checkbox" aria-label="Top 10 alerts" checked={top10} onChange={(e) => setTop10(e.target.checked)} />
      </label>
      <label className="flex items-center justify-between gap-3">Also alert on gains of at least (blank = off)
        <Input aria-label="Gain threshold" type="number" min={1} value={gain} onChange={(e) => setGain(e.target.value)} className="w-20 rounded-full" />
      </label>
      <div className="flex items-center gap-3">
        <Button variant="outline" className="rounded-full active:scale-95" onClick={save}>Save alerts</Button>
        {saved && <span role="status" className="text-xs text-muted-foreground">Saved</span>}
      </div>
    </div>
  );
}
