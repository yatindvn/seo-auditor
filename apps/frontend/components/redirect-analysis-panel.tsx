"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowRightLeft } from "lucide-react";
import { ExecutiveSummary, PageItem } from "@/lib/types";

interface RedirectAnalysisPanelProps {
  es: ExecutiveSummary;
  pages: PageItem[];
}

export function RedirectAnalysisPanel({ es, pages }: RedirectAnalysisPanelProps) {
  const pagesWithRedirects = pages.filter(p => p.redirect_chain && p.redirect_chain.length > 0);
  
  let tempRedirects = 0;
  let permRedirects = 0;
  
  pagesWithRedirects.forEach(p => {
    p.redirect_chain?.forEach(r => {
      if (r.status === 301 || r.status === 308) permRedirects++;
      else if (r.status === 302 || r.status === 307) tempRedirects++;
    });
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ArrowRightLeft className="h-4 w-4 text-muted-foreground" />
          Redirect Analysis
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="p-3 bg-muted/30 rounded-lg border border-border/50 text-center">
            <p className="text-xs text-muted-foreground uppercase mb-1">Chains</p>
            <p className="text-2xl font-bold">{es.redirect_chains}</p>
          </div>
          <div className="p-3 bg-muted/30 rounded-lg border border-border/50 text-center">
            <p className="text-xs text-muted-foreground uppercase mb-1">Loops</p>
            <p className="text-2xl font-bold text-rose-500">{es.redirect_loops}</p>
          </div>
          <div className="p-3 bg-muted/30 rounded-lg border border-border/50 text-center">
            <p className="text-xs text-muted-foreground uppercase mb-1">Temporary (302)</p>
            <p className="text-2xl font-bold text-amber-500">{tempRedirects}</p>
          </div>
          <div className="p-3 bg-muted/30 rounded-lg border border-border/50 text-center">
            <p className="text-xs text-muted-foreground uppercase mb-1">Permanent (301)</p>
            <p className="text-2xl font-bold text-emerald-500">{permRedirects}</p>
          </div>
        </div>
        
        {pagesWithRedirects.length > 0 && (
          <div className="max-h-64 overflow-y-auto pr-2">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="border-b border-border/50 text-muted-foreground">
                  <th className="pb-2 font-medium">Final URL</th>
                  <th className="pb-2 font-medium">Chain Length</th>
                  <th className="pb-2 font-medium">Hops</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {pagesWithRedirects.map((p, i) => (
                  <tr key={i}>
                    <td className="py-2 text-primary font-mono truncate max-w-[200px] pr-4">{p.url}</td>
                    <td className="py-2">{p.redirect_chain?.length}</td>
                    <td className="py-2 text-muted-foreground truncate max-w-[300px]">
                      {p.redirect_chain?.map(r => `${r.from} (${r.status})`).join(" → ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
