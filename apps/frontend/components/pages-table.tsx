"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { getStatusCodeBadge, formatNumber } from "@/lib/utils";
import { ArrowUpDown, Search, Download, ChevronLeft, ChevronRight, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAudit } from "@/lib/audit-context";
import { usePaginated } from "@/lib/api-hooks";
import { ApiService } from "@/services/api";

// The column names the API accepts. They are the database's columns, so the
// table cannot invent a sort the server has no index for.
type SortKey =
  | "status"
  | "depth"
  | "response_time_ms"
  | "word_count"
  | "internal_links_count"
  | "external_links_count"
  | "issue_count";
type SortDir = "asc" | "desc";

const PAGE_SIZE = 15;
// Long enough that typing a URL fragment is one request, short enough to feel
// immediate.
const SEARCH_DEBOUNCE_MS = 300;

interface PagesTableProps {
  sessionId: string;
}

export function PagesTable({ sessionId }: PagesTableProps) {
  const { setSelectedPage } = useAudit();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("issue_count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  // Filtering, sorting and paging all happen in the query now. The table used
  // to hold every crawled page and do this in the browser, which stopped being
  // possible once the audit payload became a summary.
  const fetcher = useCallback(
    (offset: number, limit: number) =>
      ApiService.getPages(sessionId, {
        offset,
        limit,
        sort: sortKey,
        order: sortDir,
        filter: debouncedSearch || undefined,
      }),
    [sessionId, sortKey, sortDir, debouncedSearch],
  );

  const { items, total, page, pageCount, hasNext, hasPrevious, isLoading, error, next, previous } =
    usePaginated<any>(fetcher, [sessionId, sortKey, sortDir, debouncedSearch], PAGE_SIZE);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const SortButton = ({ colKey, label }: { colKey: SortKey; label: string }) => (
    <Button
      variant="ghost"
      size="sm"
      className="h-auto p-0 font-semibold text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground whitespace-nowrap"
      onClick={() => handleSort(colKey)}
    >
      {label}
      <ArrowUpDown className={`ml-1 h-3 w-3 transition-opacity ${sortKey === colKey ? "opacity-100" : "opacity-40"}`} />
    </Button>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by URL…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10 h-9 text-xs"
          />
        </div>
        <div className="flex items-center gap-3">
          <p className="text-xs text-muted-foreground">
            {formatNumber(total)} pages found
          </p>
          {/* Exported by the server, which holds every row; the table only ever
              has the window on screen. */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => ApiService.downloadExport("csv", sessionId)}
            className="h-9 gap-1.5 text-xs"
          >
            <Download className="h-3.5 w-3.5" /> Export CSV
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-600">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {/* Said out loud: an empty table and a failed request look identical,
              and only one of them is the truth. */}
          <span>Could not load pages — {error}</span>
        </div>
      )}

      <div className="rounded-xl border border-border/50 overflow-x-auto">
        <Table className="text-xs">
          <TableHeader className="bg-muted/30">
            <TableRow className="hover:bg-transparent">
              <TableHead className="min-w-[200px]">URL / Details</TableHead>
              <TableHead><SortButton colKey="status" label="Status" /></TableHead>
              <TableHead><SortButton colKey="depth" label="Depth" /></TableHead>
              <TableHead><SortButton colKey="response_time_ms" label="ms" /></TableHead>
              <TableHead><SortButton colKey="word_count" label="Word Count" /></TableHead>
              <TableHead><SortButton colKey="internal_links_count" label="In Links" /></TableHead>
              <TableHead><SortButton colKey="external_links_count" label="Out Links" /></TableHead>
              <TableHead><SortButton colKey="issue_count" label="Issues" /></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-muted-foreground text-sm">
                  Loading pages…
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-muted-foreground text-sm">
                  {error ? "No pages could be loaded." : "No pages match your search."}
                </TableCell>
              </TableRow>
            ) : (
              items.map((page: any, idx: number) => {
                const statusStyle = getStatusCodeBadge(page.status);
                return (
                  <TableRow
                    key={page.url ?? idx}
                    className="hover:bg-muted/40 cursor-pointer transition-colors"
                    onClick={() => setSelectedPage(page)}
                  >
                    <TableCell className="max-w-[300px]">
                      <div className="font-mono text-[11px] text-primary truncate hover:underline" title={page.url}>
                        {page.url}
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        {page.title ? (
                          <span className="text-[10px] text-muted-foreground truncate max-w-[200px]" title={page.title}>
                            {page.title}
                          </span>
                        ) : (
                          <span className="text-[10px] italic text-muted-foreground/60">No Title</span>
                        )}
                        {page.canonical && (
                          <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-500 text-[9px] font-semibold border border-blue-500/20" title={`Canonical: ${page.canonical}`}>
                            CANON
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ${statusStyle.className}`}>
                        {page.status || "ERR"}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{page.depth}</TableCell>
                    <TableCell className="text-muted-foreground">{page.response_time_ms || 0}</TableCell>
                    <TableCell className="text-muted-foreground">{page.word_count || 0}</TableCell>
                    <TableCell className="text-muted-foreground">{page.internal_links_count || 0}</TableCell>
                    <TableCell className="text-muted-foreground">{page.external_links_count || 0}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        {page.issue_count > 0 ? (
                          <span className="h-2 w-2 rounded-full bg-amber-500" title={`${page.issue_count} issues`} />
                        ) : (
                          <span className="h-2 w-2 rounded-full bg-emerald-500" title="Clean" />
                        )}
                        <span className="font-semibold text-[11px]">{page.issue_count ?? 0}</span>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground pt-2">
          <span>Page {formatNumber(page)} of {formatNumber(pageCount)}</span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="h-8 w-8 p-0"
              disabled={!hasPrevious || isLoading}
              onClick={previous}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-8 w-8 p-0"
              disabled={!hasNext || isLoading}
              onClick={next}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
