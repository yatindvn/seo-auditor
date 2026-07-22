"use client";

import React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { HealthScore } from "@/lib/types";

interface IssueChartProps {
  healthScore: HealthScore;
}

export function IssueChart({ healthScore }: IssueChartProps) {
  const data = [
    { name: "Critical", count: healthScore.critical_issues, color: "#EF4444" },
    { name: "Warning", count: healthScore.warning_issues, color: "#F59E0B" },
    { name: "Info", count: healthScore.info_issues, color: "#3B82F6" },
  ];

  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 10, right: 30, left: 20, bottom: 5 }}
        >
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "currentColor", fontSize: 12, fontWeight: 500 }}
          />
          <Tooltip
            cursor={{ fill: "rgba(0,0,0,0.03)" }}
            content={({ active, payload }) => {
              if (active && payload && payload.length) {
                const item = payload[0].payload;
                return (
                  <div className="rounded-xl border border-border bg-popover/90 px-3 py-2 text-xs font-semibold shadow-md backdrop-blur-md">
                    <span style={{ color: item.color }}>{item.name}:</span>{" "}
                    <span className="text-foreground">{item.count} issue(s)</span>
                  </div>
                );
              }
              return null;
            }}
          />
          <Bar dataKey="count" radius={[0, 8, 8, 0]} barSize={24}>
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
