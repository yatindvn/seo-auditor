import type { ContentSummary } from "@seo-auditor/shared";

export function ago(iso: string, now: number = Date.now()): string {
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export function topSchema(summary: ContentSummary): { type: string; count: number } | null {
  const entries = Object.entries(summary.schema_counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return entries.length ? { type: entries[0][0], count: entries[0][1] } : null;
}

export const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString());
