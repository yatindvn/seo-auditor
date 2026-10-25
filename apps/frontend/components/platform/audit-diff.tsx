import type { AuditDiff, DiffIssue } from "@seo-auditor/shared";

import { getSeverityBadge } from "@/lib/utils";

const ORDER = ["critical", "warning", "info"];

function IssueGroup({ title, issues, total }: { title: string; issues: DiffIssue[]; total: number }) {
  const sorted = [...issues].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity));
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <h3 className="mb-3 font-semibold tracking-tight">{title} <span className="text-muted-foreground">({total})</span></h3>
      {sorted.length === 0 ? <p className="text-sm text-muted-foreground">None.</p> : (
        <ul className="divide-y text-[13px]">
          {sorted.map((i) => {
            const badge = getSeverityBadge(i.severity);
            return (
              <li key={`${i.url}|${i.code}`} className="flex min-w-0 flex-wrap items-center gap-2 py-2">
                <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${badge.className}`}>{badge.label}</span>
                <span className="font-medium">{i.code}</span>
                <span className="min-w-0 break-all text-muted-foreground">{i.url}</span>
              </li>
            );
          })}
        </ul>
      )}
      {total > sorted.length && <p className="mt-2 text-xs text-muted-foreground">Showing {sorted.length} of {total}.</p>}
    </section>
  );
}

export function AuditDiffView({ diff }: { diff: AuditDiff }) {
  const p = diff.pages;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <IssueGroup title="New issues" issues={diff.issues.new} total={diff.issues.new_count} />
        <IssueGroup title="Fixed issues" issues={diff.issues.fixed} total={diff.issues.fixed_count} />
      </div>
      <section className="rounded-[18px] border bg-card p-5 text-[13px]">
        <h3 className="mb-3 font-semibold tracking-tight">Pages</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          <div><p className="mb-1 text-xs text-muted-foreground">Added ({p.added_count})</p>{p.added.map((u) => <p key={u} className="break-all">{u}</p>)}</div>
          <div><p className="mb-1 text-xs text-muted-foreground">Removed ({p.removed_count})</p>{p.removed.map((u) => <p key={u} className="break-all">{u}</p>)}</div>
          <div><p className="mb-1 text-xs text-muted-foreground">Status changed ({p.status_changed_count})</p>
            {p.status_changed.map((s) => <p key={s.url} className="break-all">{s.url} <span className="tabular-nums text-muted-foreground">{s.old_status ?? "—"} → {s.new_status ?? "—"}</span></p>)}</div>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{diff.issues.persisting_count} issues unchanged.</p>
      </section>
    </div>
  );
}
