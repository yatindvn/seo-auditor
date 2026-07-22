"use client";

import React, { useState } from "react";
import { BrokenLink } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown, ExternalLink, Link2Off } from "lucide-react";
import { getStatusCodeBadge } from "@/lib/utils";

interface BrokenLinksTableProps {
  brokenLinks: BrokenLink[];
}

export function BrokenLinksTable({ brokenLinks }: BrokenLinksTableProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  if (!brokenLinks || brokenLinks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-emerald-300 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/10 p-8 text-center">
        <Link2Off className="h-7 w-7 text-emerald-500 opacity-80" />
        <p className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">No broken links found!</p>
        <p className="text-xs text-muted-foreground">All crawled links returned valid responses.</p>
      </div>
    );
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="flex w-full items-center justify-between rounded-xl border border-border/70 bg-card px-5 py-4 hover:bg-muted/30 transition-all">
        <div className="flex items-center gap-3">
          <Link2Off className="h-4 w-4 text-rose-500" />
          <span className="text-sm font-semibold">
            Broken Links{" "}
            <span className="ml-1 rounded-full bg-rose-500/10 px-2 py-0.5 text-xs font-bold text-rose-600 dark:text-rose-400">
              {brokenLinks.length}
            </span>
          </span>
        </div>
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
        />
      </CollapsibleTrigger>

      <CollapsibleContent className="mt-2">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>URL</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Linked From</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {brokenLinks.map((link, idx) => {
              const statusStyle = getStatusCodeBadge(link.status);
              const isRowOpen = expandedRow === idx;
              return (
                <React.Fragment key={idx}>
                  <TableRow
                    className="cursor-pointer"
                    onClick={() => setExpandedRow(isRowOpen ? null : idx)}
                  >
                    <TableCell className="max-w-xs">
                      <div className="flex items-center gap-2">
                        <ChevronDown
                          className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform ${isRowOpen ? "rotate-180" : ""}`}
                        />
                        <span className="truncate font-mono text-[11px] text-foreground/80">
                          {link.url}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      {link.status !== null ? (
                        <Badge variant="outline" className={`text-[11px] font-semibold ${statusStyle.className}`}>
                          {link.status}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-[11px] text-rose-500">
                          Unreachable
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {link.external ? (
                        <Badge variant="outline" className="text-[11px] text-muted-foreground">External</Badge>
                      ) : (
                        <Badge variant="outline" className="text-[11px] text-muted-foreground">Internal</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground tabular-nums">
                      {link.linked_from_count} referrer{link.linked_from_count !== 1 ? "s" : ""}
                    </TableCell>
                  </TableRow>
                  {isRowOpen && (
                    <TableRow className="bg-muted/20 hover:bg-muted/30">
                      <TableCell colSpan={4} className="pb-3 pt-2 px-8">
                        <div className="space-y-1.5">
                          {link.error && (
                            <p className="text-xs text-rose-600 dark:text-rose-400 font-medium">
                              Error: {link.error}
                            </p>
                          )}
                          {link.linked_from && link.linked_from.length > 0 && (
                            <div>
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">Referrers:</p>
                              <div className="space-y-1">
                                {link.linked_from.map((ref, rIdx) => (
                                  <a
                                    key={rIdx}
                                    href={ref}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="flex items-center gap-1.5 font-mono text-[10px] text-primary hover:underline"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <ExternalLink className="h-2.5 w-2.5 shrink-0 opacity-70" />
                                    {ref}
                                  </a>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              );
            })}
          </TableBody>
        </Table>
      </CollapsibleContent>
    </Collapsible>
  );
}
