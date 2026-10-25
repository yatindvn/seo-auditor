"use client";

import Link from "next/link";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { HealthTrendChart } from "@/components/platform/health-trend-chart";
import { KpiTile } from "@/components/platform/kpi-tile";
import { averagePosition, biggestMoves } from "@/lib/platform-charts";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export default function OverviewPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const audits = useApi(() => Platform.listAudits(projectId, 50), [projectId]);
  const keywords = useApi(() => Platform.listKeywords(projectId), [projectId]);
  const items = audits.data?.items ?? [];
  const [latest, previous] = items;
  const diff = useApi(latest && previous ? () => Platform.auditDiff(latest.id) : null, [latest?.id, previous?.id]);

  const kwItems = keywords.data?.items ?? [];
  const avg = averagePosition(kwItems);
  const moves = biggestMoves(kwItems, 5);
  const healthDelta = latest?.health_score != null && previous?.health_score != null
    ? Math.round((latest.health_score - previous.health_score) * 10) / 10 : null;

  return (
    <AsyncState
      state={audits}
      isEmpty={(d) => d.items.length === 0}
      emptyTitle="No audits yet"
      emptyText="Audit this site to see its health, history and issues here."
      emptyAction={<Link href="/" className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">Run an audit</Link>}
    >
      {() => (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiTile label="Health" value={latest.health_score ?? "—"} delta={<DeltaBadge value={healthDelta} />} />
            <KpiTile label="Tracked keywords" value={kwItems.length} hint={kwItems.length ? undefined : "Add some in Rank Tracker"} />
            <KpiTile label="Avg. position" value={avg ?? "—"} hint="across ranked keywords" />
            <KpiTile label="Pages in last audit" value={latest.page_count} />
          </div>

          <section className="rounded-[18px] border bg-card p-5">
            <h2 className="mb-4 font-semibold tracking-tight">Health over time</h2>
            <HealthTrendChart audits={items} />
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Latest audit vs previous</h2>
              {!previous ? (
                <EmptyState title="Run a second audit to compare" />
              ) : (
                <AsyncState state={diff}>
                  {(d) => (
                    <div className="space-y-3">
                      <div className="flex gap-6 text-sm">
                        <span className="font-semibold text-rose-700 dark:text-rose-400">{d.issues.new_count} new</span>
                        <span className="font-semibold text-emerald-700 dark:text-emerald-400">{d.issues.fixed_count} fixed</span>
                        <span className="text-muted-foreground">{d.issues.persisting_count} unchanged</span>
                      </div>
                      <Link href={`/projects/${projectId}/audits`} className="text-sm text-primary hover:underline">See the full comparison</Link>
                    </div>
                  )}
                </AsyncState>
              )}
            </section>

            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Biggest rank moves</h2>
              {moves.length === 0 ? (
                <p className="text-sm text-muted-foreground">No rank changes yet.</p>
              ) : (
                <ul className="divide-y text-sm">
                  {moves.map((k) => (
                    <li key={k.id} className="flex items-center justify-between py-2">
                      <span className="truncate">{k.phrase}</span>
                      <span className="flex items-center gap-2 tabular-nums">
                        {k.latest?.position ?? "—"} <DeltaBadge value={k.change != null ? -k.change : null} lowerIsBetter />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </AsyncState>
  );
}
