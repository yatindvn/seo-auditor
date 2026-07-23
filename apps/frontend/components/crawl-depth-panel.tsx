"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Layers, ArrowDownToLine } from "lucide-react";
import { SiteWideAnalysis, PageItem } from "@/lib/types";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { useAudit } from "@/lib/audit-context";

interface CrawlDepthPanelProps {
  analysis: SiteWideAnalysis;
  pages: PageItem[];
}

export function CrawlDepthPanel({ analysis, pages }: CrawlDepthPanelProps) {
  const { setSelectedPage } = useAudit();
  
  const dist = analysis.depth_distribution || {};
  const depthData = Object.entries(dist).map(([depth, count]) => ({
    depth: `Depth ${depth}`,
    count
  })).sort((a, b) => parseInt(a.depth.split(' ')[1]) - parseInt(b.depth.split(' ')[1]));

  const maxDepth = analysis.max_crawl_depth || 0;
  
  let totalDepthSum = 0;
  let totalPages = 0;
  Object.entries(dist).forEach(([d, c]) => {
    totalDepthSum += parseInt(d) * c;
    totalPages += c;
  });
  const avgDepth = totalPages > 0 ? (totalDepthSum / totalPages).toFixed(2) : "0";

  const deepestPages = pages.filter(p => p.depth === maxDepth).slice(0, 5);

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Layers className="h-4 w-4 text-muted-foreground" />
            Crawl Depth Distribution
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 mb-4">
            <div className="flex-1 p-3 bg-muted/30 border border-border/50 rounded-lg text-center">
              <p className="text-xs text-muted-foreground uppercase mb-1">Max Depth</p>
              <p className="text-2xl font-bold">{maxDepth}</p>
            </div>
            <div className="flex-1 p-3 bg-muted/30 border border-border/50 rounded-lg text-center">
              <p className="text-xs text-muted-foreground uppercase mb-1">Average Depth</p>
              <p className="text-2xl font-bold">{avgDepth}</p>
            </div>
          </div>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={depthData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                <XAxis dataKey="depth" fontSize={10} />
                <YAxis type="number" fontSize={10} />
                <Tooltip 
                  cursor={{ fill: 'transparent' }}
                  contentStyle={{ backgroundColor: 'hsl(var(--background))', border: '1px solid hsl(var(--border))', fontSize: '12px' }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {depthData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={index > 2 ? '#f59e0b' : '#3b82f6'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ArrowDownToLine className="h-4 w-4 text-muted-foreground" />
            Deepest Pages (Depth {maxDepth})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {deepestPages.length === 0 ? (
            <p className="text-xs text-muted-foreground">No deep pages found.</p>
          ) : (
            <div className="space-y-2">
              {deepestPages.map((p, idx) => (
                <div 
                  key={idx} 
                  className="p-3 bg-muted/20 border border-border/50 rounded-lg hover:bg-muted/40 cursor-pointer transition-colors"
                  onClick={() => setSelectedPage({ url: p.url } as any)}
                >
                  <p className="text-[11px] font-mono text-primary truncate" title={p.url}>{p.url}</p>
                  <div className="flex gap-4 mt-2 text-[10px] text-muted-foreground">
                    <span>Status: {p.status_code || 200}</span>
                    <span>Response: {p.response_time_ms}ms</span>
                    <span>Issues: {p.critical_issues + p.warning_issues + p.info_issues}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
