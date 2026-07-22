"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useAudit } from "@/lib/audit-context";
import {
  ChevronDown,
  Globe,
  Search,
  Shield,
  Zap,
  BarChart3,
  AlertCircle,
  Settings2,
} from "lucide-react";

const CRAWL_STAGES = [
  "Connecting to website…",
  "Parsing robots.txt & sitemap…",
  "Crawling pages…",
  "Analyzing SEO signals…",
  "Scoring health metrics…",
  "Compiling recommendations…",
  "Finalizing report…",
];

export default function LandingPage() {
  const router = useRouter();
  const { setAuditData, setError } = useAudit();

  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(8);
  const [maxDepth, setMaxDepth] = useState(1);
  const [ignoreRobots, setIgnoreRobots] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [stageIdx, setStageIdx] = useState(0);
  const [urlError, setUrlError] = useState<string | null>(null);

  const validateUrl = (value: string): boolean => {
    if (!value.trim()) {
      setUrlError("Please enter a URL to audit.");
      return false;
    }
    setUrlError(null);
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateUrl(url)) return;

    setIsLoading(true);
    setStageIdx(0);
    setError(null);

    // Stage ticker
    const stageInterval = setInterval(() => {
      setStageIdx((prev) => Math.min(prev + 1, CRAWL_STAGES.length - 1));
    }, 5500);

    try {
      const res = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url.trim(),
          max_pages: Math.min(Math.max(maxPages, 1), 15),
          max_depth: Math.min(Math.max(maxDepth, 0), 2),
          ignore_robots: ignoreRobots,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data?.detail || `Request failed with status ${res.status}`);
      }

      setAuditData(data);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err?.message || "An unexpected error occurred.");
      setIsLoading(false);
    } finally {
      clearInterval(stageInterval);
    }
  };

  const features = [
    { icon: Globe, label: "Full Site Crawl", desc: "BFS crawl across all internal pages" },
    { icon: Shield, label: "Security Checks", desc: "HSTS, CSP, and header audits" },
    { icon: Zap, label: "Performance Proxies", desc: "TTFB, DOM size, render-blocking resources" },
    { icon: BarChart3, label: "Health Score", desc: "Weighted score from 0–100 with grade" },
  ];

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-16 bg-gradient-to-b from-background via-background to-muted/30">
      {/* Hero */}
      <div className="mb-12 max-w-3xl text-center">
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border/80 bg-card/80 px-4 py-2 text-xs font-semibold text-muted-foreground shadow-sm backdrop-blur-md">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse-slow" />
          Technical SEO · Accessibility · Performance · Security
        </div>
        <h1 className="mb-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
          SEO{" "}
          <span className="bg-gradient-to-r from-blue-600 to-cyan-500 bg-clip-text text-transparent">
            Auditor
          </span>
        </h1>
        <p className="text-base leading-relaxed text-muted-foreground sm:text-lg max-w-xl mx-auto">
          Deep crawl any website and get a prioritized, actionable SEO health
          report in under 60 seconds — no account required.
        </p>
      </div>

      {/* Input Card */}
      <div className="w-full max-w-2xl">
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-border/80 bg-card/95 p-6 shadow-glass backdrop-blur-apple"
        >
          {isLoading ? (
            /* Loading State */
            <div className="space-y-5">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Search className="h-4 w-4 text-primary animate-pulse" />
                  <span className="text-sm font-semibold text-foreground">
                    Auditing{" "}
                    <span className="text-primary max-w-[200px] truncate inline-block align-bottom">
                      {url}
                    </span>
                  </span>
                </div>
                <span className="text-xs text-muted-foreground">
                  This may take 10–45 seconds
                </span>
              </div>
              <div className="rounded-xl border border-primary/10 bg-primary/5 px-4 py-3 text-sm text-primary font-medium transition-all">
                {CRAWL_STAGES[stageIdx]}
              </div>
              <div className="grid grid-cols-3 gap-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 rounded-xl" style={{ animationDelay: `${i * 0.1}s` }} />
                ))}
              </div>
              <Skeleton className="h-6 w-3/4 mx-auto rounded-lg" />
              <p className="text-center text-xs text-muted-foreground">
                Crawling up to {maxPages} pages, depth {maxDepth}…
              </p>
            </div>
          ) : (
            /* Input Form */
            <div className="space-y-4">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Globe className="absolute left-3.5 top-3.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="url-input"
                    type="text"
                    placeholder="https://example.com"
                    value={url}
                    onChange={(e) => {
                      setUrl(e.target.value);
                      if (urlError) setUrlError(null);
                    }}
                    className="pl-10 h-12 text-base"
                    autoFocus
                    disabled={isLoading}
                  />
                </div>
                <Button
                  type="submit"
                  variant="apple"
                  size="lg"
                  className="h-12 px-6 text-sm font-semibold"
                  disabled={isLoading}
                >
                  <Search className="mr-2 h-4 w-4" />
                  Audit
                </Button>
              </div>

              {urlError && (
                <div className="flex items-center gap-2 rounded-xl bg-rose-50 dark:bg-rose-950/20 px-3 py-2 text-xs text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/40">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                  {urlError}
                </div>
              )}

              {/* Advanced Options */}
              <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
                <CollapsibleTrigger className="flex w-full items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors py-1">
                  <Settings2 className="h-3.5 w-3.5" />
                  Advanced options
                  <ChevronDown
                    className={`ml-auto h-3.5 w-3.5 transition-transform ${advancedOpen ? "rotate-180" : ""}`}
                  />
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-3 rounded-xl border border-border/60 bg-muted/30 p-4">
                  <div className="grid gap-4 sm:grid-cols-3">
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-foreground/80">
                        Max Pages{" "}
                        <span className="font-normal text-muted-foreground">(1–15)</span>
                      </label>
                      <Input
                        type="number"
                        min={1}
                        max={15}
                        value={maxPages}
                        onChange={(e) =>
                          setMaxPages(Math.min(15, Math.max(1, Number(e.target.value))))
                        }
                        className="h-9 text-sm"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-foreground/80">
                        Max Depth{" "}
                        <span className="font-normal text-muted-foreground">(0–2)</span>
                      </label>
                      <Input
                        type="number"
                        min={0}
                        max={2}
                        value={maxDepth}
                        onChange={(e) =>
                          setMaxDepth(Math.min(2, Math.max(0, Number(e.target.value))))
                        }
                        className="h-9 text-sm"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-foreground/80">
                        Ignore robots.txt
                      </label>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={ignoreRobots}
                        onClick={() => setIgnoreRobots((v) => !v)}
                        className={`relative inline-flex h-9 w-full items-center justify-start gap-2 rounded-xl border px-3 text-xs font-medium transition-all ${
                          ignoreRobots
                            ? "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-400"
                            : "border-border/60 bg-background text-muted-foreground hover:bg-muted/30"
                        }`}
                      >
                        <span
                          className={`h-4 w-4 rounded-full border-2 transition-all ${
                            ignoreRobots
                              ? "border-amber-500 bg-amber-500"
                              : "border-muted-foreground/40 bg-transparent"
                          }`}
                        />
                        {ignoreRobots ? "Yes — ignore robots.txt" : "No — respect robots.txt"}
                      </button>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          )}
        </form>

        <p className="mt-3 text-center text-xs text-muted-foreground">
          Free & stateless — no account, no data storage.
        </p>
      </div>

      {/* Feature Pills */}
      <div className="mt-12 grid grid-cols-2 gap-3 sm:grid-cols-4 max-w-2xl w-full">
        {features.map((f, i) => (
          <div
            key={i}
            className="flex items-start gap-3 rounded-xl border border-border/60 bg-card/60 p-3.5 shadow-sm backdrop-blur-sm"
          >
            <div className="rounded-lg bg-primary/10 p-2">
              <f.icon className="h-4 w-4 text-primary" />
            </div>
            <div>
              <p className="text-xs font-semibold text-foreground">{f.label}</p>
              <p className="text-[10px] leading-relaxed text-muted-foreground">{f.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
