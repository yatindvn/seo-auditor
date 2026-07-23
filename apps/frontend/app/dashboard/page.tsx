"use client";

import React, { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { ApiService } from "@/services/api";
import { useAudit } from "@/lib/audit-context";
import { useKeyboardShortcuts, useCountUp } from "@/hooks/use-ux";
import { HealthGauge } from "@/components/health-gauge";
import { DashboardSkeleton } from "@/components/dashboard-skeleton";
import { LiveCrawlPanel } from "@/components/live-crawl-panel";
import { PageExplorerDrawer } from "@/components/page-explorer-drawer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/utils";
import {
  Globe, AlertTriangle, AlertCircle, Link2, Copy, ArrowLeft, Clock,
  CheckCircle2, Wifi, Info, Download, LayoutDashboard, Search as SearchIcon, EyeOff, MoveUp, MoveDown, Columns
} from "lucide-react";

// Lazy Load Heavy Components for Performance
const IssueChart = dynamic(() => import("@/components/issue-chart").then(m => m.IssueChart));
const RecommendationsList = dynamic(() => import("@/components/recommendations-list").then(m => m.RecommendationsList));
const PagesTable = dynamic(() => import("@/components/pages-table").then(m => m.PagesTable));
const BrokenLinksTable = dynamic(() => import("@/components/broken-links-table").then(m => m.BrokenLinksTable));
const DuplicatesPanel = dynamic(() => import("@/components/duplicates-panel").then(m => m.DuplicatesPanel));
const SiteArchitectureGraph = dynamic(() => import("@/components/site-architecture-graph").then(m => m.SiteArchitectureGraph));
const IssueCenter = dynamic(() => import("@/components/issue-center").then(m => m.IssueCenter));
const ScoreBreakdownCard = dynamic(() => import("@/components/score-breakdown-card").then(m => m.ScoreBreakdownCard));
const HistoricalComparisonPanel = dynamic(() => import("@/components/historical-comparison-panel").then(m => m.HistoricalComparisonPanel));
const OrphanPagesPanel = dynamic(() => import("@/components/orphan-pages-panel").then(m => m.OrphanPagesPanel));
const DeadEndPagesPanel = dynamic(() => import("@/components/dead-end-pages-panel").then(m => m.DeadEndPagesPanel));
const HubAnalysisPanel = dynamic(() => import("@/components/hub-analysis-panel").then(m => m.HubAnalysisPanel));
const CrawlDepthPanel = dynamic(() => import("@/components/crawl-depth-panel").then(m => m.CrawlDepthPanel));
const TechnicalSeoPanel = dynamic(() => import("@/components/technical-seo-panel").then(m => m.TechnicalSeoPanel));
const LinkAnalysisPanel = dynamic(() => import("@/components/link-analysis-panel").then(m => m.LinkAnalysisPanel));
const RedirectAnalysisPanel = dynamic(() => import("@/components/redirect-analysis-panel").then(m => m.RedirectAnalysisPanel));
const PerformancePanel = dynamic(() => import("@/components/performance-panel").then(m => m.PerformancePanel));
const SecurityAccessibilityPanel = dynamic(() => import("@/components/security-accessibility-panel").then(m => m.SecurityAccessibilityPanel));

function StatCard({ icon: Icon, label, value, colorClass = "text-foreground", iconBg = "bg-primary/10" }: any) {
  const isNumber = typeof value === "number";
  const animatedValue = useCountUp(isNumber ? value : 0, 1500);
  
  return (
    <Card className="overflow-hidden">
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
            <p className={`mt-2 text-3xl font-bold tabular-nums tracking-tight ${colorClass}`}>
              {isNumber ? formatNumber(animatedValue) : value}
            </p>
          </div>
          <div className={`rounded-xl p-2.5 ${iconBg}`}>
            <Icon className="h-5 w-5 text-primary" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Widget Configuration
const DEFAULT_LAYOUT = [
  { id: "score-breakdown", width: "full", visible: true },
  { id: "history", width: "full", visible: true },
  { id: "issue-center", width: "full", visible: true },
  { id: "architecture", width: "full", visible: true },
  { id: "orphan-deadend", width: "full", visible: true },
  { id: "hub", width: "full", visible: true },
  { id: "depth", width: "full", visible: true },
  { id: "issues-grid", width: "full", visible: true },
  { id: "broken-links", width: "full", visible: true },
  { id: "tech-seo", width: "full", visible: true },
  { id: "links", width: "full", visible: true },
  { id: "redirects", width: "full", visible: true },
  { id: "performance", width: "full", visible: true },
  { id: "security", width: "full", visible: true },
  { id: "duplicates", width: "full", visible: true },
  { id: "pages-table", width: "full", visible: true },
];

export default function DashboardPage() {
  const router = useRouter();
  const { auditData, error, isLoading, activeSessionId } = useAudit();
  
  const [isEditMode, setIsEditMode] = useState(false);
  const [layout, setLayout] = useState(DEFAULT_LAYOUT);
  const [searchOpen, setSearchOpen] = useState(false);
  
  // UX Hooks
  useKeyboardShortcuts(
    () => setSearchOpen(prev => !prev),
    () => { if (activeSessionId) ApiService.downloadExport('csv', activeSessionId) }
  );

  useEffect(() => {
    const saved = localStorage.getItem("seo_dashboard_layout");
    if (saved) setLayout(JSON.parse(saved));
  }, []);

  useEffect(() => {
    if (!auditData && !error && !isLoading) {
      const timer = setTimeout(() => router.push("/"), 300);
      return () => clearTimeout(timer);
    }
  }, [auditData, error, isLoading, router]);

  if (!auditData && isLoading) {
    return (
      <div className="min-h-screen bg-background px-4 py-8 md:px-8 lg:px-12 space-y-6">
        <Button variant="ghost" size="sm" onClick={() => router.push("/")} className="gap-1.5 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Cancel Audit
        </Button>
        <LiveCrawlPanel />
      </div>
    );
  }

  if (!auditData) {
    if (error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-5 p-8 text-center">
          <div className="rounded-2xl border border-rose-200 bg-rose-50/60 p-8 max-w-md">
            <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
            <h2 className="text-lg font-bold text-rose-700 mb-1">Audit Failed</h2>
            <p className="text-sm text-rose-600/80">{error}</p>
          </div>
          <Button variant="outline" onClick={() => router.push("/")} className="gap-2"><ArrowLeft className="h-4 w-4" /> Back to Home</Button>
        </div>
      );
    }
    return <DashboardSkeleton />;
  }

  const { executive_summary: es, pages, recommendations, duplicates, broken_links, elapsed_seconds, note } = auditData;
  const { health_score, start_url, audit_date, pages_crawled, orphan_pages, broken_links: brokenCount, duplicate_titles } = es;

  const statCards = [
    { icon: Globe, label: "Pages Crawled", value: pages_crawled, iconBg: "bg-blue-500/10" },
    { icon: AlertCircle, label: "Critical Issues", value: health_score.critical_issues, colorClass: health_score.critical_issues > 0 ? "text-rose-600" : "text-foreground", iconBg: "bg-rose-500/10" },
    { icon: AlertTriangle, label: "Warnings", value: health_score.warning_issues, colorClass: health_score.warning_issues > 0 ? "text-amber-600" : "text-foreground", iconBg: "bg-amber-500/10" },
    { icon: Link2, label: "Orphan Pages", value: orphan_pages, colorClass: orphan_pages > 0 ? "text-amber-600" : "text-foreground", iconBg: "bg-amber-500/10" },
    { icon: Wifi, label: "Broken Links", value: brokenCount, colorClass: brokenCount > 0 ? "text-rose-600" : "text-foreground", iconBg: "bg-rose-500/10" },
    { icon: Copy, label: "Duplicate Titles", value: duplicate_titles, colorClass: duplicate_titles > 0 ? "text-amber-600" : "text-foreground", iconBg: "bg-amber-500/10" },
  ];

  // Layout Engine Helpers
  const moveWidget = (index: number, direction: 1 | -1) => {
    const newLayout = [...layout];
    const targetIdx = index + direction;
    if (targetIdx >= 0 && targetIdx < newLayout.length) {
      [newLayout[index], newLayout[targetIdx]] = [newLayout[targetIdx], newLayout[index]];
      setLayout(newLayout);
    }
  };
  const toggleVisibility = (index: number) => {
    const newLayout = [...layout];
    newLayout[index].visible = !newLayout[index].visible;
    setLayout(newLayout);
  };
  const toggleWidth = (index: number) => {
    const newLayout = [...layout];
    newLayout[index].width = newLayout[index].width === "full" ? "half" : "full";
    setLayout(newLayout);
  };
  const saveLayout = () => {
    localStorage.setItem("seo_dashboard_layout", JSON.stringify(layout));
    setIsEditMode(false);
  };
  const resetLayout = () => {
    setLayout(DEFAULT_LAYOUT);
    localStorage.removeItem("seo_dashboard_layout");
  };

  const WidgetWrapper = ({ id, children }: { id: string, children: React.ReactNode }) => {
    const index = layout.findIndex(l => l.id === id);
    const config = layout[index];
    if (!config) return null;
    if (!config.visible && !isEditMode) return null;
    
    return (
      <div className={`relative transition-all duration-300 ${config.width === 'half' ? 'col-span-1' : 'col-span-1 md:col-span-2'} ${!config.visible ? 'opacity-40 grayscale' : ''}`}>
        {isEditMode && (
          <div className="absolute -top-3 -right-3 z-10 flex items-center gap-1 bg-card border border-border shadow-md rounded-lg p-1">
            <button onClick={() => moveWidget(index, -1)} className="p-1.5 hover:bg-muted rounded"><MoveUp className="h-3 w-3" /></button>
            <button onClick={() => moveWidget(index, 1)} className="p-1.5 hover:bg-muted rounded"><MoveDown className="h-3 w-3" /></button>
            <button onClick={() => toggleWidth(index)} className="p-1.5 hover:bg-muted rounded"><Columns className="h-3 w-3" /></button>
            <button onClick={() => toggleVisibility(index)} className="p-1.5 hover:bg-muted rounded"><EyeOff className="h-3 w-3" /></button>
          </div>
        )}
        <div className={`${isEditMode ? 'ring-2 ring-primary/50 rounded-2xl pointer-events-none' : ''}`}>
          {children}
        </div>
      </div>
    );
  };

  const widgetComponents: Record<string, React.ReactNode> = {
    "score-breakdown": <ScoreBreakdownCard />,
    "history": <HistoricalComparisonPanel />,
    "issue-center": <IssueCenter />,
    "architecture": <SiteArchitectureGraph />,
    "orphan-deadend": (
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <OrphanPagesPanel analysis={auditData.site_wide_analysis} />
        <DeadEndPagesPanel analysis={auditData.site_wide_analysis} />
      </div>
    ),
    "hub": <HubAnalysisPanel analysis={auditData.site_wide_analysis} pages={pages} />,
    "depth": <CrawlDepthPanel analysis={auditData.site_wide_analysis} pages={pages} />,
    "issues-grid": (
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card><CardHeader className="pb-3"><CardTitle className="text-base">Issue Severity Breakdown</CardTitle></CardHeader><CardContent><IssueChart healthScore={health_score} /></CardContent></Card>
        <Card><CardHeader className="pb-3"><CardTitle className="text-base">Top Recommendations</CardTitle></CardHeader><CardContent><div className="max-h-72 overflow-y-auto"><RecommendationsList recommendations={es.top_recommendations} /></div></CardContent></Card>
      </div>
    ),
    "broken-links": <BrokenLinksTable brokenLinks={broken_links} />,
    "tech-seo": <Card><CardContent className="pt-6"><TechnicalSeoPanel es={es} pages={pages} /></CardContent></Card>,
    "links": <LinkAnalysisPanel pages={pages} es={es} />,
    "redirects": <RedirectAnalysisPanel pages={pages} es={es} />,
    "performance": <PerformancePanel pages={pages} />,
    "security": <SecurityAccessibilityPanel pages={pages} />,
    "duplicates": <Card><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-base"><Copy className="h-4 w-4"/>Duplicate Content Analysis</CardTitle></CardHeader><CardContent><DuplicatesPanel duplicates={duplicates} /></CardContent></Card>,
    "pages-table": <Card><CardHeader className="pb-3"><CardTitle className="text-base">All Crawled Pages</CardTitle></CardHeader><CardContent><PagesTable pages={pages} /></CardContent></Card>,
  };

  return (
    <div className="min-h-screen bg-background space-y-8 pb-12">
      {/* ─── Global Search Overlay ─── */}
      {searchOpen && (
        <div className="fixed inset-0 z-[100] flex items-start justify-center pt-20 bg-background/80 backdrop-blur-sm" onClick={() => setSearchOpen(false)}>
          <div className="w-full max-w-2xl bg-card border border-border shadow-2xl rounded-xl p-4 animate-in fade-in zoom-in-95" onClick={e => e.stopPropagation()}>
            <div className="relative">
              <SearchIcon className="absolute left-3 top-3.5 h-5 w-5 text-muted-foreground" />
              <input autoFocus type="text" placeholder="Search pages, issues, or metrics (Cmd+K)..." className="w-full bg-transparent text-lg outline-none pl-11 pr-4 py-3" />
            </div>
            <p className="text-xs text-muted-foreground mt-4 text-center">Global search is simulated in this prototype.</p>
          </div>
        </div>
      )}

      {/* ─── Sticky Toolbar ─── */}
      <div className="sticky top-0 z-40 bg-background/95 backdrop-blur-md border-b border-border/40 px-4 py-3 md:px-8 lg:px-12 xl:px-16 flex flex-wrap items-center justify-between gap-4">
        <Button variant="ghost" size="sm" onClick={() => router.push("/")} className="gap-1.5 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> New audit
        </Button>
        <div className="flex items-center gap-2">
          {isEditMode ? (
            <>
              <Button variant="outline" size="sm" onClick={resetLayout} className="text-rose-500">Reset</Button>
              <Button size="sm" onClick={saveLayout} className="gap-1.5">Save Layout</Button>
            </>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => setIsEditMode(true)} className="gap-1.5 text-xs">
              <LayoutDashboard className="h-3.5 w-3.5" /> Edit Layout
            </Button>
          )}
          
          <div className="h-4 w-[1px] bg-border/60 mx-1" />
          <Button variant="outline" size="sm" onClick={() => activeSessionId && ApiService.downloadExport('csv', activeSessionId)} className="gap-1.5 text-xs text-muted-foreground"><Download className="h-3.5 w-3.5" /> CSV</Button>
          <Button variant="outline" size="sm" onClick={() => activeSessionId && ApiService.downloadExport('pdf', activeSessionId)} className="gap-1.5 text-xs text-muted-foreground"><Download className="h-3.5 w-3.5" /> PDF</Button>
          <Button variant="outline" size="sm" onClick={() => activeSessionId && ApiService.downloadExport('json', activeSessionId)} className="gap-1.5 text-xs text-muted-foreground"><Download className="h-3.5 w-3.5" /> JSON</Button>
        </div>
      </div>

      <div className="px-4 md:px-8 lg:px-12 xl:px-16 space-y-8">
        <LiveCrawlPanel />

        {/* ─── Header ─── */}
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2 min-w-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>{new Date(audit_date).toLocaleString()}</span>
              {elapsed_seconds && <span>&middot; Completed in {elapsed_seconds}s</span>}
            </div>
            <div className="flex items-center gap-2 min-w-0">
              <Globe className="h-5 w-5 shrink-0 text-muted-foreground" />
              <h1 className="text-xl font-bold text-foreground truncate">{start_url}</h1>
            </div>
          </div>
          <div className="shrink-0">
            <HealthGauge healthScore={health_score} />
          </div>
        </div>

        {/* ─── Summary stat cards ─── */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {statCards.map((card, i) => <StatCard key={i} {...card} />)}
        </div>

        {/* ─── Dynamic Layout Grid ─── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {layout.map((config) => (
            <WidgetWrapper key={config.id} id={config.id}>
              {widgetComponents[config.id]}
            </WidgetWrapper>
          ))}
        </div>

        <PageExplorerDrawer />

        {note && (
          <div className="mt-8 flex items-start gap-3 rounded-xl border border-border/60 bg-muted/30 p-4 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-400" />
            <p className="leading-relaxed">{note}</p>
          </div>
        )}
      </div>
    </div>
  );
}
