"use client";

import { useState } from "react";
import type { BacklinkKind } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

function Pager({ offset, total, onChange }: { offset: number; total: number; onChange: (o: number) => void }) {
  if (total <= 50) return null;
  return (
    <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
      <button type="button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - 50))} className="rounded-full border px-3 py-1 disabled:opacity-50">Previous</button>
      <span>{offset + 1}–{Math.min(offset + 50, total)} of {total}</span>
      <button type="button" disabled={offset + 50 >= total} onClick={() => onChange(offset + 50)} className="rounded-full border px-3 py-1 disabled:opacity-50">Next</button>
    </div>
  );
}

export function RefDomainsTable({ projectId }: { projectId: number }) {
  const [offset, setOffset] = useState(0);
  const state = useApi(() => Platform.refDomains(projectId, offset), [projectId, offset]);
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <h2 className="mb-3 font-semibold tracking-tight">Top referring domains</h2>
      <AsyncState state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No referring domains yet">
        {(d) => (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                  <th className="py-2 pr-4 font-medium">Domain</th><th className="py-2 pr-4 font-medium">DataForSEO rank</th>
                  <th className="py-2 pr-4 font-medium">Backlinks</th><th className="py-2 font-medium">First seen</th></tr></thead>
                <tbody className="divide-y">{d.items.map((r) => (
                  <tr key={r.domain}><td className="break-all py-2 pr-4">{r.domain}</td><td className="py-2 pr-4 tabular-nums">{r.rank ?? "—"}</td>
                    <td className="py-2 pr-4 tabular-nums">{r.backlinks}</td><td className="py-2 text-muted-foreground">{r.first_seen?.slice(0, 10) ?? "—"}</td></tr>))}</tbody>
              </table>
            </div>
            <Pager offset={offset} total={d.total} onChange={setOffset} />
          </>
        )}
      </AsyncState>
    </section>
  );
}

const TITLES: Record<BacklinkKind, string> = { new: "New links (30 days)", lost: "Lost links (30 days)", broken: "Broken backlinks" };

export function LinksTable({ projectId, kind }: { projectId: number; kind: BacklinkKind }) {
  const [offset, setOffset] = useState(0);
  const state = useApi(() => Platform.backlinkLinks(projectId, kind, offset), [projectId, kind, offset]);
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <h2 className="mb-1 font-semibold tracking-tight">{TITLES[kind]}</h2>
      {kind === "broken" && <p className="mb-3 text-xs text-muted-foreground">Links pointing at pages that error. Redirect this URL to a live page to keep their value.</p>}
      <AsyncState state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="None">
        {(d) => (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                  <th className="py-2 pr-4 font-medium">From</th><th className="py-2 pr-4 font-medium">To</th>
                  <th className="py-2 pr-4 font-medium">Anchor</th><th className="py-2 pr-4 font-medium">Rank</th>
                  <th className="py-2 font-medium">{kind === "broken" ? "Status" : "Follow"}</th></tr></thead>
                <tbody className="divide-y">{d.items.map((l, i) => (
                  <tr key={`${l.url_from}-${i}`} className="align-top">
                    <td className="max-w-[200px] break-all py-2 pr-4">{l.url_from}</td>
                    <td className="max-w-[200px] break-all py-2 pr-4">{l.url_to}{kind === "broken" && <p className="text-xs text-muted-foreground">Redirect this URL to a live page</p>}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{l.anchor || "—"}</td>
                    <td className="py-2 pr-4 tabular-nums">{l.domain_from_rank ?? "—"}</td>
                    <td className="py-2 text-muted-foreground">{kind === "broken" ? (l.crawled_status ?? l.target_status ?? "—") : (l.dofollow ? "follow" : "nofollow")}</td>
                  </tr>))}</tbody>
              </table>
            </div>
            <Pager offset={offset} total={d.total} onChange={setOffset} />
          </>
        )}
      </AsyncState>
    </section>
  );
}
