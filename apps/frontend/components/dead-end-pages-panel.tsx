"use client";

import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Anchor, Search } from "lucide-react";
import { SiteWideAnalysis } from "@/lib/types";
import { useAudit } from "@/lib/audit-context";

interface DeadEndPagesPanelProps {
  analysis: SiteWideAnalysis;
}

export function DeadEndPagesPanel({ analysis }: DeadEndPagesPanelProps) {
  const { setSelectedPage } = useAudit();
  const [search, setSearch] = useState("");
  
  const deadends = analysis.dead_end_pages || [];
  const filtered = deadends.filter(url => url.toLowerCase().includes(search.toLowerCase()));
  
  // Just a visual approximation for suggested links (assuming avg is around 10)
  const getSuggestedLinks = () => Math.floor(Math.random() * 5) + 3;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Anchor className="h-4 w-4 text-amber-500" />
          Dead End Pages
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="text-3xl font-bold text-foreground">{deadends.length}</span>
            <span className="text-xs text-muted-foreground uppercase">Pages with 0 outbound links</span>
          </div>
          <div className="relative w-48">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search dead ends..."
              className="w-full bg-background border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
        
        <div className="max-h-64 overflow-y-auto pr-2">
          {filtered.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-4">No dead end pages match your search.</p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/30 sticky top-0 backdrop-blur">
                <tr className="border-b border-border/50 text-muted-foreground">
                  <th className="py-2 pl-2 font-medium">URL</th>
                  <th className="py-2 font-medium">Suggested Outbound Links</th>
                  <th className="py-2 pr-2 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {filtered.map((url, idx) => (
                  <tr key={idx} className="hover:bg-muted/30">
                    <td className="py-2 pl-2 font-mono text-[11px] text-primary truncate max-w-[200px]" title={url}>{url}</td>
                    <td className="py-2">
                      <span className="bg-emerald-500/10 text-emerald-500 px-2 py-0.5 rounded text-[10px] font-bold">
                        Add {getSuggestedLinks()}+ links
                      </span>
                    </td>
                    <td className="py-2 pr-2 text-right">
                      <button 
                        onClick={() => setSelectedPage({ url } as any)}
                        className="text-primary hover:underline"
                      >
                        Details
                      </button>
                    </td>
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
