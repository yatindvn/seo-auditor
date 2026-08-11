"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Search, TrendingUp, Lightbulb, AlertTriangle } from "lucide-react";
import { PageItem } from "@/lib/types";

interface KeywordPanelProps {
  pages: PageItem[];
}

const SKIPPED_NOTES = [
  "ranking check unavailable — Google CSE not configured",
  "ranking check skipped — daily Google CSE quota reached",
];

export function KeywordPanel({ pages }: KeywordPanelProps) {
  const pagesWithKeywords = pages.filter(
    p => p.keyword_analysis && p.keyword_analysis.top_keywords.length > 0
  );

  const skippedNote = pagesWithKeywords
    .flatMap(p => p.keyword_analysis?.rankings || [])
    .map(r => r.note)
    .find(note => note && SKIPPED_NOTES.includes(note));

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
                      <span className={r.position ? "font-semibold text-emerald-500" : "text-muted-foreground"}>
                        {r.position ? `#${r.position}` : r.note || "not ranking in top 10"}
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
