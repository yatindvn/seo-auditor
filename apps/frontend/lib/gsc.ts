import type { GscDailyPoint } from "@seo-auditor/shared";

export const formatCount = (n: number | null | undefined) => (n == null ? "—" : Math.round(n).toLocaleString("en-US"));
export const formatCtr = (ctr: number | null | undefined) => (ctr == null ? "—" : `${(ctr * 100).toFixed(1)}%`);
export const formatPosition = (p: number | null | undefined) => (p == null ? "—" : p.toFixed(1));

/** new − old, rounded for display; null when either side is missing. */
export function change(now: number | null | undefined, before: number | null | undefined, digits = 0): number | null {
  if (now == null || before == null) return null;
  const f = 10 ** digits;
  return Math.round((now - before) * f) / f;
}

export function trendData(daily: GscDailyPoint[]) {
  return daily.map((d) => ({ label: new Date(`${d.date}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }),
                             clicks: d.clicks, impressions: d.impressions }));
}
