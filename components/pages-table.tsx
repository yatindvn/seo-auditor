"use client";

import React, { useState, useMemo } from "react";
import { PageItem } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { getStatusCodeBadge } from "@/lib/utils";
import { ArrowUpDown, Search } from "lucide-react";
import { Button } from "@/components/ui/button";

type SortKey = "status_code" | "word_count" | "critical_issues" | "warning_issues" | "info_issues";
type SortDir = "asc" | "desc";

interface PagesTableProps {
  pages: PageItem[];
}

export function PagesTable({ pages }: PagesTableProps) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("critical_issues");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const filtered = useMemo(() => {
    return pages
      .filter((p) => p.url.toLowerCase().includes(search.toLowerCase()) ||
        (p.title || "").toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => {
        const aVal = (a[sortKey] ?? 0) as number;
        const bVal = (b[sortKey] ?? 0) as number;
        return sortDir === "asc" ? aVal - bVal : bVal - aVal;
      });
  }, [pages, search, sortKey, sortDir]);

  const SortButton = ({ colKey, label }: { colKey: SortKey; label: string }) => (
    <Button
      variant="ghost"
      size="sm"
      className="h-auto p-0 font-semibold text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground"
      onClick={() => handleSort(colKey)}
    >
      {label}
      <ArrowUpDown className={`ml-1.5 h-3 w-3 transition-opacity ${sortKey === colKey ? "opacity-100" : "opacity-40"}`} />
    </Button>
  );

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-3.5 top-3.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search by URL or title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-10"
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Showing {filtered.length} of {pages.length} pages
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>URL / Title</TableHead>
            <TableHead><SortButton colKey="status_code" label="Status" /></TableHead>
            <TableHead><SortButton colKey="word_count" label="Words" /></TableHead>
            <TableHead><SortButton colKey="critical_issues" label="Critical" /></TableHead>
            <TableHead><SortButton colKey="warning_issues" label="Warn" /></TableHead>
            <TableHead><SortButton colKey="info_issues" label="Info" /></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filtered.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="py-10 text-center text-muted-foreground text-sm">
                No pages match your search.
              </TableCell>
            </TableRow>
          ) : (
            filtered.map((page, idx) => {
              const statusStyle = getStatusCodeBadge(page.status_code);
              return (
                <TableRow key={idx}>
                  <TableCell className="min-w-[220px] max-w-[360px]">
                    <div className="space-y-0.5">
                      <a
                        href={page.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate font-mono text-[11px] text-primary hover:underline"
                      >
                        {page.url}
                      </a>
                      {page.title && (
                        <p className="truncate text-xs text-muted-foreground">{page.title}</p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {page.status_code !== null ? (
                      <Badge variant="outline" className={`text-[11px] font-semibold ${statusStyle.className}`}>
                        {page.status_code}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-[11px] text-muted-foreground">—</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-sm tabular-nums text-muted-foreground">
                    {page.word_count ?? 0}
                  </TableCell>
                  <TableCell>
                    {page.critical_issues > 0 ? (
                      <span className="font-bold text-rose-600 dark:text-rose-400 text-sm tabular-nums">
                        {page.critical_issues}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/40 text-sm">0</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {page.warning_issues > 0 ? (
                      <span className="font-bold text-amber-600 dark:text-amber-400 text-sm tabular-nums">
                        {page.warning_issues}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/40 text-sm">0</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {page.info_issues > 0 ? (
                      <span className="font-bold text-blue-600 dark:text-blue-400 text-sm tabular-nums">
                        {page.info_issues}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/40 text-sm">0</span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );
}
