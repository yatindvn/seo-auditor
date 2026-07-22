"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAudit } from "@/lib/audit-context";
import { HealthGauge } from "@/components/health-gauge";
import { IssueChart } from "@/components/issue-chart";
import { RecommendationsList } from "@/components/recommendations-list";
import { PagesTable } from "@/components/pages-table";
import { BrokenLinksTable } from "@/components/broken-links-table";
import { DuplicatesPanel } from "@/components/duplicates-panel";
import { DashboardSkeleton } from "@/components/dashboard-skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/utils";
import {
  Globe,
  AlertTriangle,
  AlertCircle,
  Link2,
  Copy,
  FileSearch,
  ArrowLeft,
  Clock,
  CheckCircle2,
  Wifi,
  Info,
} from "lucide-react";

interface StatCardProps {
  icon: React.ElementType;
  label: string;
  value: number | string;
  colorClass?: string;
  iconBg?: string;
}

function StatCard({ icon: Icon, label, value, colorClass = "text-foreground", iconBg = "bg-primary/10" }: StatCardProps) {
  return (
    <Card className="overflow-hidden">
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
            <p className={`mt-2 text-3xl font-bold tabular-nums tracking-tight ${colorClass}`}>
              {typeof value === "number" ? formatNumber(value) : value}
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

export default function DashboardPage() {
  const router = useRouter();
  const { auditData, error } = useAudit();

  useEffect(() => {
    if (!auditData && !error) {
      // If no data and we're directly on this page, redirect to home
      const timer = setTimeout(() => router.push("/"), 300);
      return () => clearTimeout(timer);
    }
  }, [auditData, error, router]);

  if (!auditData) {
    if (error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-5 p-8 text-center">
          <div className="rounded-2xl border border-rose-200 bg-rose-50/60 dark:border-rose-900/40 dark:bg-rose-950/20 p-8 max-w-md">
            <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
            <h2 className="text-lg font-bold text-rose-700 dark:text-rose-400 mb-1">Audit Failed</h2>
            <p className="text-sm text-rose-600/80 dark:text-rose-300/70">{error}</p>
          </div>
          <Button variant="outline" onClick={() => router.push("/")} className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            Back to Home
          </Button>
        </div>
      );
    }
    return <DashboardSkeleton />;
  }

  const { executive_summary: es, pages, recommendations, duplicates, broken_links, elapsed_seconds, note } = auditData;
  const { health_score, start_url, audit_date, pages_crawled, orphan_pages, broken_links: brokenCount, duplicate_titles } = es;

  const auditDate = new Date(audit_date);
  const dateStr = auditDate.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  const timeStr = auditDate.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

  const statCards: StatCardProps[] = [
    { icon: Globe, label: "Pages Crawled", value: pages_crawled, iconBg: "bg-blue-500/10" },
    { icon: AlertCircle, label: "Critical Issues", value: health_score.critical_issues, colorClass: health_score.critical_issues > 0 ? "text-rose-600 dark:text-rose-400" : "text-foreground", iconBg: "bg-rose-500/10" },
    { icon: AlertTriangle, label: "Warnings", value: health_score.warning_issues, colorClass: health_score.warning_issues > 0 ? "text-amber-600 dark:text-amber-400" : "text-foreground", iconBg: "bg-amber-500/10" },
    { icon: Link2, label: "Orphan Pages", value: orphan_pages, colorClass: orphan_pages > 0 ? "text-amber-600 dark:text-amber-400" : "text-foreground", iconBg: "bg-amber-500/10" },
    { icon: Wifi, label: "Broken Links", value: brokenCount, colorClass: brokenCount > 0 ? "text-rose-600 dark:text-rose-400" : "text-foreground", iconBg: "bg-rose-500/10" },
    { icon: Copy, label: "Duplicate Titles", value: duplicate_titles, colorClass: duplicate_titles > 0 ? "text-amber-600 dark:text-amber-400" : "text-foreground", iconBg: "bg-amber-500/10" },
  ];

  return (
    <div className="min-h-screen bg-background px-4 py-8 md:px-8 lg:px-12 xl:px-16">
      {/* ─── Back button ─── */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => router.push("/")}
        className="mb-6 gap-1.5 text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        New audit
      </Button>

      {/* ─── a) Header ─── */}
      <div className="mb-8 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2 min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            <span>{dateStr} at {timeStr}</span>
            {elapsed_seconds && (
              <>
                <span>&middot;</span>
                <span>Completed in {elapsed_seconds}s</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2 min-w-0">
            <Globe className="h-5 w-5 shrink-0 text-muted-foreground" />
            <h1 className="text-xl font-bold text-foreground truncate">
              {start_url}
            </h1>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${es.robots_txt_found ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400" : "bg-slate-50 text-slate-600 dark:bg-slate-900/30"}`}>
              {es.robots_txt_found ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
              robots.txt {es.robots_txt_found ? "found" : "missing"}
            </span>
            {es.sitemaps_found.length > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400">
                <CheckCircle2 className="h-3 w-3" />
                {es.sitemaps_found.length} sitemap{es.sitemaps_found.length > 1 ? "s" : ""} found
              </span>
            )}
          </div>
        </div>
        <div className="shrink-0">
          <HealthGauge healthScore={health_score} />
        </div>
      </div>

      {/* ─── b) Summary stat cards ─── */}
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {statCards.map((card, i) => (
          <StatCard key={i} {...card} />
        ))}
      </div>

      {/* ─── c & d) Chart + Recommendations ─── */}
      <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <FileSearch className="h-4 w-4 text-muted-foreground" />
              Issue Severity Breakdown
            </CardTitle>
          </CardHeader>
          <CardContent>
            <IssueChart healthScore={health_score} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-muted-foreground" />
              Top Recommendations
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-72 overflow-y-auto pr-1">
              <RecommendationsList recommendations={es.top_recommendations} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ─── Full Recommendations ─── */}
      {recommendations && recommendations.length > es.top_recommendations.length && (
        <Card className="mb-8">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-muted-foreground" />
              All Recommendations{" "}
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                {recommendations.length}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-96 overflow-y-auto pr-1">
              <RecommendationsList recommendations={recommendations} />
            </div>
          </CardContent>
        </Card>
      )}

      {/* ─── e) Pages table ─── */}
      {pages && pages.length > 0 && (
        <Card className="mb-8">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Globe className="h-4 w-4 text-muted-foreground" />
              Pages
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                {pages.length}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PagesTable pages={pages} />
          </CardContent>
        </Card>
      )}

      {/* ─── f) Broken links ─── */}
      <div className="mb-8">
        <BrokenLinksTable brokenLinks={broken_links} />
      </div>

      {/* ─── g) Duplicates ─── */}
      <Card className="mb-8">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Copy className="h-4 w-4 text-muted-foreground" />
            Duplicate Content Analysis
          </CardTitle>
        </CardHeader>
        <CardContent>
          <DuplicatesPanel duplicates={duplicates} />
        </CardContent>
      </Card>

      {/* ─── h) Footer note ─── */}
      {note && (
        <div className="mt-8 flex items-start gap-3 rounded-xl border border-border/60 bg-muted/30 p-4 text-xs text-muted-foreground">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-400" />
          <p className="leading-relaxed">{note}</p>
        </div>
      )}
    </div>
  );
}
