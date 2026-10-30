"use client";

import { useState } from "react";

import { AsyncState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { GscTable } from "@/components/platform/gsc-table";
import { GscTrendChart } from "@/components/platform/gsc-trend-chart";
import { KpiTile } from "@/components/platform/kpi-tile";
import { PageHeader } from "@/components/platform/page-header";
import { change, formatCount, formatCtr, formatPosition, trendData } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function SearchConsolePage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const overview = useApi(() => Platform.gscOverview(projectId), [projectId]);
  const sites = useApi(overview.data?.configured ? () => Platform.gscSites() : null, [overview.data?.configured]);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const sync = async () => {
    setSyncing(true); setSyncMessage(null);
    try {
      const r = await Platform.gscSync(projectId);
      setSyncMessage(r.status === "synced" ? `Synced ${r.days} days, ${r.pages} pages, ${r.queries} queries.`
        : r.status === "no_access" ? `No access yet: add ${r.client_email} as a user on this site's Search Console property.`
        : `Sync failed: ${r.message}`);
      overview.reload();
    } catch (e) {
      setSyncMessage(e instanceof ApiError ? e.detail : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const pickProperty = async (value: string) => {
    await Platform.updateProject(projectId, { gsc_property: value });
    overview.reload();
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Search Console" description="How Google sees this site: clicks, impressions and positions, from Google Search Console." />
      <AsyncState state={overview}>
        {(o) => !o.configured ? (
          <section className="space-y-2 rounded-[18px] border bg-card p-5 text-sm">
            <h2 className="font-semibold tracking-tight">Connect Search Console</h2>
            <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
              <li>In Google Cloud, create a service account and enable the &ldquo;Google Search Console API&rdquo;.</li>
              <li>Create a JSON key for it and put the file on the backend server.</li>
              <li>Set <code className="rounded bg-muted px-1">GSC_SERVICE_ACCOUNT_FILE</code> to that file&rsquo;s path and restart the backend.</li>
              <li>In Search Console → Settings → Users and permissions, add the service account&rsquo;s email as a user.</li>
            </ol>
          </section>
        ) : (
          <div className="space-y-6">
            <DryRunBanner show={o.dry_run} message="Preview data. Search Console is in dry-run mode, so these numbers are made up." />
            <section className="flex flex-wrap items-end gap-4 rounded-[18px] border bg-card p-5 text-sm">
              <label className="space-y-1 text-xs font-medium text-muted-foreground">Property
                <select aria-label="Property" className="block h-9 min-w-[220px] rounded-lg border bg-background px-3 text-sm"
                        value={o.property ?? ""} onChange={(e) => pickProperty(e.target.value)}>
                  <option value="">{o.property ? "" : "Choose…"}</option>
                  {(sites.data?.sites ?? []).map((s) => <option key={s.site_url} value={s.site_url}>{s.site_url}</option>)}
                  {o.property && !(sites.data?.sites ?? []).some((s) => s.site_url === o.property) && <option value={o.property}>{o.property}</option>}
                </select>
              </label>
              <div className="text-xs text-muted-foreground">Last sync: {o.last_sync_at ? new Date(o.last_sync_at).toLocaleString() : "never"}</div>
              <button type="button" onClick={sync} disabled={syncing} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
                {syncing ? "Syncing…" : "Sync now"}
              </button>
              {!o.property && <p className="w-full text-muted-foreground">Add <strong>{o.client_email}</strong> as a user on this site&apos;s Search Console property, then pick it here or sync.</p>}
              {syncMessage && <p className="w-full text-muted-foreground">{syncMessage}</p>}
            </section>
            {o.kpis && (
              <>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <KpiTile label="Clicks (28 days)" value={formatCount(o.kpis.clicks)} delta={<DeltaBadge value={change(o.kpis.clicks, o.previous_kpis?.clicks)} />} />
                  <KpiTile label="Impressions" value={formatCount(o.kpis.impressions)} delta={<DeltaBadge value={change(o.kpis.impressions, o.previous_kpis?.impressions)} />} />
                  <KpiTile label="CTR" value={formatCtr(o.kpis.ctr)} />
                  <KpiTile label="Avg. position" value={formatPosition(o.kpis.position)}
                           delta={<DeltaBadge value={change(o.kpis.position, o.previous_kpis?.position, 1)} lowerIsBetter />} />
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  <GscTrendChart title="Clicks" data={trendData(o.daily)} dataKey="clicks" />
                  <GscTrendChart title="Impressions" data={trendData(o.daily)} dataKey="impressions" />
                </div>
              </>
            )}
            <div className="grid gap-4 xl:grid-cols-2">
              <GscTable projectId={projectId} kind="pages" />
              <GscTable projectId={projectId} kind="queries" />
            </div>
          </div>
        )}
      </AsyncState>
    </div>
  );
}
