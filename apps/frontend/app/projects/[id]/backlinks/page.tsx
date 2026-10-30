"use client";

import { useState } from "react";

import { AsyncState } from "@/components/platform/async-state";
import { LinksTable, RefDomainsTable } from "@/components/platform/backlink-tables";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { KpiTile } from "@/components/platform/kpi-tile";
import { LinkGap } from "@/components/platform/link-gap";
import { MetricTrendChart } from "@/components/platform/metric-trend-chart";
import { PageHeader } from "@/components/platform/page-header";
import { change, formatCount } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function BacklinksPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const overview = useApi(() => Platform.backlinksOverview(projectId), [projectId]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    setBusy(true); setMessage(null);
    try {
      const r = await Platform.refreshBacklinks(projectId);
      setMessage(r.status === "refreshed" ? `Refreshed${r.history_months ? `, with ${r.history_months} months of history` : ""}.` : r.message ?? "Refresh failed");
      overview.reload();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.detail : "Refresh failed");
    } finally {
      setBusy(false);
    }
  };

  const toggleWeekly = async (on: boolean) => {
    await Platform.updateProject(projectId, { backlink_schedule: on ? "weekly" : null });
    overview.reload();
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Backlinks" description="Who links to this site, how that's changing, and who links to your competitors instead. Data from DataForSEO." />
      <AsyncState state={overview}>
        {(o) => {
          const l = o.latest, p = o.previous;
          const label = (d: string, source: string) => ({ label: d, note: source === "history" ? "from DataForSEO history" : undefined });
          return (
            <div className="space-y-6">
              <DryRunBanner show={o.dry_run_provider || !!l?.dry_run} message="Preview data. DataForSEO is not live, so these backlink numbers are made up." />
              <section className="flex flex-wrap items-center gap-4 rounded-[18px] border bg-card p-5 text-sm">
                <button type="button" onClick={refresh} disabled={busy} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
                  {busy ? "Refreshing…" : "Refresh now"}
                </button>
                <span className="text-xs text-muted-foreground">about $0.25 per refresh · last: {o.last_refresh_at ? new Date(o.last_refresh_at).toLocaleString() : "never"}</span>
                <label className="ml-auto flex items-center gap-2">
                  <button type="button" role="switch" aria-checked={o.schedule === "weekly"} aria-label="Weekly refresh" onClick={() => toggleWeekly(o.schedule !== "weekly")}
                          className={`relative h-6 w-11 rounded-full transition-colors ${o.schedule === "weekly" ? "bg-primary" : "bg-muted"}`}>
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-background transition-all ${o.schedule === "weekly" ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                  Weekly refresh
                </label>
                {message && <p className="w-full text-muted-foreground">{message}</p>}
              </section>
              {!l ? (
                <p className="rounded-[18px] border bg-card p-5 text-sm text-muted-foreground">No backlink data yet. Press <strong>Refresh now</strong>.</p>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <KpiTile label="Authority" value={l.authority ?? "—"} hint="DataForSEO rank, 0–1000" delta={<DeltaBadge value={change(l.authority, p?.authority)} />} />
                    <KpiTile label="Referring domains" value={formatCount(l.referring_domains)} delta={<DeltaBadge value={change(l.referring_domains, p?.referring_domains)} />} />
                    <KpiTile label="Backlinks" value={formatCount(l.backlinks)} delta={<DeltaBadge value={change(l.backlinks, p?.backlinks)} />} />
                    <KpiTile label="Broken backlinks" value={formatCount(l.broken_backlinks)} delta={<DeltaBadge value={change(l.broken_backlinks, p?.broken_backlinks)} lowerIsBetter />} />
                  </div>
                  <div className="grid gap-4 lg:grid-cols-3">
                    <MetricTrendChart title="Referring domains" data={o.history.map((h) => ({ ...label(h.date, h.source), value: h.referring_domains }))} />
                    <MetricTrendChart title="Backlinks" data={o.history.map((h) => ({ ...label(h.date, h.source), value: h.backlinks }))} />
                    <MetricTrendChart title="Authority" data={o.history.map((h) => ({ ...label(h.date, h.source), value: h.authority }))} />
                  </div>
                  <div className="grid gap-4 xl:grid-cols-2">
                    <RefDomainsTable projectId={projectId} />
                    <LinksTable projectId={projectId} kind="broken" />
                    <LinksTable projectId={projectId} kind="new" />
                    <LinksTable projectId={projectId} kind="lost" />
                  </div>
                </>
              )}
              <LinkGap projectId={projectId} />
            </div>
          );
        }}
      </AsyncState>
    </div>
  );
}
