"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AuditListItem } from "@seo-auditor/shared";

import { healthTrend, SERIES_LIGHT } from "@/lib/platform-charts";

/** One series (the project's health score), so no legend: the card title names it. */
export function HealthTrendChart({ audits }: { audits: AuditListItem[] }) {
  const data = healthTrend(audits);
  return (
    <div className="h-60 w-full sm:h-80" role="img" aria-label="Health score over time">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
          <Line type="monotone" dataKey="score" name="Health" stroke={SERIES_LIGHT[0]} strokeWidth={2}
                dot={{ r: 4 }} activeDot={{ r: 5 }} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
