import type { AuditListItem, RankCheckView, TrackedKeyword } from "@seo-auditor/shared";

// Categorical slots in fixed order, validated (dataviz validate_palette.js)
// against the card surfaces: white (light) and #050b1c (dark). Slot 1 is
// always the project's own site; competitors follow in listed order.
export const SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
export const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"];

const dayLabel = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export function healthTrend(audits: AuditListItem[]) {
  return [...audits]
    .sort((a, b) => a.finished_at.localeCompare(b.finished_at) || a.id - b.id)
    .map((a) => ({ label: dayLabel(a.finished_at), score: a.health_score }));
}

export type RankPoint = { label: string; me: number | null } & Record<string, number | null | string>;

export function rankSeries(history: RankCheckView[], competitors: string[]) {
  let maxPosition = 10;
  const points: RankPoint[] = history.map((check) => {
    // A skipped check measured nothing: a gap in the line, never a zero.
    const me = check.status === "skipped" ? null : check.position;
    const point: RankPoint = { label: dayLabel(check.checked_at), me };
    if (me != null) maxPosition = Math.max(maxPosition, me);
    for (const domain of competitors) {
      const value = check.status === "skipped" ? null : check.competitor_positions?.[domain] ?? null;
      point[domain] = value;
      if (value != null) maxPosition = Math.max(maxPosition, value);
    }
    return point;
  });
  return { points, maxPosition };
}

export function averagePosition(keywords: TrackedKeyword[]): number | null {
  const ranked = keywords.map((k) => k.latest?.position).filter((p): p is number => p != null);
  if (!ranked.length) return null;
  return Math.round((ranked.reduce((a, b) => a + b, 0) / ranked.length) * 10) / 10;
}

export function biggestMoves(keywords: TrackedKeyword[], n: number): TrackedKeyword[] {
  return keywords
    .filter((k) => k.change != null && k.change !== 0)
    .sort((a, b) => Math.abs(b.change!) - Math.abs(a.change!))
    .slice(0, n);
}
