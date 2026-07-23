"use client";

import React, { useState } from "react";
import { useAudit } from "@/lib/audit-context";
import { AlertCircle, AlertTriangle, Info, CheckCircle2, ChevronRight, Shield, Zap } from "lucide-react";

export function IssueCenter() {
  const { auditData } = useAudit();
  const [severityFilter, setSeverityFilter] = useState<"all" | "critical" | "warning" | "info">("all");

  const recommendations = auditData?.recommendations || [];
  const filteredRecs = recommendations.filter((r) => severityFilter === "all" || r.severity === severityFilter);

  const criticalCount = recommendations.filter((r) => r.severity === "critical").length;
  const warningCount = recommendations.filter((r) => r.severity === "warning").length;
  const infoCount = recommendations.filter((r) => r.severity === "info").length;

  return (
    <div className="space-y-4 rounded-2xl border border-border/80 bg-card/80 p-6 shadow-glass backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border/60 pb-4">
        <div>
          <h3 className="text-lg font-bold tracking-tight text-foreground">Aggregated Issue Center</h3>
          <p className="text-xs text-muted-foreground">
            Prioritized issues grouped by severity, impact score, and estimated effort
          </p>
        </div>

        {/* Severity Filter Pills */}
        <div className="flex items-center gap-1.5 text-xs">
          <button
            onClick={() => setSeverityFilter("all")}
            className={`rounded-lg px-3 py-1.5 font-semibold transition-all ${
              severityFilter === "all" ? "bg-primary text-primary-foreground" : "bg-muted/40 text-muted-foreground hover:bg-muted"
            }`}
          >
            All ({recommendations.length})
          </button>
          <button
            onClick={() => setSeverityFilter("critical")}
            className={`rounded-lg px-3 py-1.5 font-semibold transition-all ${
              severityFilter === "critical" ? "bg-rose-500 text-white" : "bg-rose-500/10 text-rose-500 hover:bg-rose-500/20"
            }`}
          >
            Critical ({criticalCount})
          </button>
          <button
            onClick={() => setSeverityFilter("warning")}
            className={`rounded-lg px-3 py-1.5 font-semibold transition-all ${
              severityFilter === "warning" ? "bg-amber-500 text-white" : "bg-amber-500/10 text-amber-500 hover:bg-amber-500/20"
            }`}
          >
            Warning ({warningCount})
          </button>
          <button
            onClick={() => setSeverityFilter("info")}
            className={`rounded-lg px-3 py-1.5 font-semibold transition-all ${
              severityFilter === "info" ? "bg-blue-500 text-white" : "bg-blue-500/10 text-blue-500 hover:bg-blue-500/20"
            }`}
          >
            Info ({infoCount})
          </button>
        </div>
      </div>

      {/* Issues List */}
      <div className="space-y-3">
        {filteredRecs.length === 0 ? (
          <div className="rounded-xl border border-border/40 bg-muted/20 p-8 text-center text-xs text-muted-foreground">
            No issues match the selected severity filter.
          </div>
        ) : (
          filteredRecs.map((issue, idx) => (
            <div
              key={idx}
              className="group rounded-xl border border-border/60 bg-card/60 p-4 transition-all hover:border-primary/40 shadow-sm"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  {issue.severity === "critical" ? (
                    <AlertCircle className="h-5 w-5 text-rose-500 shrink-0 mt-0.5" />
                  ) : issue.severity === "warning" ? (
                    <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
                  ) : (
                    <Info className="h-5 w-5 text-blue-500 shrink-0 mt-0.5" />
                  )}
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-foreground">{issue.code}</span>
                      <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                        {issue.affected_pages} page(s)
                      </span>
                      {issue.impact && (
                        <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                          Impact: {issue.impact}
                        </span>
                      )}
                      {issue.estimated_effort && (
                        <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                          {issue.estimated_effort}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs font-medium text-foreground">{issue.recommendation}</p>
                    {issue.suggested_resolution && (
                      <p className="mt-1 text-[11px] text-muted-foreground">{issue.suggested_resolution}</p>
                    )}
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <span className="text-xs font-bold text-muted-foreground">Score</span>
                  <p className="text-sm font-black text-foreground">{issue.priority_score}</p>
                </div>
              </div>

              {/* Affected URLs Sample */}
              {issue.example_urls && issue.example_urls.length > 0 && (
                <div className="mt-3 border-t border-border/40 pt-2 text-[10px]">
                  <span className="font-semibold text-muted-foreground">Affected URLs Sample:</span>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {issue.example_urls.slice(0, 3).map((url, i) => (
                      <span key={i} className="rounded bg-muted/60 px-2 py-0.5 font-mono text-muted-foreground">
                        {url}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
