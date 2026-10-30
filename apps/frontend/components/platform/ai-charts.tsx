"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AiOverview } from "@seo-auditor/shared";

import { pct } from "@/lib/ai-visibility";
import { SERIES_LIGHT } from "@/lib/platform-charts";

function Frame({ title, asTable, onToggle, children }: { title: string; asTable: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        <button type="button" onClick={onToggle} className="rounded-full border px-3 py-1 text-xs active:scale-95">{asTable ? "Show as chart" : "Show as table"}</button>
      </div>
      {children}
    </section>
  );
}

export function MentionTrend({ trend }: { trend: AiOverview["trend"] }) {
  const [asTable, setAsTable] = useState(false);
  const models = Array.from(new Set(trend.flatMap((t) => Object.keys(t.by_provider))));
  const data = trend.map((t) => ({ label: new Date(t.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    ...Object.fromEntries(models.map((m) => [m, t.by_provider[m] != null ? Math.round((t.by_provider[m] as number) * 100) : null])) }));
  return (
    <Frame title="Mention rate per run" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Run</th>{models.map((m) => <th key={m} className="py-1">{m}</th>)}</tr></thead>
          <tbody>{trend.map((t, i) => <tr key={t.run_id}><td className="py-1">{data[i].label}</td>{models.map((m) => <td key={m} className="py-1 tabular-nums">{pct(t.by_provider[m])}</td>)}</tr>)}</tbody></table>
      ) : (
        <div className="h-56 w-full" role="img" aria-label="Mention rate per run by model">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Legend itemSorter={null} wrapperStyle={{ fontSize: 12 }} />
              {models.map((m, i) => <Line key={m} type="monotone" dataKey={m} stroke={SERIES_LIGHT[i % SERIES_LIGHT.length]} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Frame>
  );
}

export function ShareOfVoice({ share }: { share: AiOverview["share_of_voice"] }) {
  const [asTable, setAsTable] = useState(false);
  const data = share.map((s) => ({ owner: s.owner, value: Math.round(s.rate * 100), isSelf: s.is_self }));
  return (
    <Frame title="Share of voice (latest run)" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Brand</th><th className="py-1">Answers mentioning it</th></tr></thead>
          <tbody>{share.map((s) => <tr key={s.owner}><td className="py-1">{s.owner}</td><td className="py-1 tabular-nums">{pct(s.rate)}{s.is_self ? " (you)" : ""}</td></tr>)}</tbody></table>
      ) : (
        <div className="w-full" style={{ height: Math.max(120, data.length * 36) }} role="img" aria-label="Share of voice by brand">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
              <XAxis type="number" domain={[0, 100]} unit="%" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="owner" width={140} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Bar dataKey="value" name="Mentioned in" radius={[0, 4, 4, 0]}>
                {data.map((d) => <Cell key={d.owner} fill={d.isSelf ? SERIES_LIGHT[0] : "hsl(var(--muted-foreground))"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Frame>
  );
}
