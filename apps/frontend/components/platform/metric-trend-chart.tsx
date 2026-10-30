"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { SERIES_LIGHT } from "@/lib/platform-charts";

export interface TrendPoint { label: string; value: number | null; note?: string }

export function MetricTrendChart({ title, data }: { title: string; data: TrendPoint[] }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        <button type="button" onClick={() => setAsTable((v) => !v)} className="rounded-full border px-3 py-1 text-xs active:scale-95">
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-[13px]">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Date</th><th className="py-1">{title}</th><th className="py-1" /></tr></thead>
            <tbody>{data.map((d, i) => (
              <tr key={`${d.label}-${i}`}><td className="py-1">{d.label}</td><td className="py-1 tabular-nums">{d.value ?? "—"}</td>
                <td className="py-1 text-xs text-muted-foreground">{d.note ?? ""}</td></tr>))}</tbody>
          </table>
        </div>
      ) : (
        <div className="h-48 w-full" role="img" aria-label={`${title} over time`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Line type="monotone" dataKey="value" name={title} stroke={SERIES_LIGHT[0]} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
