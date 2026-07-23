"use client";

import React, { useState } from "react";
import { Recommendation } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown, ExternalLink, Lightbulb } from "lucide-react";
import { getSeverityBadge } from "@/lib/utils";

interface RecommendationsListProps {
  recommendations: Recommendation[];
}

export function RecommendationsList({ recommendations }: RecommendationsListProps) {
  const [openItems, setOpenItems] = useState<Record<number, boolean>>({});

  const toggleItem = (idx: number) => {
    setOpenItems((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  if (!recommendations || recommendations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center border border-dashed rounded-xl">
        <Lightbulb className="h-8 w-8 text-amber-500 mb-2 opacity-80" />
        <p className="text-sm font-semibold text-foreground">No critical recommendations!</p>
        <p className="text-xs text-muted-foreground mt-1">Your website passed all primary health checks cleanly.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {recommendations.map((rec, idx) => {
        const severityInfo = getSeverityBadge(rec.severity);
        const isOpen = !!openItems[idx];
        const hasExamples = rec.example_urls && rec.example_urls.length > 0;

        return (
          <Collapsible
            key={`${rec.code}-${idx}`}
            open={isOpen}
            onOpenChange={() => toggleItem(idx)}
            className="rounded-xl border border-border/70 bg-card p-4 transition-all hover:border-border hover:shadow-sm"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex flex-1 items-start gap-3">
                <Badge
                  variant={
                    rec.severity === "critical"
                      ? "critical"
                      : rec.severity === "warning"
                      ? "warning"
                      : "info"
                  }
                  className="mt-0.5 shrink-0"
                >
                  {severityInfo.label}
                </Badge>
                <div className="space-y-1">
                  <p className="text-sm font-medium leading-snug text-foreground">
                    {rec.recommendation}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Code: <code className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-mono">{rec.code}</code> &middot; Priority Score: {rec.priority_score}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3 shrink-0">
                <span className="rounded-lg bg-muted px-2.5 py-1 text-xs font-semibold text-muted-foreground">
                  {rec.affected_pages} {rec.affected_pages === 1 ? "page" : "pages"}
                </span>

                {hasExamples && (
                  <CollapsibleTrigger asChild>
                    <button className="rounded-lg p-1 text-muted-foreground hover:bg-accent hover:text-foreground">
                      <ChevronDown
                        className={`h-4 w-4 transition-transform duration-200 ${
                          isOpen ? "rotate-180" : ""
                        }`}
                      />
                    </button>
                  </CollapsibleTrigger>
                )}
              </div>
            </div>

            {hasExamples && (
              <CollapsibleContent className="mt-3 pt-3 border-t border-border/50 text-xs text-muted-foreground space-y-1.5">
                <p className="font-semibold text-foreground/80">Affected Example URLs:</p>
                <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
                  {rec.example_urls.map((url, uIdx) => (
                    <a
                      key={uIdx}
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1.5 text-primary hover:underline truncate font-mono text-[11px]"
                    >
                      <ExternalLink className="h-3 w-3 shrink-0 opacity-70" />
                      <span className="truncate">{url}</span>
                    </a>
                  ))}
                </div>
              </CollapsibleContent>
            )}
          </Collapsible>
        );
      })}
    </div>
  );
}
