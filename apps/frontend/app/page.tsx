"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAudit } from "@/lib/audit-context";
import { ApiService } from "@/services/api";
import { buildRankTargets, countQueries, RankTargetRow } from "@/lib/rank-targets";
import {
  ChevronDown,
  Globe,
  Search,
  Shield,
  Zap,
  BarChart3,
  AlertCircle,
  Settings2,
  Clock,
  Gauge,
  Activity,
  Layers
} from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

const PRESETS = [
  {
    id: "quick",
    name: "Quick Audit",
    icon: Zap,
    pages: 25,
    depth: 2,
    desc: "Landing pages, portfolios, small sites",
    color: "text-blue-500",
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
  },
  {
    id: "standard",
    name: "Standard Audit",
    icon: BarChart3,
    pages: 100,
    depth: 4,
    desc: "Business websites, small SaaS",
    color: "text-emerald-500",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    badge: "Default"
  },
  {
    id: "deep",
    name: "Deep Audit",
    icon: Search,
    pages: 500,
    depth: 8,
    desc: "Blogs, content-heavy websites",
    color: "text-amber-500",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
  },
  {
    id: "full",
    name: "Full Site Crawl",
    icon: Globe,
    pages: 1000,
    depth: 15,
    desc: "Enterprise, ecommerce, large docs",
    color: "text-rose-500",
    bg: "bg-rose-500/10",
    border: "border-rose-500/30",
    // TEMPORARILY DISABLED.
    //
    // Near-duplicate detection is O(n^2) by design -- see the docstring on
    // `near_duplicate_content` in apps/backend/app/analysis/analysis.py:103,
    // which states it is "fine for a few hundred pages, not designed for huge
    // sites". At 5000 pages that is ~12.5 million pairwise Jaccard comparisons
    // over per-page shingle sets. Observed in production: the crawl finished in
    // 696s, then the analysis pinned a single CPU core at ~99% and never
    // returned, so /api/audit/latest kept answering 404 and the dashboard never
    // appeared. The resulting payload would also be ~100 MB of JSON, since 100
    // pages already produces 2.36 MB.
    //
    // The config above is left intact rather than deleted. To re-enable, remove
    // these two lines -- but fix the quadratic analysis first, or the same hang
    // returns.
    disabled: true,
    disabledReason: "Full Site Crawl is temporarily closed - large crawls are being optimised",
  }
];

export default function LandingPage() {
  const router = useRouter();
  const { startNewAudit, setError } = useAudit();

  const [url, setUrl] = useState("");
  const [selectedPreset, setSelectedPreset] = useState("standard");
  
  // Custom Overrides
  const [maxPages, setMaxPages] = useState(100);
  const [maxDepth, setMaxDepth] = useState(4);
  const [ignoreRobots, setIgnoreRobots] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [isCustom, setIsCustom] = useState(false);
  const [rankRows, setRankRows] = useState<RankTargetRow[]>([{ url: "", keywords: "" }]);
  
  const [isLoading, setIsLoading] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);

  // Sync preset values
  const handlePresetSelect = (presetId: string) => {
    const preset = PRESETS.find(p => p.id === presetId);
    // A disabled preset must not apply its page/depth values even if the click
    // somehow lands -- the button is also disabled in the markup below.
    if (preset && !preset.disabled) {
      setSelectedPreset(presetId);
      setMaxPages(preset.pages);
      setMaxDepth(preset.depth);
      setIsCustom(false);
    }
  };

  const handleCustomChange = (type: 'pages' | 'depth', val: number) => {
    setIsCustom(true);
    setSelectedPreset("custom");
    if (type === 'pages') setMaxPages(val);
    if (type === 'depth') setMaxDepth(val);
  };

  // Dynamic Estimations
  const estimation = useMemo(() => {
    let pages = maxPages;
    let timeRaw = (pages * 0.8) + (maxDepth * 1.5); // heuristic
    let timeStr = "";
    if (timeRaw < 60) timeStr = `< 1 min`;
    else if (timeRaw < 180) timeStr = `1–3 mins`;
    else if (timeRaw < 900) timeStr = `5–15 mins`;
    else timeStr = `15+ mins`;

    let usage = "Low";
    let complexity = "fast";
    if (pages > 2500) { usage = "High"; complexity = "enterprise"; }
    else if (pages >= 500) { usage = "High"; complexity = "deep"; }
    else if (pages >= 100) { usage = "Medium"; complexity = "standard"; }

    return { pages, timeStr, usage, complexity };
  }, [maxPages, maxDepth]);

  const rankQueryCount = useMemo(() => countQueries(rankRows), [rankRows]);

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
    setError(null);

    try {
      const rankTargets = buildRankTargets(rankRows);
      const data = await ApiService.runAudit({
        url: url.trim(),
        // Mirrors MAX_PAGES_LIMIT in apps/backend/app/schemas/schemas.py; above it
        // the API returns 422, and beyond ~1000 pages the audit cannot finish usefully.
        max_pages: Math.min(Math.max(maxPages, 1), 1000),
        max_depth: Math.min(Math.max(maxDepth, 0), 15),
        ignore_robots: ignoreRobots,
        ...(rankTargets.length > 0 && {
          rank_targets: rankTargets,
          enable_rank_check: true,
          enable_keyword_suggestions: true,
        }),
      });

      startNewAudit(data.session_id);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err?.message || "An unexpected error occurred.");
    } finally {
      setIsLoading(false);
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
      <div className="mb-8 max-w-3xl text-center">
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border/80 bg-card/80 px-4 py-2 text-xs font-semibold text-muted-foreground shadow-sm backdrop-blur-md">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse-slow" />
          Technical SEO · Accessibility · Performance · Security
        </div>
        <h1 className="mb-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
          SEO{" "}
          <span className="bg-gradient-to-r from-primary to-blue-600 bg-clip-text text-transparent">
            Auditor
          </span>
        </h1>
        <p className="text-lg text-muted-foreground sm:text-xl">
          Enterprise-grade Website SEO Auditing Platform. Analyze architecture, performance, and compliance in real-time.
        </p>
      </div>

      <div className="w-full max-w-2xl rounded-3xl border border-border/60 bg-card/50 p-6 shadow-2xl backdrop-blur-xl sm:p-8">
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="space-y-2">
            <label className="text-sm font-semibold text-foreground">Target URL</label>
            <div className="relative">
              <Search className="absolute left-3.5 top-3.5 h-5 w-5 text-muted-foreground" />
              <Input
                type="text"
                placeholder="https://example.com"
                className={`h-12 w-full rounded-xl bg-background pl-11 text-base shadow-inner ${urlError ? "border-rose-500 ring-rose-500/20" : ""}`}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={isLoading}
              />
            </div>
            {urlError && <p className="text-xs text-rose-500 mt-1 flex items-center gap-1"><AlertCircle className="h-3 w-3" /> {urlError}</p>}
          </div>

          <div className="space-y-3">
            <label className="text-sm font-semibold text-foreground flex items-center justify-between">
              Crawl Configuration
              {isCustom && <span className="text-[10px] uppercase font-bold text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded">Custom Mode</span>}
            </label>
            
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => handlePresetSelect(p.id)}
                  disabled={isLoading || p.disabled}
                  aria-disabled={p.disabled || undefined}
                  // Native title rather than a tooltip component: this repo has no
                  // tooltip primitive in components/ui, and title works on hover
                  // for a disabled button without adding a dependency.
                  title={p.disabled ? p.disabledReason : undefined}
                  className={`relative flex flex-col items-center justify-center gap-2 rounded-xl border p-4 transition-all text-center ${
                    p.disabled
                      ? 'border-border/40 bg-muted/10 opacity-50 cursor-not-allowed'
                      : selectedPreset === p.id
                        ? `${p.border} ${p.bg} ring-2 ring-primary/20 shadow-md`
                        : 'border-border/60 bg-muted/20 hover:bg-muted/40 hover:border-border'
                  }`}
                >
                  {p.badge && !p.disabled && (
                    <span className="absolute -top-2 -right-2 bg-primary text-primary-foreground text-[9px] font-bold px-1.5 py-0.5 rounded-sm shadow-sm">
                      {p.badge}
                    </span>
                  )}
                  {p.disabled && (
                    <span className="absolute -top-2 -right-2 bg-muted-foreground/80 text-background text-[9px] font-bold px-1.5 py-0.5 rounded-sm shadow-sm">
                      Temporarily closed
                    </span>
                  )}
                  <p.icon className={`h-6 w-6 ${selectedPreset === p.id ? p.color : 'text-muted-foreground'}`} />
                  <div className="space-y-0.5">
                    <p className={`text-xs font-bold ${selectedPreset === p.id ? 'text-foreground' : 'text-muted-foreground'}`}>{p.name}</p>
                    <p className="text-[9px] text-muted-foreground leading-tight hidden sm:block">{p.desc}</p>
                  </div>
                </button>
              ))}
            </div>

            {selectedPreset === "full" && (
              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 flex items-start gap-3 mt-2 text-rose-600 dark:text-rose-400">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <p className="text-xs leading-relaxed font-medium">
                  <strong>Enterprise Warning:</strong> Full Site Crawls can execute up to 5,000 pages and take significant backend processing time and memory.
                </p>
              </div>
            )}

            <div className="rounded-xl border border-border/60 bg-muted/20 p-4 mt-4 grid grid-cols-3 divide-x divide-border/60">
              <div className="flex flex-col items-center justify-center px-2">
                <span className="text-[10px] uppercase font-semibold text-muted-foreground flex items-center gap-1 mb-1"><Layers className="h-3 w-3" /> Estimated Pages</span>
                <span className="text-base font-bold tabular-nums">~{estimation.pages}</span>
              </div>
              <div className="flex flex-col items-center justify-center px-2">
                <span className="text-[10px] uppercase font-semibold text-muted-foreground flex items-center gap-1 mb-1"><Clock className="h-3 w-3" /> Estimated Time</span>
                <span className="text-base font-bold">{estimation.timeStr}</span>
              </div>
              <div className="flex flex-col items-center justify-center px-2">
                <span className="text-[10px] uppercase font-semibold text-muted-foreground flex items-center gap-1 mb-1"><Activity className="h-3 w-3" /> Resource Usage</span>
                <span className={`text-sm font-bold capitalize
                  ${estimation.usage === 'High' ? 'text-rose-500' : estimation.usage === 'Medium' ? 'text-amber-500' : 'text-emerald-500'}
                `}>
                  {estimation.usage}
                </span>
              </div>
            </div>
          </div>

          <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen} className="rounded-xl border border-border/60 bg-muted/10 overflow-hidden">
            <CollapsibleTrigger asChild>
              <button type="button" className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/30 transition-colors">
                <span className="flex items-center gap-2"><Settings2 className="h-4 w-4 text-muted-foreground" /> Advanced Overrides</span>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${advancedOpen ? "rotate-180" : ""}`} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="space-y-5 px-4 pb-5 pt-2 border-t border-border/40">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-muted-foreground flex justify-between">
                      Max Pages <span>{maxPages}</span>
                    </label>
                    <input 
                      type="range" 
                      min="10" max="1000" step="10"
                      value={maxPages} 
                      onChange={(e) => handleCustomChange('pages', parseInt(e.target.value))}
                      className="w-full accent-primary" 
                    />
                    <div className="flex justify-between text-[9px] text-muted-foreground px-1">
                      <span>10</span><span>500</span><span>1000</span>
                    </div>
                  </div>
                  
                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-muted-foreground flex justify-between">
                      Max Crawl Depth <span>{maxDepth}</span>
                    </label>
                    <input 
                      type="range" 
                      min="1" max="15" step="1"
                      value={maxDepth} 
                      onChange={(e) => handleCustomChange('depth', parseInt(e.target.value))}
                      className="w-full accent-primary" 
                    />
                    <div className="flex justify-between text-[9px] text-muted-foreground px-1">
                      <span>1</span><span>8</span><span>15</span>
                    </div>
                  </div>
                </div>

                <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border/50 bg-muted/20 p-3 hover:bg-muted/40 transition-colors">
                  <input
                    type="checkbox"
                    checked={ignoreRobots}
                    onChange={(e) => setIgnoreRobots(e.target.checked)}
                    className="h-4 w-4 rounded border-input bg-background text-primary focus:ring-primary"
                    disabled={isLoading}
                  />
                  <div>
                    <p className="text-sm font-semibold">Ignore robots.txt</p>
                    <p className="text-xs text-muted-foreground">Force crawl paths blocked by robots.txt (for staging environments)</p>
                  </div>
                </label>

                <div className="space-y-3 rounded-lg border border-border/50 bg-muted/20 p-3">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold">Keyword rank tracking</p>
                    <span
                      role="status"
                      aria-live="polite"
                      className={`text-xs ${rankQueryCount > 100 ? "text-rose-500 font-semibold" : "text-muted-foreground"}`}
                    >
                      will use {rankQueryCount} of your 100 daily queries
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Only the pages you list here are rank-checked. Requires Google CSE credentials in apps/backend/.env.
                  </p>
                  {rankRows.map((row, i) => (
                    <div key={i} className="flex gap-2">
                      <Input
                        placeholder="https://example.com/services"
                        aria-label={`Rank-tracked page URL ${i + 1}`}
                        value={row.url}
                        onChange={e => setRankRows(rows => rows.map((r, j) => j === i ? { ...r, url: e.target.value } : r))}
                        disabled={isLoading}
                        className="flex-1"
                      />
                      <Input
                        placeholder="keyword one, keyword two"
                        aria-label={`Keywords for page ${i + 1}, comma-separated`}
                        value={row.keywords}
                        onChange={e => setRankRows(rows => rows.map((r, j) => j === i ? { ...r, keywords: e.target.value } : r))}
                        disabled={isLoading}
                        className="flex-1"
                      />
                      <Button
                        type="button" variant="ghost" size="sm"
                        aria-label={`Remove rank-tracked page ${i + 1}`}
                        onClick={() => setRankRows(rows => rows.length > 1 ? rows.filter((_, j) => j !== i) : rows)}
                        disabled={isLoading}
                      >
                        Remove
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button" variant="outline" size="sm"
                    onClick={() => setRankRows(rows => [...rows, { url: "", keywords: "" }])}
                    disabled={isLoading}
                  >
                    Add page
                  </Button>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>

          <Button
            type="submit"
            className="h-14 w-full text-base font-bold shadow-lg transition-all hover:scale-[1.02] active:scale-[0.98] gap-2 rounded-xl group relative overflow-hidden"
            disabled={isLoading}
          >
            <div className="absolute inset-0 bg-gradient-to-r from-primary/0 via-white/10 to-primary/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000" />
            {isLoading ? (
              <span className="flex items-center gap-2">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                Initializing Session...
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <Gauge className="h-5 w-5" />
                Start SEO Audit
              </span>
            )}
          </Button>
        </form>
      </div>

      <div className="mt-16 grid w-full max-w-5xl grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4 px-4">
        {features.map((f, i) => (
          <div key={i} className="flex flex-col items-center text-center p-4">
            <div className="mb-4 rounded-2xl bg-primary/10 p-3">
              <f.icon className="h-6 w-6 text-primary" />
            </div>
            <h3 className="mb-2 font-semibold">{f.label}</h3>
            <p className="text-sm text-muted-foreground">{f.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
