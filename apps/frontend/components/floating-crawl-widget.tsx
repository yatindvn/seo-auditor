"use client";

import React from "react";
import { useAudit } from "@/lib/audit-context";
import { Layers, Clock } from "lucide-react";

function formatTime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function FloatingCrawlWidget() {
  const { liveCrawlMetrics, isLoading } = useAudit();

  if (!isLoading || !liveCrawlMetrics) return null;

  const progress = liveCrawlMetrics.progress ?? 5;
  const pagesCrawled = liveCrawlMetrics.pages_crawled ?? 0;
  const eta = liveCrawlMetrics.eta_seconds ?? 0;
  const currentUrl = liveCrawlMetrics.current_url ?? "";

  // Extract domain
  let domain = currentUrl;
  try { domain = new URL(currentUrl).hostname; } catch {}

  const handleClick = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <button
      onClick={handleClick}
      title="Scroll to crawl status"
      className="fixed bottom-6 right-6 z-50 flex flex-col gap-1.5 rounded-2xl border border-primary/30 bg-card/95 backdrop-blur-md shadow-2xl px-4 py-3 text-left hover:border-primary/60 transition-all duration-200 hover:shadow-primary/20 hover:shadow-xl group min-w-[180px]"
    >
      {/* Domain + live badge */}
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] font-semibold text-muted-foreground truncate max-w-[120px]">{domain}</span>
        <span className="flex h-2 w-2 shrink-0">
          <span className="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
        </span>
      </div>

      {/* Big percentage */}
      <div className="text-2xl font-bold tabular-nums text-foreground leading-none">
        {progress}%
      </div>

      {/* Progress bar */}
      <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Layers className="h-3 w-3 text-blue-500" />
          {pagesCrawled} pages
        </span>
        {eta > 0 && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3 text-indigo-500" />
            ETA {formatTime(eta)}
          </span>
        )}
      </div>

      {/* Tap hint */}
      <p className="text-[9px] text-muted-foreground/60 group-hover:text-muted-foreground transition-colors">
        ↑ Click to scroll to status
      </p>
    </button>
  );
}
