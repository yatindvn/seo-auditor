"use client";

import React, { useState, useRef, useEffect } from "react";
import { useAudit } from "@/lib/audit-context";
import { ApiService } from "@/services/api";
import { matchesActivityFilter, ActivityFilterType } from "@/lib/activity-feed";
import { getActivityIcon } from "@/components/activity-icon";
import {
  Activity, Clock, Zap, Layers, Pause, Play, Square,
  RefreshCw, ArrowDownCircle, X,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";


// ─── Activity Drawer ───────────────────────────────────────────────────────────
type DrawerTab = "activity" | "pages";

function ActivityDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { activityLog, livePageRows, isLoading, setSelectedPage, activeSessionId } = useAudit();
  const [activeTab, setActiveTab] = useState<DrawerTab>("activity");
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState<ActivityFilterType>("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current && open) {
      scrollRef.current.scrollTop = 0;
    }
  }, [activityLog, autoScroll, open]);

  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  const filteredActivity = activityLog.filter(act => matchesActivityFilter(act, searchQuery, filterType));

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[60] bg-background/60 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Drawer panel */}
      <div className="fixed right-0 top-0 bottom-0 z-[70] w-full max-w-[680px] bg-card border-l border-border shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5 shrink-0">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2.5 w-2.5">
              {isLoading && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />}
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${isLoading ? "bg-emerald-500" : "bg-muted-foreground"}`} />
            </span>
            <h2 className="text-sm font-bold tracking-tight text-foreground">Live Crawl Monitor</h2>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold border ${isLoading ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" : "bg-muted text-muted-foreground border-border"}`}>
              {isLoading ? "In Progress" : "Completed"}
            </span>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 hover:bg-muted transition-colors">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border shrink-0">
          <button
            className={`px-5 py-2.5 text-xs font-semibold transition-colors ${activeTab === "activity" ? "text-foreground border-b-2 border-primary" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setActiveTab("activity")}
          >
            Activity Feed
          </button>
          <button
            className={`px-5 py-2.5 text-xs font-semibold transition-colors ${activeTab === "pages" ? "text-foreground border-b-2 border-primary" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setActiveTab("pages")}
          >
            Crawled Pages ({livePageRows.length})
          </button>
        </div>

        {/* Controls */}
        {activeTab === "activity" && (
          <div className="flex items-center gap-2 px-5 py-2.5 border-b border-border/60 shrink-0">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search events..."
                className="h-7 w-full text-xs bg-muted/40 border border-border rounded-md pl-8 pr-3 focus:outline-none focus:ring-1 focus:ring-primary"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>
            <select
              className="h-7 text-xs bg-muted/40 border border-border rounded-md px-2 focus:outline-none"
              value={filterType}
              onChange={e => setFilterType(e.target.value as ActivityFilterType)}
            >
              <option value="all">All Events</option>
              <option value="page">Pages</option>
              <option value="link">Links</option>
              <option value="redirect">Redirects</option>
              <option value="error">Errors</option>
            </select>
            <button
              onClick={() => setAutoScroll(!autoScroll)}
              title={autoScroll ? "Pause auto-scroll" : "Resume auto-scroll"}
              className={`h-7 w-7 flex items-center justify-center rounded-md border transition-colors ${autoScroll ? "border-primary/30 bg-primary/10 text-primary" : "border-border bg-muted/40 text-muted-foreground"}`}
            >
              <ArrowDownCircle className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Activity list / Crawled pages list */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-1.5">
          {activeTab === "activity" ? (
            filteredActivity.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground py-16">
                {isLoading ? "Listening for real-time events…" : "No events recorded."}
              </div>
            ) : (
              filteredActivity.map(act => (
                <div
                  key={act.id}
                  className="flex items-start gap-2.5 rounded-lg border border-border/40 bg-card/60 px-3 py-2 text-xs text-foreground"
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
            )
          ) : (
            livePageRows.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground py-16">
                {isLoading ? "No pages crawled yet…" : "No pages found."}
              </div>
            ) : (
              livePageRows.map((row, idx) => (
                <button
                  key={idx}
                  onClick={() => setSelectedPage({ url: row.url } as any)}
                  className="flex w-full items-center gap-2.5 rounded-lg border border-border/40 bg-card/60 px-3 py-2 text-xs text-foreground text-left hover:bg-muted/30 transition-colors"
                >
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold shrink-0 ${row.status === 200 ? "bg-emerald-500/10 text-emerald-500" : "bg-amber-500/10 text-amber-500"}`}>
                    {row.status ?? 200}
                  </span>
                  <span className="truncate font-mono flex-1 min-w-0">{row.url}</span>
                  <span className="text-[10px] text-muted-foreground shrink-0">{row.response_time ?? 0}ms</span>
                </button>
              ))
            )
          )}
        </div>

        {/* Footer actions */}
        {isLoading && activeSessionId && (
          <div className="flex items-center gap-2 px-5 py-3 border-t border-border shrink-0">
            <Button variant="outline" size="sm" onClick={() => ApiService.pauseAudit(activeSessionId)} className="h-8 gap-1.5 text-xs flex-1">
              <Pause className="h-3.5 w-3.5" /> Pause
            </Button>
            <Button variant="outline" size="sm" onClick={() => ApiService.resumeAudit(activeSessionId)} className="h-8 gap-1.5 text-xs flex-1">
              <Play className="h-3.5 w-3.5" /> Resume
            </Button>
            <Button variant="outline" size="sm" onClick={() => ApiService.stopAudit(activeSessionId)} className="h-8 gap-1.5 text-xs flex-1 text-rose-500 border-rose-500/40 hover:bg-rose-500/10">
              <Square className="h-3.5 w-3.5" /> Stop
            </Button>
          </div>
        )}
      </div>
    </>
  );
}

// ─── Compact Crawl Bar ─────────────────────────────────────────────────────────
export function CompactCrawlBar() {
  const { liveCrawlMetrics, activityLog, isLoading, activeSessionId } = useAudit();
  const [drawerOpen, setDrawerOpen] = useState(false);

  if (!isLoading && !liveCrawlMetrics) return null;

  const progress = liveCrawlMetrics?.progress ?? (isLoading ? 5 : 100);
  const pagesCrawled = liveCrawlMetrics?.pages_crawled ?? 0;
  const queueRemaining = liveCrawlMetrics?.queue_remaining ?? 0;
  const speed = liveCrawlMetrics?.speed_pages_per_sec ?? 0;
  const elapsed = liveCrawlMetrics?.elapsed_seconds ?? 0;
  const eta = liveCrawlMetrics?.eta_seconds ?? 0;
  const currentUrl = liveCrawlMetrics?.current_url ?? "";
  const stage = liveCrawlMetrics?.stage ?? (isLoading ? "Initialising…" : "Complete");
  const unreadCount = activityLog.length;

  return (
    <>
      <div className="rounded-xl border border-primary/20 bg-card/80 backdrop-blur-md shadow-sm px-4 py-3">
        {/* Top row: status + metrics + actions */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* Pulse + stage label */}
          <div className="flex items-center gap-2 shrink-0">
            <span className="relative flex h-2.5 w-2.5">
              {isLoading && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />}
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${isLoading ? "bg-emerald-500" : "bg-muted-foreground"}`} />
            </span>
            <span className="text-xs font-semibold text-foreground">{stage}</span>
          </div>

          {/* Current URL */}
          {currentUrl && (
            <span className="text-xs text-muted-foreground font-mono truncate max-w-[220px] hidden sm:block">
              {currentUrl.replace(/^https?:\/\//, "")}
            </span>
          )}

          {/* Divider */}
          <div className="flex-1" />

          {/* Metrics chips */}
          <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0 flex-wrap">
            <span className="flex items-center gap-1">
              <Layers className="h-3.5 w-3.5 text-blue-500" />
              <strong className="text-foreground">{pagesCrawled}</strong> crawled
            </span>
            <span className="flex items-center gap-1">
              <Search className="h-3.5 w-3.5 text-amber-500" />
              <strong className="text-foreground">{queueRemaining}</strong> queued
            </span>
            <span className="flex items-center gap-1">
              <Zap className="h-3.5 w-3.5 text-emerald-500" />
              <strong className="text-foreground">{speed}</strong> p/s
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5 text-indigo-500" />
              <strong className="text-foreground">{elapsed}s</strong>
            </span>
            {isLoading && eta > 0 && (
              <span className="text-muted-foreground">ETA <strong className="text-foreground">{eta}s</strong></span>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1.5 shrink-0">
            {isLoading && activeSessionId && (
              <>
                <button
                  onClick={() => ApiService.pauseAudit(activeSessionId)}
                  title="Pause"
                  className="h-7 w-7 flex items-center justify-center rounded-md border border-border hover:bg-muted transition-colors"
                >
                  <Pause className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
                <button
                  onClick={() => ApiService.stopAudit(activeSessionId)}
                  title="Stop"
                  className="h-7 w-7 flex items-center justify-center rounded-md border border-rose-500/40 hover:bg-rose-500/10 transition-colors"
                >
                  <Square className="h-3.5 w-3.5 text-rose-500" />
                </button>
              </>
            )}
            <button
              onClick={() => window.location.reload()}
              title="Recrawl"
              className="h-7 w-7 flex items-center justify-center rounded-md border border-border hover:bg-muted transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
            <button
              onClick={() => setDrawerOpen(true)}
              title="View activity feed"
              className="relative h-7 flex items-center gap-1.5 rounded-md border border-border hover:bg-muted px-2.5 transition-colors text-xs text-muted-foreground"
            >
              <Activity className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Activity</span>
              {unreadCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-primary text-[9px] font-bold text-primary-foreground px-1">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div className="mt-2.5 space-y-1">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full transition-all duration-500 ${isLoading ? "bg-gradient-to-r from-blue-500 to-emerald-500" : "bg-emerald-500"}`}
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>{progress}%</span>
            {isLoading && <span className="text-primary font-medium">Live</span>}
          </div>
        </div>
      </div>

      <ActivityDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}

// ─── Legacy export alias (keeps dashboard import working) ──────────────────────
export function LiveCrawlPanel() {
  return <CompactCrawlBar />;
}

