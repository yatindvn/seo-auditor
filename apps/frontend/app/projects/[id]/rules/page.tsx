"use client";

import { useState } from "react";
import type { CustomRule } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { PageHeader } from "@/components/platform/page-header";
import { RuleForm } from "@/components/platform/rule-form";
import { SeverityPill } from "@/components/platform/severity-pill";
import { EXAMPLE_RULE } from "@/lib/rules";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export default function RulesPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const rules = useApi(() => Platform.listRules(projectId), [projectId]);
  const latest = useApi(async () => {
    const audits = await Platform.listAudits(projectId, 1);
    return audits.items.length ? Platform.auditCustomRules(audits.items[0].id) : { audit_id: 0, items: [] };
  }, [projectId]);
  const [editing, setEditing] = useState<CustomRule | "new" | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const lastRun = new Map((latest.data?.items ?? []).map((s) => [s.rule_id, s]));

  const saved = () => { setEditing(null); rules.reload(); };
  const toggle = async (rule: CustomRule) => { await Platform.updateRule(rule.id, { enabled: !rule.enabled }); rules.reload(); };
  const remove = async (rule: CustomRule) => { await Platform.deleteRule(rule.id); setConfirming(null); rules.reload(); };
  const addExample = async () => { await Platform.createRule(projectId, EXAMPLE_RULE); rules.reload(); };

  return (
    <div className="space-y-6">
      <PageHeader title="Custom Rules" description="Your own checks, run on every page of every audit of this site."
                  actions={editing === null ? <button type="button" onClick={() => setEditing("new")} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">New rule</button> : undefined} />
      {editing !== null && (
        <RuleForm projectId={projectId} initial={editing === "new" ? undefined : editing} onSaved={saved} onCancel={() => setEditing(null)} />
      )}
      <AsyncState state={rules} isEmpty={(d) => d.items.length === 0} emptyTitle="No rules yet"
                  emptyText="Rules check every page for things that matter to this site, like a brand in the title or structured data on product pages."
                  emptyAction={<button type="button" onClick={addExample} className="rounded-full border px-4 py-2 text-sm active:scale-95">Add an example rule</button>}>
        {(d) => (
          <ul className="divide-y rounded-[18px] border bg-card">
            {d.items.map((rule) => {
              const run = lastRun.get(rule.id);
              return (
                <li key={rule.id} className="flex flex-wrap items-start gap-3 p-4">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{rule.name}</span>
                      <SeverityPill severity={rule.severity} />
                      {rule.url_pattern && <span className="rounded border px-1.5 font-mono text-[11px] text-muted-foreground">{rule.url_pattern}</span>}
                    </div>
                    <p className="break-all text-sm text-muted-foreground">{rule.description}</p>
                    {run && <p className="text-xs text-muted-foreground">Last audit: failed on {run.pages_failed} of {run.pages_checked} pages</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <button type="button" role="switch" aria-checked={rule.enabled} aria-label={`Enable ${rule.name}`} onClick={() => toggle(rule)}
                            className={`relative h-6 w-11 rounded-full transition-colors ${rule.enabled ? "bg-primary" : "bg-muted"}`}>
                      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-background transition-all ${rule.enabled ? "left-[22px]" : "left-0.5"}`} />
                    </button>
                    <button type="button" onClick={() => setEditing(rule)} className="rounded-full border px-3 py-1 text-xs active:scale-95">Edit</button>
                    {confirming === rule.id ? (
                      <button type="button" onClick={() => remove(rule)} className="rounded-full border border-rose-300 px-3 py-1 text-xs text-rose-700 active:scale-95 dark:text-rose-400">Confirm delete</button>
                    ) : (
                      <button type="button" aria-label={`Delete ${rule.name}`} onClick={() => setConfirming(rule.id)} className="rounded-full border px-3 py-1 text-xs active:scale-95">Delete</button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </AsyncState>
    </div>
  );
}
