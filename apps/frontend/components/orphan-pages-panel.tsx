"use client";

import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Unlink, Search } from "lucide-react";
import { SiteWideAnalysis } from "@/lib/types";
import { useAudit } from "@/lib/audit-context";

interface OrphanPagesPanelProps {
  analysis: SiteWideAnalysis;
}

export function OrphanPagesPanel({ analysis }: OrphanPagesPanelProps) {
  const { setSelectedPage } = useAudit();
  const [search, setSearch] = useState("");
  
  const orphans = analysis.orphan_pages || [];
  const filtered = orphans.filter(url => url.toLowerCase().includes(search.toLowerCase()));

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Unlink className="h-4 w-4 text-purple-500" />
          Orphan Pages Analysis
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="text-3xl font-bold text-foreground">{orphans.length}</span>
            <span className="text-xs text-muted-foreground uppercase">Pages with 0 inbound links</span>
          </div>
          <div className="relative w-48">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search orphans..."
              className="w-full bg-background border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
        
        <div className="max-h-64 overflow-y-auto pr-2">
          {filtered.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-4">No orphan pages match your search.</p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/30 sticky top-0 backdrop-blur">
                <tr className="border-b border-border/50 text-muted-foreground">
                  <th className="py-2 pl-2 font-medium">Orphan URL</th>
                  <th className="py-2 pr-2 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {filtered.map((url, idx) => (
                  <tr key={idx} className="hover:bg-muted/30">
                    <td className="py-2 pl-2 font-mono text-[11px] text-primary truncate max-w-[300px]" title={url}>{url}</td>
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
