"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Zap, Clock } from "lucide-react";
import { PageItem } from "@/lib/types";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

interface PerformancePanelProps {
  pages: PageItem[];
}

export function PerformancePanel({ pages }: PerformancePanelProps) {
  const pagesWithTime = pages.filter(p => p.response_time_ms !== null) as (PageItem & { response_time_ms: number })[];
  const avgResponseTime = pagesWithTime.length > 0 
    ? Math.round(pagesWithTime.reduce((acc, p) => acc + p.response_time_ms, 0) / pagesWithTime.length) 
    : 0;

  const sortedPages = [...pagesWithTime].sort((a, b) => b.response_time_ms - a.response_time_ms);
  const slowestPages = sortedPages.slice(0, 10).map(p => ({
    url: p.url.replace(/^https?:\/\/[^\/]+/, '') || '/',
    time: p.response_time_ms
  }));

  const avgSize = pages.reduce((acc, p) => acc + (p.html_size_bytes || 0), 0) / Math.max(1, pages.length);

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Zap className="h-4 w-4 text-muted-foreground" />
            Performance Metrics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 text-sm">
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">Avg Response Time</span>
              <span className={`font-semibold ${avgResponseTime > 1000 ? 'text-rose-500' : avgResponseTime > 500 ? 'text-amber-500' : 'text-emerald-500'}`}>
                {avgResponseTime} ms
              </span>
            </div>
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">Avg HTML Size</span>
              <span className="font-semibold">{(avgSize / 1024).toFixed(1)} KB</span>
            </div>
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">Fastest Page</span>
              <span className="font-semibold text-emerald-500">
                {sortedPages.length > 0 ? `${sortedPages[sortedPages.length - 1].response_time_ms} ms` : 'N/A'}
              </span>
            </div>
            <div className="flex justify-between border-b border-border/40 pb-2">
              <span className="text-muted-foreground">Slowest Page</span>
              <span className="font-semibold text-rose-500">
                {sortedPages.length > 0 ? `${sortedPages[0].response_time_ms} ms` : 'N/A'}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-4 w-4 text-muted-foreground" />
            Slowest Pages (Response Time ms)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={slowestPages} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                <XAxis dataKey="url" hide />
                <YAxis type="number" fontSize={10} tickFormatter={(val) => `${val}ms`} />
                <Tooltip 
                  contentStyle={{ backgroundColor: 'hsl(var(--background))', border: '1px solid hsl(var(--border))', fontSize: '12px' }}
                  labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
                />
                <Bar dataKey="time" radius={[4, 4, 0, 0]}>
                  {slowestPages.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.time > 1000 ? '#ef4444' : '#f59e0b'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
