"use client";

import React from "react";
import { useAudit } from "@/lib/audit-context";
import { ShieldCheck, Code, Link2, Eye, Zap, Lock } from "lucide-react";

export function ScoreBreakdownCard() {
  const { auditData } = useAudit();
  const health = auditData?.executive_summary.health_score;
  const categories = health?.categories || {
    technical_seo: 92,
    content: 85,
    internal_linking: 88,
    accessibility: 80,
    performance: 78,
    security: 95,
  };

  const cards = [
    { label: "Technical SEO", score: categories.technical_seo, icon: Code, color: "text-blue-500", bg: "bg-blue-500" },
    { label: "Content Quality", score: categories.content, icon: ShieldCheck, color: "text-emerald-500", bg: "bg-emerald-500" },
    { label: "Internal Linking", score: categories.internal_linking, icon: Link2, color: "text-purple-500", bg: "bg-purple-500" },
    { label: "Accessibility", score: categories.accessibility, icon: Eye, color: "text-amber-500", bg: "bg-amber-500" },
    { label: "Performance", score: categories.performance, icon: Zap, color: "text-indigo-500", bg: "bg-indigo-500" },
    { label: "Security", score: categories.security, icon: Lock, color: "text-rose-500", bg: "bg-rose-500" },
  ];

  return (
    <div className="space-y-4 rounded-2xl border border-border/80 bg-card/80 p-6 shadow-glass backdrop-blur-md">
      <div className="flex items-center justify-between border-b border-border/60 pb-3">
        <div>
          <h3 className="text-lg font-bold tracking-tight text-foreground">Website Score Breakdown</h3>
          <p className="text-xs text-muted-foreground">Category sub-scores across 6 key SEO pillars</p>
        </div>
        <div className="text-right">
          <span className="text-xs text-muted-foreground">Overall Health</span>
          <p className="text-xl font-black text-foreground">{health?.score ?? 88} / 100</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map((item, idx) => (
          <div key={idx} className="space-y-2 rounded-xl border border-border/60 bg-muted/20 p-3.5">
            <div className="flex items-center gap-2">
              <item.icon className={`h-4 w-4 ${item.color}`} />
              <span className="text-xs font-semibold text-foreground truncate">{item.label}</span>
            </div>
            <p className="text-2xl font-black text-foreground">{item.score}%</p>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div className={`h-full ${item.bg}`} style={{ width: `${item.score}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
