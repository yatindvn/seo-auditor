"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { AuditDiffView } from "@/components/platform/audit-diff";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { PageHeader } from "@/components/platform/page-header";
import { RenderingTable } from "@/components/platform/rendering-table";
import { AccessibilityTable } from "@/components/platform/accessibility-table";
import { RulesSummary } from "@/components/platform/rules-summary";
import { VitalsTable } from "@/components/platform/vitals-table";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export default function SiteAuditPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const audits = useApi(() => Platform.listAudits(projectId, 50), [projectId]);
  const items = audits.data?.items ?? [];
  const [selected, setSelected] = useState<number | null>(null);
  const [against, setAgainst] = useState<number | null>(null);

  useEffect(() => {
    if (items.length >= 1 && selected === null) setSelected(items[0].id);
    if (items.length >= 2 && against === null) setAgainst(items[1].id);
  }, [items, selected, against]);

  const diff = useApi(selected !== null && against !== null ? () => Platform.auditDiff(selected, against) : null, [selected, against]);
  const vitals = useApi(selected !== null ? () => Platform.auditVitals(selected) : null, [selected]);
  const rendering = useApi(selected !== null ? () => Platform.auditRendering(selected) : null, [selected]);
  const accessibility = useApi(selected !== null ? () => Platform.auditAccessibility(selected) : null, [selected]);
  const customRules = useApi(selected !== null ? () => Platform.auditCustomRules(selected) : null, [selected]);

  return (
    <div className="space-y-6">
      <PageHeader title="Site Audit" description="Every audit of this site, and what changed between any two." />
      <AsyncState state={audits} isEmpty={(d) => d.items.length === 0} emptyTitle="No audits yet"
                  emptyAction={<Link href="/" className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">Run an audit</Link>}>
        {() => (
          <>
            <div className="overflow-x-auto rounded-[18px] border bg-card">
              <table className="w-full min-w-[640px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="sticky left-0 bg-card px-4 py-3 font-medium">Finished</th>
                    <th className="px-4 py-3 font-medium">Trigger</th>
                    <th className="px-4 py-3 text-right font-medium">Pages</th>
                    <th className="px-4 py-3 text-right font-medium">Health</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((a, i) => {
                    const prev = items[i + 1];
                    const delta = prev && a.health_score != null && prev.health_score != null
                      ? Math.round((a.health_score - prev.health_score) * 10) / 10 : null;
                    return (
                      <tr key={a.id} className="border-b last:border-0">
                        <td className="sticky left-0 bg-card px-4 py-3">{when(a.finished_at)}</td>
                        <td className="px-4 py-3 capitalize text-muted-foreground">{a.trigger}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{a.page_count}</td>
                        <td className="px-4 py-3 text-right tabular-nums"><span className="mr-2">{a.health_score ?? "—"}</span><DeltaBadge value={delta} /></td>
                        <td className="px-4 py-3 text-right">
                          <Link href={`/dashboard?session=${a.session_id}`} className="text-primary hover:underline">Open report</Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Core Web Vitals</h2>
              <AsyncState state={vitals}>{(v) => <VitalsTable rows={v.items} status={v.status} />}</AsyncState>
            </section>
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">JavaScript rendering</h2>
              <AsyncState state={rendering}>{(r) => <RenderingTable rows={r.items} status={r.status} reason={r.reason} />}</AsyncState>
            </section>
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Accessibility</h2>
              <AsyncState state={accessibility}>{(a) => <AccessibilityTable rows={a.items} status={a.status} reason={a.reason} />}</AsyncState>
            </section>
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Custom rules</h2>
              <AsyncState state={customRules}>{(c) => <RulesSummary items={c.items} />}</AsyncState>
            </section>

            {items.length < 2 ? (
              <EmptyState title="Run a second audit to compare" text="Each new audit of this site can be compared with any earlier one." />
            ) : (
              <section className="space-y-4">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <label className="flex items-center gap-2">Compare
                    <select aria-label="Compare audit" className="h-9 rounded-full border bg-card px-3" value={selected ?? ""}
                            onChange={(e) => setSelected(Number(e.target.value))}>
                      {items.map((a) => <option key={a.id} value={a.id}>{`#${a.id} · ${when(a.finished_at)}`}</option>)}
                    </select>
                  </label>
                  <label className="flex items-center gap-2">compare against
                    <select aria-label="Compare against" className="h-9 rounded-full border bg-card px-3" value={against ?? ""}
                            onChange={(e) => setAgainst(Number(e.target.value))}>
                      {items.filter((a) => a.id !== selected).map((a) => <option key={a.id} value={a.id}>{`#${a.id} · ${when(a.finished_at)}`}</option>)}
                    </select>
                  </label>
                </div>
                <AsyncState state={diff}>{(d) => <AuditDiffView diff={d} />}</AsyncState>
              </section>
            )}
          </>
        )}
      </AsyncState>
    </div>
  );
}
