"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Link2, Activity } from "lucide-react";
import { PageItem, ExecutiveSummary } from "@/lib/types";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis } from "recharts";

interface LinkAnalysisPanelProps {
  pages: PageItem[];
  es: ExecutiveSummary;
}

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

export function LinkAnalysisPanel({ pages, es }: LinkAnalysisPanelProps) {
  let totalInternal = 0;
  let totalExternal = 0;
  
  pages.forEach(p => {
    totalInternal += p.internal_links_count || 0;
    totalExternal += p.external_links_count || 0;
  });

  const linkData = [
    { name: "Internal", value: totalInternal },
    { name: "External", value: totalExternal },
  ];

  const statusData = Object.entries(es.status_code_breakdown).map(([status, count]) => ({
    status,
    count
  }));

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Link2 className="h-4 w-4 text-muted-foreground" />
            Link Distribution
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center">
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={linkData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                  {linkData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-4 mt-2 text-sm font-medium">
            <div className="flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-blue-500"></span> Internal: {totalInternal}
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-emerald-500"></span> External: {totalExternal}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4 text-muted-foreground" />
            HTTP Status Codes
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusData} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <XAxis type="number" />
                <YAxis dataKey="status" type="category" width={40} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]}>
                  {statusData.map((entry, index) => {
                    let fill = "#3b82f6";
                    if (entry.status.startsWith("3")) fill = "#f59e0b";
                    if (entry.status.startsWith("4")) fill = "#ef4444";
                    if (entry.status.startsWith("5")) fill = "#8b5cf6";
                    return <Cell key={`cell-${index}`} fill={fill} />;
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
