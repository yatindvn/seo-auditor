"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ContentResult, ContentSummary } from "@seo-auditor/shared";

import { ChartFrame } from "@/components/platform/chart-frame";
import { num } from "@/lib/content";
import { SERIES_LIGHT } from "@/lib/platform-charts";

const axis = { fontSize: 12, fill: "hsl(var(--muted-foreground))" };
const tooltip = { borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 };

export function WordsChart({ results }: { results: ContentResult[] }) {
  const [asTable, setAsTable] = useState(false);
  const data = results.filter((r) => r.word_count != null).map((r) => ({ label: `#${r.position}`, words: r.word_count as number }));
  return (
    <ChartFrame title="Words per result" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Position</th><th className="py-1">Words</th></tr></thead>
          <tbody>{data.map((d) => <tr key={d.label}><td className="py-1">{d.label}</td><td className="py-1 tabular-nums">{num(d.words)}</td></tr>)}</tbody></table>
      ) : (
        <div className="h-56 w-full" role="img" aria-label="Word count per result">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} />
              <YAxis tick={axis} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltip} />
              <Bar dataKey="words" name="Words" fill={SERIES_LIGHT[0]} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartFrame>
  );
}

export function SchemaChart({ summary }: { summary: ContentSummary }) {
  const [asTable, setAsTable] = useState(false);
  const data = Object.entries(summary.schema_counts).map(([type, count]) => ({ type, count }));
  return (
    <ChartFrame title="Schema types used" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {data.length === 0 ? <p className="text-sm text-muted-foreground">None of the fetched results use JSON-LD.</p> : asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Type</th><th className="py-1">Results</th></tr></thead>
          <tbody>{data.map((d) => <tr key={d.type}><td className="py-1">{d.type}</td><td className="py-1 tabular-nums">{d.count}</td></tr>)}</tbody></table>
      ) : (
        <div className="w-full" style={{ height: Math.max(120, data.length * 36) }} role="img" aria-label="Schema types across results">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
              <XAxis type="number" allowDecimals={false} tick={axis} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="type" width={120} tick={axis} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltip} />
              <Bar dataKey="count" name="Results" fill={SERIES_LIGHT[1]} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartFrame>
  );
}
