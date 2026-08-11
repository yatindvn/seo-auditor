import type { ActivityLogEvent } from "@seo-auditor/shared";

export type ActivityFilterType = "all" | "page" | "link" | "redirect" | "error";

export function formatCrawlTime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function matchesActivityFilter(
  act: ActivityLogEvent,
  searchQuery: string,
  filterType: ActivityFilterType
): boolean {
  if (
    searchQuery &&
    !act.message.toLowerCase().includes(searchQuery.toLowerCase()) &&
    !act.url?.toLowerCase().includes(searchQuery.toLowerCase())
  ) {
    return false;
  }
  if (filterType !== "all") {
    if (filterType === "link" && !["internal_link", "external_link"].includes(act.type)) return false;
    if (filterType === "error" && !["broken_link", "timeout"].includes(act.type)) return false;
    if (filterType === "page" && act.type !== "page_crawled") return false;
    if (filterType === "redirect" && act.type !== "redirect") return false;
  }
  return true;
}
