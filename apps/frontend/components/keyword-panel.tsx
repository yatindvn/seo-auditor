"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Search, TrendingUp, Lightbulb, AlertTriangle } from "lucide-react";
import { PageItem } from "@/lib/types";
import type { RankTarget } from "@seo-auditor/shared";

interface KeywordPanelProps {
  pages: PageItem[];
  rankTargets?: RankTarget[];
}

/**
 * Mirrors apps/backend/app/seo/rank_checker.py's _normalize_url exactly:
 * strip fragment, then query string, then scheme, then a leading "www.",
 * then any trailing slash. The frontend and backend are answering the same
 * "was this URL reached?" question about the same URLs, so they must agree —
 * otherwise a page the backend successfully rank-checked (e.g. crawled with a
 * tracking query string the user's nominated URL doesn't have) gets reported
 * here as never reached by the crawl.
 */
function normalizeUrl(url: string): string {
  return url
    .split("#")[0]
    .split("?")[0]
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/\/$/, "");
}

export function KeywordPanel({ pages, rankTargets }: KeywordPanelProps) {
  const pagesWithKeywords = pages.filter(
    p => p.keyword_analysis && p.keyword_analysis.top_keywords.length > 0
  );

  const skippedNote = pagesWithKeywords
    .flatMap(p => p.keyword_analysis?.rankings || [])
    .find(r => r.status === "skipped")?.note;

  if (pagesWithKeywords.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4 text-muted-foreground" />
            Keyword Intelligence
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No keyword data available for this audit.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {skippedNote && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2.5 text-xs text-amber-600">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {skippedNote}
        </div>
      )}
      {(() => {
        const crawled = new Set(pages.map(p => normalizeUrl(p.url)));
        const missed = (rankTargets || [])
          .map(t => normalizeUrl(t.url))
          .filter(u => !crawled.has(u));
        if (missed.length === 0) return null;
        return (
          <div className="rounded-lg border border-border/50 bg-muted/20 px-4 py-2.5 text-xs text-muted-foreground">
            Not reached by this crawl (try a higher max depth, or check robots.txt): {missed.join(", ")}
          </div>
        );
      })()}
      {pagesWithKeywords.map(page => (
        <Card key={page.url}>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Search className="h-4 w-4 text-muted-foreground" />
              <span className="truncate font-mono text-sm">{page.url}</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Top Keywords
              </p>
              <div className="flex flex-wrap gap-2">
                {page.keyword_analysis!.top_keywords.map(kw => (
                  <span key={kw.phrase} className="rounded-md bg-muted/40 px-2 py-1 text-xs">
                    {kw.phrase}
                    <span className="text-muted-foreground ml-1">({kw.found_in.join(", ")})</span>
                  </span>
                ))}
              </div>
            </div>

            {page.keyword_analysis!.rankings.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" /> Rankings
                </p>
                <ul className="space-y-1 text-sm">
                  {page.keyword_analysis!.rankings.map(r => (
                    <li key={r.keyword} className="flex justify-between border-b border-border/30 pb-1">
                      <span>{r.keyword}</span>
                      <span className={
                        r.status === "ranked" ? "font-semibold text-emerald-500"
                        : r.status === "not_ranked" ? "text-amber-600"
                        : "text-muted-foreground italic"
                      }>
                        {r.status === "ranked" ? `#${r.position}`
                          : r.status === "not_ranked" ? "not in top 10"
                          : "not checked"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {page.keyword_analysis!.suggested_keywords.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
                  <Lightbulb className="h-3 w-3" /> Suggested Keywords
                </p>
                <ul className="space-y-1.5 text-sm">
                  {page.keyword_analysis!.suggested_keywords.map(s => (
                    <li key={s.phrase} className="rounded-md bg-muted/20 px-2 py-1.5">
                      <span className="font-medium">{s.phrase}</span>
                      <span className="text-muted-foreground text-xs block">{s.reason}</span>
                      {s.replaces && (
                        <span className="text-[11px] text-amber-600 block">
                          instead of <span className="font-medium">{s.replaces}</span>
                        </span>
                      )}
                      {s.competitor_examples && s.competitor_examples.length > 0 && (
                        <span className="text-[10px] text-muted-foreground/70 block truncate">
                          e.g. {s.competitor_examples.join(", ")}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
