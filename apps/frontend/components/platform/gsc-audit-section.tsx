import { CheckCircle2, XCircle } from "lucide-react";
import type { AuditGsc } from "@seo-auditor/shared";

import { formatCount, formatPosition } from "@/lib/gsc";

function IndexPill({ verdict }: { verdict: string | null }) {
  if (verdict === "PASS") return <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400"><CheckCircle2 className="h-3 w-3" aria-hidden />Indexed</span>;
  if (!verdict) return <span className="text-muted-foreground">—</span>;
  return <span className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400"><XCircle className="h-3 w-3" aria-hidden />Not indexed</span>;
}

const MESSAGES: Record<string, string> = {
  disabled: "Search Console inspection was turned off for this audit.",
  not_configured: "Search Console isn't connected. Set it up in the project's Search Console tab.",
  no_property: "No Search Console property for this site yet. Pick one in the Search Console tab.",
  error: "Search Console couldn't be reached during this audit.",
};

export function GscAuditSection({ data }: { data: AuditGsc }) {
  if (data.status !== "inspected") return <p className="text-sm text-muted-foreground">{MESSAGES[data.status] ?? MESSAGES.error}</p>;
  return (
    <div className="space-y-5">
      {data.dry_run && <p className="text-xs text-amber-800 dark:text-amber-400">Preview data — Search Console is in dry-run mode.</p>}
      <div>
        <h3 className="mb-2 text-sm font-semibold">Index status</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-[13px]">
            <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
              <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th><th className="py-2 pr-4 font-medium">Google</th>
              <th className="py-2 pr-4 font-medium">Reason</th><th className="py-2 font-medium">Last crawl</th></tr></thead>
            <tbody className="divide-y">
              {data.inspections.map((i) => (
                <tr key={i.url} className="align-top">
                  <td className="sticky left-0 max-w-[140px] break-all bg-card py-2 pr-4 sm:max-w-[300px]">{i.url}</td>
                  <td className="py-2 pr-4">{i.error ? <span className="text-muted-foreground">Couldn&apos;t inspect: {i.error}</span> : <IndexPill verdict={i.verdict} />}</td>
                  <td className="py-2 pr-4 text-muted-foreground">
                    {i.coverage_state ?? "—"}
                    {i.google_canonical && i.user_canonical && i.google_canonical !== i.user_canonical && (
                      <p className="break-all text-xs">Google&apos;s canonical: {i.google_canonical}</p>)}
                  </td>
                  <td className="whitespace-nowrap py-2 text-muted-foreground">{i.last_crawl ? new Date(i.last_crawl).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Crawled pages by clicks <span className="font-normal text-muted-foreground">(28 days)</span></h3>
          {data.pages.length === 0 ? <p className="text-sm text-muted-foreground">No Search Console data for the crawled pages yet.</p> : (
            <ul className="divide-y text-[13px]">{data.pages.slice(0, 20).map((p) => (
              <li key={p.url} className="flex items-start justify-between gap-3 py-1.5">
                <span className="min-w-0 break-all">{p.url}</span>
                <span className="whitespace-nowrap tabular-nums text-muted-foreground">{formatCount(p.clicks)} clicks · pos {formatPosition(p.position)}</span>
              </li>))}</ul>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Pages Google shows that the crawl didn&apos;t reach</h3>
          {data.not_crawled.length === 0 ? <p className="text-sm text-muted-foreground">None. Every page with impressions was crawled.</p> : (
            <ul className="divide-y text-[13px]">{data.not_crawled.slice(0, 20).map((p) => (
              <li key={p.url} className="flex items-start justify-between gap-3 py-1.5">
                <span className="min-w-0 break-all">{p.url}</span>
                <span className="whitespace-nowrap tabular-nums text-muted-foreground">{formatCount(p.impressions)} impr.</span>
              </li>))}</ul>
          )}
        </div>
      </div>
    </div>
  );
}
