"use client";

import React, { useState, useRef, useEffect } from "react";
import { useAudit } from "@/lib/audit-context";
import { ApiService } from "@/services/api";
import { Activity, Clock, Zap, Layers, AlertCircle, CheckCircle2, Search, Pause, Play, Square, RefreshCw, Link2, ExternalLink, XCircle, ArrowDownCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

export function LiveCrawlPanel() {
  const { liveCrawlMetrics, activityLog, livePageRows, isLoading, setSelectedPage } = useAudit();
  
  const [autoScroll, setAutoScroll] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState("all");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = 0; // The list is newest-first, so scroll to top
    }
  }, [activityLog, autoScroll]);

  if (!isLoading && !liveCrawlMetrics) {
    return null;
  }

  const speed = liveCrawlMetrics?.speed_pages_per_sec || 0;
  const pagesCrawled = liveCrawlMetrics?.pages_crawled || livePageRows.length;
  const queueRemaining = liveCrawlMetrics?.queue_remaining || 0;
  const elapsed = liveCrawlMetrics?.elapsed_seconds || 0;
  const eta = liveCrawlMetrics?.eta_seconds || 0;
  const currentUrl = liveCrawlMetrics?.current_url || "Crawling site pages…";
  
  const filteredActivity = activityLog.filter(act => {
    if (searchQuery && !act.message.toLowerCase().includes(searchQuery.toLowerCase()) && !act.url?.toLowerCase().includes(searchQuery.toLowerCase())) {
      return false;
    }
    if (filterType !== "all") {
      if (filterType === "link" && !['internal_link', 'external_link'].includes(act.type)) return false;
      if (filterType === "error" && !['broken_link', 'timeout'].includes(act.type)) return false;
      if (filterType === "page" && act.type !== "page_crawled") return false;
      if (filterType === "redirect" && act.type !== "redirect") return false;
    }
    return true;
  });

  const getIconForType = (type: string) => {
    switch (type) {
      case 'internal_link': return <Link2 className="h-3.5 w-3.5 text-blue-500 shrink-0 mt-0.5" />;
      case 'external_link': return <ExternalLink className="h-3.5 w-3.5 text-purple-500 shrink-0 mt-0.5" />;
      case 'broken_link': return <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0 mt-0.5" />;
      case 'timeout': return <Clock className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />;
      case 'redirect': return <RefreshCw className="h-3.5 w-3.5 text-orange-500 shrink-0 mt-0.5" />;
      case 'page_crawled': return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />;
      default: return <Activity className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />;
    }
  };

  return (
    <div className="space-y-6 rounded-2xl border border-primary/20 bg-card/80 p-6 shadow-glass backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border/60 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="relative flex h-3 w-3">
              {isLoading && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>}
              <span className={`relative inline-flex rounded-full h-3 w-3 ${isLoading ? 'bg-emerald-500' : 'bg-muted-foreground'}`}></span>
            </span>
            <h3 className="text-lg font-bold tracking-tight text-foreground">Live Crawl Monitor</h3>
          </div>
          <p className="mt-1 text-xs text-muted-foreground truncate max-w-xl">
            Active Target: <span className="font-semibold text-primary">{currentUrl}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && (
            <>
              <Button variant="outline" size="sm" onClick={() => ApiService.pauseAudit()} className="h-8 gap-1 text-xs">
                <Pause className="h-3.5 w-3.5" /> Pause
              </Button>
              <Button variant="outline" size="sm" onClick={() => ApiService.resumeAudit()} className="h-8 gap-1 text-xs">
                <Play className="h-3.5 w-3.5" /> Resume
              </Button>
              <Button variant="destructive" size="sm" onClick={() => ApiService.stopAudit()} className="h-8 gap-1 text-xs bg-red-500/20 text-red-500 hover:bg-red-500/30 border-red-500/50">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" onClick={() => window.location.reload()} className="h-8 gap-1 text-xs">
            <RefreshCw className="h-3.5 w-3.5" /> Recrawl
          </Button>
          <span className={`ml-2 rounded-full px-3 py-1 text-xs font-semibold border ${isLoading ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' : 'bg-muted text-muted-foreground border-border'}`}>
            {isLoading ? "In Progress" : "Completed"}
          </span>
        </div>
      </div>

      {/* Live Metrics Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <div className="rounded-xl border border-border/60 bg-muted/30 p-3.5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Layers className="h-3.5 w-3.5 text-blue-500" />
            <span>Crawled</span>
          </div>
          <p className="mt-2 text-xl font-bold text-foreground">{pagesCrawled}</p>
        </div>

        <div className="rounded-xl border border-border/60 bg-muted/30 p-3.5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Search className="h-3.5 w-3.5 text-amber-500" />
            <span>Queue</span>
          </div>
          <p className="mt-2 text-xl font-bold text-foreground">{queueRemaining}</p>
        </div>

        <div className="rounded-xl border border-border/60 bg-muted/30 p-3.5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Zap className="h-3.5 w-3.5 text-emerald-500" />
            <span>Speed</span>
          </div>
          <p className="mt-2 text-xl font-bold text-foreground">{speed} p/s</p>
        </div>

        <div className="rounded-xl border border-border/60 bg-muted/30 p-3.5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5 text-indigo-500" />
            <span>Elapsed</span>
          </div>
          <p className="mt-2 text-xl font-bold text-foreground">{elapsed}s</p>
        </div>

        <div className="rounded-xl border border-border/60 bg-muted/30 p-3.5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Activity className="h-3.5 w-3.5 text-purple-500" />
            <span>ETA</span>
          </div>
          <p className="mt-2 text-xl font-bold text-foreground">{eta}s</p>
        </div>

        <div className="rounded-xl border border-border/60 bg-muted/30 p-3.5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
            <span>Status</span>
          </div>
          <p className={`mt-2 text-sm font-semibold ${isLoading ? 'text-emerald-500' : 'text-muted-foreground'}`}>
            {isLoading ? "Running" : "Done"}
          </p>
        </div>
      </div>

      {/* Live Progress Bar */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs font-semibold text-muted-foreground">
          <span>{liveCrawlMetrics?.stage || "Scanning BFS Nodes..."}</span>
          <span>{liveCrawlMetrics?.progress || (isLoading ? 5 : 100)}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-300"
            style={{ width: `${liveCrawlMetrics?.progress || (isLoading ? 5 : 100)}%` }}
          />
        </div>
      </div>

      {/* Grid: Activity Feed & Live Crawled Table */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Activity Feed */}
        <div className="rounded-xl border border-border/60 bg-muted/20 p-4 flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Live Activity Feed
            </h4>
            <div className="flex items-center gap-2">
              <input 
                type="text" 
                placeholder="Search..." 
                className="h-7 text-xs bg-background border border-border rounded px-2 w-24 focus:outline-none focus:ring-1 focus:ring-primary"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
              <select 
                className="h-7 text-xs bg-background border border-border rounded px-1 focus:outline-none"
                value={filterType}
                onChange={e => setFilterType(e.target.value)}
              >
                <option value="all">All</option>
                <option value="page">Pages</option>
                <option value="link">Links</option>
                <option value="redirect">Redirects</option>
                <option value="error">Errors</option>
              </select>
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setAutoScroll(!autoScroll)} title={autoScroll ? "Pause Scroll" : "Resume Scroll"}>
                <ArrowDownCircle className={`h-4 w-4 ${autoScroll ? 'text-primary' : 'text-muted-foreground'}`} />
              </Button>
            </div>
          </div>
          <div ref={scrollRef} className="h-64 space-y-2 overflow-y-auto pr-2 text-xs flex-1">
            {filteredActivity.length === 0 ? (
              <div className="flex h-full items-center justify-center text-muted-foreground">
                Listening for real-time events…
              </div>
            ) : (
              filteredActivity.map((act) => (
                <div
                  key={act.id}
                  className="flex items-start gap-2 rounded-lg border border-border/40 bg-card/60 p-2 text-foreground"
                >
                  {getIconForType(act.type)}
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{act.message}</p>
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(act.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Live Crawled Pages Table */}
        <div className="rounded-xl border border-border/60 bg-muted/20 p-4 flex flex-col">
          <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Live Crawled Pages
          </h4>
          <div className="h-64 overflow-y-auto text-xs flex-1">
            <table className="w-full text-left">
              <thead className="sticky top-0 bg-muted/20 backdrop-blur">
                <tr className="border-b border-border/60 text-muted-foreground">
                  <th className="pb-2 font-semibold pl-2">URL</th>
                  <th className="pb-2 font-semibold">Status</th>
                  <th className="pb-2 font-semibold">Depth</th>
                  <th className="pb-2 font-semibold text-right pr-2">Time (ms)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {livePageRows.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-muted-foreground">
                      No pages streamed yet
                    </td>
                  </tr>
                ) : (
                  livePageRows.map((row, idx) => (
                    <tr 
                      key={idx} 
                      className="hover:bg-muted/40 cursor-pointer transition-colors"
                      onClick={() => setSelectedPage({ url: row.url } as any)}
                    >
                      <td className="py-2 pl-2 max-w-[200px] truncate font-mono text-[11px] text-primary">{row.url}</td>
                      <td className="py-2">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${row.status === 200 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500'}`}>
                          {row.status || 200}
                        </span>
                      </td>
                      <td className="py-2 text-muted-foreground">{row.depth || 0}</td>
                      <td className="py-2 pr-2 text-right text-muted-foreground">{row.response_time || 0}ms</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
