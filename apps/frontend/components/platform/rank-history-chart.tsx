"use client";

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RankCheckView } from "@seo-auditor/shared";

import { Button } from "@/components/ui/button";
import { rankSeries, SERIES_LIGHT } from "@/lib/platform-charts";

/** Position over time: #1 at the top (reversed axis), one line for the
 *  project and one per competitor in fixed slot order. A skipped check is a
 *  gap. Light-mode slots 3-5 are below 3:1 contrast, so the chart always has
 *  a legend and a table view (dataviz rule). */
export function RankHistoryChart({ history, competitors, myDomain }: {
  history: RankCheckView[]; competitors: string[]; myDomain: string;
}) {
  const [asTable, setAsTable] = useState(false);
  const { points, maxPosition } = rankSeries(history, competitors.slice(0, 5));
  const series = [{ key: "me", name: myDomain }, ...competitors.slice(0, 5).map((d) => ({ key: d, name: d }))];

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" className="rounded-full" onClick={() => setAsTable((t) => !t)}>
          {asTable ? "Show as chart" : "Show as table"}
        </Button>
      </div>
      {asTable ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-[13px]">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b"><th className="px-3 py-2 font-medium">Date</th>
                {series.map((s) => <th key={s.key} className="px-3 py-2 text-right font-medium">{s.name}</th>)}</tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="px-3 py-2">{p.label}</td>
                  {series.map((s) => <td key={s.key} className="px-3 py-2 text-right tabular-nums">{(p[s.key] as number | null) ?? "—"}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-60 w-full sm:h-80" role="img" aria-label={`Ranking history for ${myDomain} and competitors`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 24, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <YAxis reversed domain={[1, maxPosition]} allowDecimals={false}
                     tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              {/* itemSorter={null}: keep series order, so your own site is listed first */}
              <Legend itemSorter={null} wrapperStyle={{ fontSize: 12 }} />
              {series.map((s, i) => (
                <Line key={s.key} dataKey={s.key} name={s.name} stroke={SERIES_LIGHT[i]} strokeWidth={2}
                      dot={{ r: 4 }} activeDot={{ r: 5 }} connectNulls={false} type="monotone" />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
