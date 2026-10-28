import type { RuleSummary } from "@seo-auditor/shared";

import { SeverityPill } from "@/components/platform/severity-pill";

export function RulesSummary({ items }: { items: RuleSummary[] }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No custom rules ran in this audit. Add rules in the Custom Rules tab.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b"><th className="py-2 pr-4 font-medium">Rule</th><th className="py-2 pr-4 font-medium">Severity</th>
            <th className="py-2 pr-4 font-medium">Failed / checked</th><th className="py-2 font-medium">Examples</th></tr>
        </thead>
        <tbody className="divide-y">
          {items.map((s) => (
            <tr key={s.rule_id} className="align-top">
              <td className="py-2 pr-4"><p className="font-medium">{s.name}</p><p className="text-muted-foreground">{s.description}</p></td>
              <td className="py-2 pr-4"><SeverityPill severity={s.severity} /></td>
              <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{s.pages_failed} / {s.pages_checked}</td>
              <td className="py-2"><ul className="space-y-0.5">{s.example_urls.slice(0, 3).map((u) => <li key={u} className="break-all">{u}</li>)}</ul></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
