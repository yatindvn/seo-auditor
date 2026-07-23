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
import { Input } from "@/components/ui/input";
import { getStatusCodeBadge } from "@/lib/utils";
import { ArrowUpDown, Search, Download, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAudit } from "@/lib/audit-context";

type SortKey = "status_code" | "depth" | "response_time_ms" | "word_count" | "internal_links_count" | "external_links_count" | "issues_total";
type SortDir = "asc" | "desc";

interface PagesTableProps {
  pages: PageItem[];
}

export function PagesTable({ pages }: PagesTableProps) {
  const { setSelectedPage } = useAudit();
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("issues_total");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 15;

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    setCurrentPage(1);
  };

  const enhancedPages = useMemo(() => {
    return pages.map(p => ({
      ...p,
      issues_total: (p.critical_issues || 0) + (p.warning_issues || 0) + (p.info_issues || 0)
    }));
  }, [pages]);

  const filtered = useMemo(() => {
    return enhancedPages
      .filter((p) => p.url.toLowerCase().includes(search.toLowerCase()) ||
        (p.title || "").toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => {
        const aVal = (a[sortKey] ?? 0) as number;
        const bVal = (b[sortKey] ?? 0) as number;
        return sortDir === "asc" ? aVal - bVal : bVal - aVal;
      });
  }, [enhancedPages, search, sortKey, sortDir]);

  const paginated = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const totalPages = Math.ceil(filtered.length / pageSize);

  const exportCsv = () => {
    const headers = ["URL", "Status", "Depth", "Response Time (ms)", "Title", "Meta Desc Length", "Canonical", "Word Count", "Internal Links", "External Links", "Critical", "Warnings", "Info"];
    const rows = filtered.map(p => [
      p.url,
      p.status_code || "",
      p.depth || 0,
      p.response_time_ms || 0,
      `"${(p.title || "").replace(/"/g, '""')}"`,
      p.meta_description?.length || 0,
      p.canonical || "",
      p.word_count || 0,
      p.internal_links_count || 0,
      p.external_links_count || 0,
      p.critical_issues || 0,
      p.warning_issues || 0,
      p.info_issues || 0
    ]);
    
    const csv = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pages_export.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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
            placeholder="Search by URL or title…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setCurrentPage(1);
            }}
            className="pl-10 h-9 text-xs"
          />
        </div>
        <div className="flex items-center gap-3">
          <p className="text-xs text-muted-foreground">
            {filtered.length} pages found
          </p>
          <Button variant="outline" size="sm" onClick={exportCsv} className="h-9 gap-1.5 text-xs">
            <Download className="h-3.5 w-3.5" /> Export CSV
          </Button>
        </div>
      </div>
      
      <div className="rounded-xl border border-border/50 overflow-x-auto">
        <Table className="text-xs">
          <TableHeader className="bg-muted/30">
            <TableRow className="hover:bg-transparent">
              <TableHead className="min-w-[200px]">URL / Details</TableHead>
              <TableHead><SortButton colKey="status_code" label="Status" /></TableHead>
              <TableHead><SortButton colKey="depth" label="Depth" /></TableHead>
              <TableHead><SortButton colKey="response_time_ms" label="ms" /></TableHead>
              <TableHead><SortButton colKey="word_count" label="Words" /></TableHead>
              <TableHead><SortButton colKey="internal_links_count" label="In Links" /></TableHead>
              <TableHead><SortButton colKey="external_links_count" label="Out Links" /></TableHead>
              <TableHead><SortButton colKey="issues_total" label="Issues" /></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paginated.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-muted-foreground text-sm">
                  No pages match your search.
                </TableCell>
              </TableRow>
            ) : (
              paginated.map((page, idx) => {
                const statusStyle = getStatusCodeBadge(page.status_code);
                return (
                  <TableRow 
                    key={idx} 
                    className="hover:bg-muted/40 cursor-pointer transition-colors"
                    onClick={() => setSelectedPage(page as any)}
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
                        {page.status_code || "ERR"}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{page.depth}</TableCell>
                    <TableCell className="text-muted-foreground">{page.response_time_ms || 0}</TableCell>
                    <TableCell className="text-muted-foreground">{page.word_count || 0}</TableCell>
                    <TableCell className="text-muted-foreground">{page.internal_links_count || 0}</TableCell>
                    <TableCell className="text-muted-foreground">{page.external_links_count || 0}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        {page.critical_issues > 0 && <span className="h-2 w-2 rounded-full bg-rose-500" title={`${page.critical_issues} Critical`} />}
                        {page.warning_issues > 0 && <span className="h-2 w-2 rounded-full bg-amber-500" title={`${page.warning_issues} Warning`} />}
                        {page.info_issues > 0 && <span className="h-2 w-2 rounded-full bg-blue-500" title={`${page.info_issues} Info`} />}
                        {page.issues_total === 0 && <span className="h-2 w-2 rounded-full bg-emerald-500" title="Clean" />}
                        <span className="font-semibold text-[11px]">{page.issues_total}</span>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground pt-2">
          <span>Page {currentPage} of {totalPages}</span>
          <div className="flex gap-2">
            <Button 
              variant="outline" 
              size="sm" 
              className="h-8 w-8 p-0" 
              disabled={currentPage === 1}
              onClick={() => setCurrentPage(c => c - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button 
              variant="outline" 
              size="sm" 
              className="h-8 w-8 p-0" 
              disabled={currentPage === totalPages}
              onClick={() => setCurrentPage(c => c + 1)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
