"use client";

import React, { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAudit } from "@/lib/audit-context";
import { ApiService } from "@/services/api";
import { formatCrawlTime, matchesActivityFilter, ActivityFilterType } from "@/lib/activity-feed";
import { getActivityIcon } from "@/components/activity-icon";
import {
  Activity, Clock, Zap, Layers, Pause, Play, Square,
  RefreshCw, XCircle, ArrowLeft, Search,
  ArrowDownCircle, Filter,
} from "lucide-react";
import { Button } from "@/components/ui/button";

type ActiveTab = "activity" | "pages";

export default function LiveCrawlPage() {
  const router = useRouter();
  const { liveCrawlMetrics, activityLog, livePageRows, isLoading, setSelectedPage, activeSessionId } = useAudit();

  const [activeTab, setActiveTab] = useState<ActiveTab>("activity");
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState<ActivityFilterType>("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pageSearch, setPageSearch] = useState("");

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [activityLog, autoScroll]);

  const progress = liveCrawlMetrics?.progress ?? (isLoading ? 5 : 100);
  const pagesCrawled = liveCrawlMetrics?.pages_crawled ?? livePageRows.length;
  const queueRemaining = liveCrawlMetrics?.queue_remaining ?? 0;
  const speed = liveCrawlMetrics?.speed_pages_per_sec ?? 0;
  const elapsed = liveCrawlMetrics?.elapsed_seconds ?? 0;
  const eta = liveCrawlMetrics?.eta_seconds ?? 0;
  const currentUrl = liveCrawlMetrics?.current_url ?? "—";
  const stage = liveCrawlMetrics?.stage ?? (isLoading ? "Initialising…" : "Completed");

  const filteredActivity = activityLog.filter(act => matchesActivityFilter(act, searchQuery, filterType));

  const filteredPages = livePageRows.filter(row =>
    !pageSearch || row.url.toLowerCase().includes(pageSearch.toLowerCase())
  );

  const errorCount = activityLog.filter(a => ["broken_link", "timeout"].includes(a.type)).length;
  const redirectCount = activityLog.filter(a => a.type === "redirect").length;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* ─── Sticky Header ─────────────────────────────────────────────── */}
      <div className="sticky top-0 z-40 bg-background/95 backdrop-blur-md border-b border-border/40">
        <div className="px-4 md:px-8 lg:px-12 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard")} className="gap-1.5 text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-4 w-4" /> Dashboard
            </Button>
            <div className="h-4 w-[1px] bg-border/60" />
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                {isLoading && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />}
                <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${isLoading ? "bg-emerald-500" : "bg-muted-foreground"}`} />
              </span>
              <h1 className="text-sm font-bold text-foreground">Live Crawl Monitor</h1>
              <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold border ${isLoading ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" : "bg-muted text-muted-foreground border-border"}`}>
                {isLoading ? "In Progress" : "Completed"}
              </span>
            </div>
          </div>

          {isLoading && activeSessionId && (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => ApiService.pauseAudit(activeSessionId)} className="h-8 gap-1.5 text-xs">
                <Pause className="h-3.5 w-3.5" /> Pause
              </Button>
              <Button variant="outline" size="sm" onClick={() => ApiService.resumeAudit(activeSessionId)} className="h-8 gap-1.5 text-xs">
                <Play className="h-3.5 w-3.5" /> Resume
              </Button>
              <Button variant="outline" size="sm" onClick={() => ApiService.stopAudit(activeSessionId)} className="h-8 gap-1.5 text-xs text-rose-500 border-rose-500/40 hover:bg-rose-500/10">
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
              <Button variant="outline" size="sm" onClick={() => window.location.reload()} className="h-8 gap-1.5 text-xs">
                <RefreshCw className="h-3.5 w-3.5" /> Recrawl
              </Button>
            </div>
          )}
        </div>

        {/* Progress bar */}
        <div className="h-1 w-full bg-muted overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${isLoading ? "bg-gradient-to-r from-blue-500 to-emerald-500" : "bg-emerald-500"}`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      <div className="flex-1 px-4 md:px-8 lg:px-12 py-6 space-y-6">
        {/* ─── Stats Cards ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {[
            { icon: Layers, label: "Pages Crawled", value: String(pagesCrawled), color: "text-blue-500" },
            { icon: Search, label: "Queue Remaining", value: String(queueRemaining), color: "text-amber-500" },
            { icon: Zap, label: "Speed (p/s)", value: String(speed), color: "text-emerald-500" },
            { icon: Clock, label: "Elapsed", value: formatCrawlTime(elapsed), color: "text-indigo-500" },
            { icon: Clock, label: "ETA", value: isLoading && eta > 0 ? formatCrawlTime(eta) : "—", color: "text-purple-500" },
            { icon: XCircle, label: "Errors", value: String(errorCount), color: "text-rose-500" },
            { icon: RefreshCw, label: "Redirects", value: String(redirectCount), color: "text-orange-500" },
          ].map(({ icon: Icon, label, value, color }) => (
            <div key={label} className="rounded-xl border border-border/60 bg-card p-3.5">
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground mb-2">
                <Icon className={`h-3.5 w-3.5 ${color}`} /> {label}
              </div>
              <p className="text-lg font-bold tabular-nums text-foreground leading-none">{value}</p>
            </div>
          ))}
        </div>

        {/* Current target */}
        <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3 text-xs text-muted-foreground flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-primary shrink-0" />
          <span>Currently crawling:</span>
          <span className="font-mono text-foreground font-semibold truncate">{currentUrl}</span>
          <span className="ml-auto shrink-0 font-semibold text-foreground">{stage}</span>
        </div>

        {/* ─── Tabs ─────────────────────────────────────────────────────── */}
        <div className="rounded-2xl border border-border/60 bg-card overflow-hidden">
          <div className="flex border-b border-border/60">
            {(["activity", "pages"] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-5 py-3 text-xs font-semibold transition-colors ${activeTab === tab ? "text-foreground border-b-2 border-primary -mb-px" : "text-muted-foreground hover:text-foreground"}`}
              >
                {tab === "activity" ? `Activity Feed (${filteredActivity.length})` : `Crawled Pages (${livePageRows.length})`}
              </button>
            ))}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border/60 bg-muted/10">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              {activeTab === "activity" ? (
                <input
                  type="text"
                  placeholder="Search events…"
                  className="h-8 w-full text-xs bg-background border border-border rounded-lg pl-8 pr-3 focus:outline-none focus:ring-1 focus:ring-primary"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                />
              ) : (
                <input
                  type="text"
                  placeholder="Search URLs…"
                  className="h-8 w-full text-xs bg-background border border-border rounded-lg pl-8 pr-3 focus:outline-none focus:ring-1 focus:ring-primary"
                  value={pageSearch}
                  onChange={e => setPageSearch(e.target.value)}
                />
              )}
            </div>
            {activeTab === "activity" && (
              <>
                <select
                  className="h-8 text-xs bg-background border border-border rounded-lg px-2 focus:outline-none"
                  value={filterType}
                  onChange={e => setFilterType(e.target.value as ActivityFilterType)}
                >
                  <option value="all">All Events</option>
                  <option value="page">Pages Only</option>
                  <option value="link">Links Only</option>
                  <option value="redirect">Redirects</option>
                  <option value="error">Errors</option>
                </select>
                <button
                  onClick={() => setAutoScroll(!autoScroll)}
                  title={autoScroll ? "Pause auto-scroll" : "Resume auto-scroll"}
                  className={`h-8 w-8 flex items-center justify-center rounded-lg border transition-colors ${autoScroll ? "border-primary/30 bg-primary/10 text-primary" : "border-border bg-background text-muted-foreground"}`}
                >
                  <ArrowDownCircle className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </div>

          {/* Content */}
          <div ref={scrollRef} className="overflow-y-auto max-h-[calc(100vh-420px)] min-h-[300px]">
            {activeTab === "activity" ? (
              <div className="p-4 space-y-1.5">
                {filteredActivity.length === 0 ? (
                  <div className="py-16 text-center text-xs text-muted-foreground">
                    {isLoading ? "Waiting for events…" : "No events recorded."}
                  </div>
                ) : (
                  filteredActivity.map(act => (
                    <div
                      key={act.id}
                      className="flex items-start gap-2.5 rounded-lg border border-border/40 bg-card/60 px-3 py-2 text-xs text-foreground hover:bg-muted/30 transition-colors"
                    >
                      {getActivityIcon(act.type)}
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{act.message}</p>
                        {act.url && <p className="truncate text-[10px] text-muted-foreground font-mono mt-0.5">{act.url}</p>}
                      </div>
                      <span className="text-[10px] text-muted-foreground shrink-0">
                        {new Date(act.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  ))
                )}
              </div>
            ) : (
              <table className="w-full text-xs text-left">
                <thead className="sticky top-0 bg-muted/30 backdrop-blur border-b border-border/60">
                  <tr className="text-muted-foreground">
                    <th className="px-4 py-2.5 font-semibold">URL</th>
                    <th className="px-3 py-2.5 font-semibold">Status</th>
                    <th className="px-3 py-2.5 font-semibold">Depth</th>
                    <th className="px-3 py-2.5 font-semibold text-right pr-4">Time (ms)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {filteredPages.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="py-16 text-center text-muted-foreground">
                        {isLoading ? "No pages crawled yet…" : "No pages found."}
                      </td>
                    </tr>
                  ) : (
                    filteredPages.map((row, idx) => (
                      <tr
                        key={idx}
                        className="hover:bg-muted/30 cursor-pointer transition-colors"
                        onClick={() => setSelectedPage({ url: row.url } as any)}
                      >
                        <td className="px-4 py-2 max-w-[360px] truncate font-mono text-[11px] text-primary">{row.url}</td>
                        <td className="px-3 py-2">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${row.status === 200 ? "bg-emerald-500/10 text-emerald-500" : "bg-amber-500/10 text-amber-500"}`}>
                            {row.status ?? 200}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">{row.depth ?? 0}</td>
                        <td className="px-3 py-2 text-right pr-4 text-muted-foreground">{row.response_time ?? 0}ms</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

