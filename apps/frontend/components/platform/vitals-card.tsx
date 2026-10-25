"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { VitalsMetric } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { RatingPill, VITALS_NOT_CONFIGURED } from "@/components/platform/vitals-table";
import { formatVitalsMetric, SERIES_LIGHT, vitalsScoreTrend } from "@/lib/platform-charts";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

/** The homepage's latest Core Web Vitals and its performance score over time. */
export function VitalsCard({ projectId }: { projectId: number }) {
  const trend = useApi(() => Platform.vitalsTrend(projectId), [projectId]);
  const [asTable, setAsTable] = useState(false);

  return (
    <section className="rounded-[18px] border bg-card p-5">
      <h2 className="mb-1 font-semibold tracking-tight">Core Web Vitals</h2>
      <AsyncState
        state={trend}
        isEmpty={(d) => d.points.length === 0}
        emptyTitle="Core Web Vitals not measured yet"
        emptyText={VITALS_NOT_CONFIGURED.replace("Core Web Vitals not measured. ", "") + " Then run an audit."}
      >
        {(d) => {
          const latest = d.points[d.points.length - 1];
          const responsiveness: VitalsMetric = latest.data_kind === "field" ? "inp_ms" : "tbt_ms";
          const tiles: { metric: VitalsMetric; label: string }[] = [
            { metric: "lcp_ms", label: "LCP" },
            { metric: responsiveness, label: responsiveness === "inp_ms" ? "INP" : "TBT (lab)" },
            { metric: "cls", label: "CLS" },
          ];
          const data = vitalsScoreTrend(d.points);
          return (
            <div className="space-y-4">
              <p className="break-all text-xs text-muted-foreground">
                {d.url} · {latest.data_kind === "field" ? "Field data" : "Lab data"} · {latest.source}
              </p>
              <div className="grid gap-3 sm:grid-cols-3">
                {tiles.map((t) => (
                  <div key={t.metric} className="rounded-xl border p-3">
                    <p className="text-xs text-muted-foreground">{t.label}</p>
                    <p className="text-lg font-semibold tabular-nums tracking-tight">{formatVitalsMetric(t.metric, latest[t.metric])}</p>
                    <RatingPill rating={latest.metric_ratings[t.metric]} />
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">Performance score per audit</p>
                <button type="button" onClick={() => setAsTable((v) => !v)}
                        className="rounded-full border px-3 py-1 text-xs active:scale-95">
                  {asTable ? "Show as chart" : "Show as table"}
                </button>
              </div>
              {asTable ? (
                <table className="w-full text-[13px]">
                  <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Audit</th><th className="py-1">Score</th></tr></thead>
                  <tbody>{data.map((p, i) => <tr key={d.points[i].audit_id}><td className="py-1">{p.label}</td><td className="py-1 tabular-nums">{p.score ?? "—"}</td></tr>)}</tbody>
                </table>
              ) : (
                <div className="h-40 w-full" role="img" aria-label="Performance score over time">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                      <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
                      <Line type="monotone" dataKey="score" name="Performance" stroke={SERIES_LIGHT[0]} strokeWidth={2}
                            dot={{ r: 4 }} activeDot={{ r: 5 }} connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          );
        }}
      </AsyncState>
    </section>
  );
}
