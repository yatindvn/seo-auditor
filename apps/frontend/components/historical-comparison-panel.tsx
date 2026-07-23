"use client";

import React, { useEffect, useState } from "react";
import { useAudit } from "@/lib/audit-context";
import { ApiService } from "@/services/api";
import { History, TrendingUp, TrendingDown, Trash2, FolderOpen, Scale, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function HistoricalComparisonPanel() {
  const { auditData, setAuditData, historyComparison, setHistoryComparison } = useAudit();
  const [sessions, setSessions] = useState<any[]>([]);
  const [comparingSession, setComparingSession] = useState<any | null>(null);

  const loadHistory = async () => {
    try {
      const res = await ApiService.getHistory();
      if (res?.sessions) setSessions(res.sessions);
      if (res?.comparison) setHistoryComparison(res.comparison);
    } catch {
      // Ignore fetch error
    }
  };

  useEffect(() => {
    loadHistory();
  }, [auditData]);

  const handleDelete = async (id: string) => {
    try {
      await ApiService.deleteHistory(id);
      loadHistory();
    } catch (e) {
      console.error(e);
    }
  };

  const handleOpen = (session: any) => {
    if (session.auditResult) {
      setAuditData(session.auditResult);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const handleCompare = (session: any) => {
    if (!auditData) return;
    const prev = session.auditResult;
    const currScore = auditData.executive_summary?.health_score?.score || 0;
    const prevScore = prev?.executive_summary?.health_score?.score || 0;

    const currRecs = new Set((auditData.recommendations || []).map((r: any) => r.code));
    const prevRecs = new Set((prev?.recommendations || []).map((r: any) => r.code));

    const newIssues = Array.from(currRecs).filter(x => !prevRecs.has(x));
    const resolvedIssues = Array.from(prevRecs).filter(x => !currRecs.has(x));

    const comp = {
      previousDate: prev?.executive_summary?.audit_date || "",
      currentDate: auditData.executive_summary?.audit_date || "",
      scoreChange: Math.round((currScore - prevScore) * 10) / 10,
      previousScore: prevScore,
      currentScore: currScore,
      newIssuesCount: newIssues.length,
      resolvedIssuesCount: resolvedIssues.length,
      newIssues,
      resolvedIssues,
      pagesCountDelta: (auditData.pages?.length || 0) - (prev?.pages?.length || 0),
    };
    
    setHistoryComparison(comp as any);
    setComparingSession(session);
  };

  if (sessions.length === 0) {
    return null;
  }

  const comp = historyComparison;
  const isImproved = comp && comp.scoreChange >= 0;

  return (
    <div className="space-y-6 rounded-2xl border border-border/80 bg-card/80 p-6 shadow-glass backdrop-blur-md">
      
      {comp && (
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-border/60 pb-3">
            <div className="flex items-center gap-2">
              <Scale className="h-5 w-5 text-primary" />
              <h3 className="text-lg font-bold tracking-tight text-foreground">Crawl Comparison Dashboard</h3>
            </div>
            <div className="flex items-center gap-2">
              {isImproved ? (
                <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-bold text-emerald-600 border border-emerald-500/20">
                  <TrendingUp className="h-3.5 w-3.5" /> +{comp.scoreChange} pts Improvement
                </span>
              ) : (
                <span className="flex items-center gap-1 rounded-full bg-rose-500/10 px-3 py-1 text-xs font-bold text-rose-500 border border-rose-500/20">
                  <TrendingDown className="h-3.5 w-3.5" /> {comp.scoreChange} pts Regression
                </span>
              )}
              <Button variant="ghost" size="sm" onClick={() => setHistoryComparison(null)}>Close</Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-border/60 bg-muted/20 p-3.5">
              <span className="text-xs text-muted-foreground">Previous Score</span>
              <p className="text-xl font-bold text-foreground mt-1">{comp.previousScore}</p>
            </div>
            <div className="rounded-xl border border-border/60 bg-muted/20 p-3.5">
              <span className="text-xs text-muted-foreground">Current Score</span>
              <p className="text-xl font-bold text-foreground mt-1">{comp.currentScore}</p>
            </div>
            <div className="rounded-xl border border-border/60 bg-muted/20 p-3.5">
              <span className="text-xs text-muted-foreground">Resolved Issues</span>
              <p className="text-xl font-bold text-emerald-500 mt-1">+{comp.resolvedIssuesCount}</p>
            </div>
            <div className="rounded-xl border border-border/60 bg-muted/20 p-3.5">
              <span className="text-xs text-muted-foreground">New Issues</span>
              <p className="text-xl font-bold text-rose-500 mt-1">{comp.newIssuesCount}</p>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-4 pt-4 border-t border-border/60">
        <div className="flex items-center gap-2">
          <History className="h-5 w-5 text-muted-foreground" />
          <h3 className="text-lg font-bold tracking-tight text-foreground">Session History</h3>
        </div>
        <div className="overflow-x-auto rounded-xl border border-border/60">
          <table className="w-full text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground border-b border-border/60">
              <tr>
                <th className="p-3">Audit Target</th>
                <th className="p-3">Date</th>
                <th className="p-3">Score</th>
                <th className="p-3">Pages</th>
                <th className="p-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40 font-mono">
              {sessions.map((s, idx) => {
                const isCurrent = auditData?.executive_summary?.audit_date === s.auditResult?.executive_summary?.audit_date;
                return (
                  <tr key={s.id || idx} className={`hover:bg-muted/20 ${isCurrent ? 'bg-primary/5' : ''}`}>
                    <td className="p-3 font-semibold text-primary truncate max-w-[200px]">{s.auditResult?.executive_summary?.start_url || "Unknown"}</td>
                    <td className="p-3">{new Date(s.timestamp || s.auditResult?.executive_summary?.audit_date).toLocaleString()}</td>
                    <td className="p-3">{s.auditResult?.executive_summary?.health_score?.score || 0}</td>
                    <td className="p-3">{s.auditResult?.executive_summary?.pages_crawled || 0}</td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {isCurrent ? (
                          <span className="text-xs font-sans font-bold text-emerald-500 mr-2">Current View</span>
                        ) : (
                          <>
                            <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => handleCompare(s)}>
                              <Scale className="h-3 w-3 mr-1" /> Compare
                            </Button>
                            <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => handleOpen(s)}>
                              <FolderOpen className="h-3 w-3 mr-1" /> Open
                            </Button>
                          </>
                        )}
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-rose-500 hover:text-rose-600 hover:bg-rose-500/10" onClick={() => handleDelete(s.id)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
