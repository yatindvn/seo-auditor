"use client";

import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Crown, Search } from "lucide-react";
import { SiteWideAnalysis, PageItem } from "@/lib/types";
import { useAudit } from "@/lib/audit-context";

interface HubAnalysisPanelProps {
  analysis: SiteWideAnalysis;
  pages: PageItem[];
}

export function HubAnalysisPanel({ analysis, pages }: HubAnalysisPanelProps) {
  const { setSelectedPage } = useAudit();
  const [search, setSearch] = useState("");
  
  // hub_pages_over_linked is Array<[url, outboundCount]>
  const hubs = analysis.hub_pages_over_linked || [];
  
  // Mix in top_pages_by_importance if available for Link Score
  const importanceMap = new Map(analysis.top_pages_by_importance?.map(p => [p.url, p.score]) || []);

  const hubData = hubs.map(([url, outCount]) => {
    const page = pages.find(p => p.url === url);
    return {
      url,
      outCount,
      inCount: page?.internal_links_count || 0, // Approx for inbound
      score: importanceMap.get(url) ? Math.round(importanceMap.get(url)! * 100) / 100 : "N/A"
    };
  }).filter(h => h.url.toLowerCase().includes(search.toLowerCase()));

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Crown className="h-4 w-4 text-emerald-500" />
          Hub Analysis & Authority
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs text-muted-foreground">Pages with excessive outbound links ({'>'} 150) or high PageRank.</p>
          <div className="relative w-48">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search hubs..."
              className="w-full bg-background border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
        
        <div className="max-h-64 overflow-y-auto pr-2">
          {hubData.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-4">No hub pages found.</p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/30 sticky top-0 backdrop-blur">
                <tr className="border-b border-border/50 text-muted-foreground">
                  <th className="py-2 pl-2 font-medium">Authority URL</th>
                  <th className="py-2 font-medium text-right">Inbound</th>
                  <th className="py-2 font-medium text-right">Outbound</th>
                  <th className="py-2 font-medium text-right">Link Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {hubData.map((hub, idx) => (
                  <tr key={idx} className="hover:bg-muted/30 cursor-pointer transition-colors" onClick={() => setSelectedPage({ url: hub.url } as any)}>
                    <td className="py-2 pl-2 font-mono text-[11px] text-primary truncate max-w-[200px]" title={hub.url}>{hub.url}</td>
                    <td className="py-2 text-right">{hub.inCount}</td>
                    <td className="py-2 text-right text-rose-500 font-bold">{hub.outCount}</td>
                    <td className="py-2 text-right text-emerald-500 font-bold">{hub.score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
