import { describe, expect, it } from "vitest";

import { averagePosition, biggestMoves, healthTrend, rankSeries } from "@/lib/platform-charts";
import { formatVitalsMetric, vitalsScoreTrend } from "@/lib/platform-charts";

const audit = (id: number, finished: string, score: number | null) => ({
  id, session_id: `s${id}`, status: "completed" as const, trigger: "manual" as const,
  start_url: "https://example.com/", started_at: finished, finished_at: finished, page_count: 10, health_score: score,
});

describe("healthTrend", () => {
  it("orders oldest first and keeps missing scores as null", () => {
    const points = healthTrend([audit(2, "2026-10-20T10:00:00+00:00", 70), audit(1, "2026-10-10T10:00:00+00:00", null)]);
    expect(points.map((p) => p.score)).toEqual([null, 70]);
  });
});

describe("rankSeries", () => {
  const check = (day: string, position: number | null, status = position ? "ranked" : "not_ranked",
                 competitors: Record<string, number | null> = {}) => ({
    position, ranking_url: null, status: status as any, checked_at: `2026-10-${day}T09:00:00+00:00`,
    note: null, competitor_positions: competitors,
  });

  it("maps my position and each competitor per check", () => {
    const { points } = rankSeries([check("20", 4, "ranked", { "rival.org": 2 }), check("21", 9, "ranked", { "rival.org": null })], ["rival.org"]);
    expect(points).toEqual([
      expect.objectContaining({ me: 4, "rival.org": 2 }),
      expect.objectContaining({ me: 9, "rival.org": null }),
    ]);
  });

  it("turns skipped checks into gaps, not zeros", () => {
    const { points } = rankSeries([check("20", 4), check("21", null, "skipped"), check("22", 6)], []);
    expect(points.map((p) => p.me)).toEqual([4, null, 6]);
  });

  it("reports the worst position seen for the reversed axis domain", () => {
    expect(rankSeries([check("20", 4, "ranked", { a: 30 })], ["a"]).maxPosition).toBe(30);
    expect(rankSeries([], []).maxPosition).toBe(10);
  });
});

describe("keyword summaries", () => {
  const kw = (id: number, position: number | null, change: number | null) => ({
    id, phrase: `k${id}`, country: "US", device: "desktop" as const, language: "en", enabled: true, change,
    latest: position === null ? null : { position, ranking_url: null, status: "ranked" as const,
                                         checked_at: "", note: null, competitor_positions: {} },
  });

  it("averages ranked positions only", () => {
    expect(averagePosition([kw(1, 4, null), kw(2, 10, null), kw(3, null, null)])).toBe(7);
    expect(averagePosition([kw(1, null, null)])).toBeNull();
  });

  it("biggest moves are by absolute change", () => {
    expect(biggestMoves([kw(1, 4, 1), kw(2, 9, -5), kw(3, 3, 3), kw(4, 5, null)], 2).map((k) => k.id)).toEqual([2, 3]);
  });
});

describe("Core Web Vitals helpers", () => {
  it("formats each metric in its own unit", () => {
    expect(formatVitalsMetric("lcp_ms", 4810)).toBe("4.8 s");
    expect(formatVitalsMetric("inp_ms", 182.4)).toBe("182 ms");
    expect(formatVitalsMetric("tbt_ms", 90)).toBe("90 ms");
    expect(formatVitalsMetric("cls", 0.123)).toBe("0.12");
    expect(formatVitalsMetric("lcp_ms", null)).toBe("—");
  });

  it("charts the performance score per audit, gaps as null", () => {
    const point = (id: number, score: number | null) => ({
      audit_id: id, finished_at: `2026-10-2${id}T10:00:00+00:00`, url: "u", source: "psi" as const,
      data_kind: "lab" as const, performance_score: score, lcp_ms: null, inp_ms: null, cls: null,
      tbt_ms: null, rating: null, metric_ratings: { lcp_ms: null, inp_ms: null, cls: null, tbt_ms: null },
    });
    const data = vitalsScoreTrend([point(1, 71), point(2, null)]);
    expect(data.map((d) => d.score)).toEqual([71, null]);
    expect(data[0].label).toBeTruthy();
  });
});
