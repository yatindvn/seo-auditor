import { describe, expect, it } from "vitest";

import { change, formatCount, formatCtr, formatPosition, trendData } from "@/lib/gsc";

describe("gsc helpers", () => {
  it("formats numbers for people", () => {
    expect(formatCount(1234.4)).toBe("1,234");
    expect(formatCtr(0.0345)).toBe("3.5%");
    expect(formatPosition(7.26)).toBe("7.3");
    expect(formatCtr(null)).toBe("—");
  });
  it("computes changes", () => {
    expect(change(560, 280)).toBe(280);
    expect(change(5, 10, 1)).toBe(-5);
    expect(change(null, 3)).toBeNull();
  });
  it("labels the trend by UTC day", () => {
    expect(trendData([{ date: "2026-10-01", clicks: 3, impressions: 40, ctr: 0.075, position: 8 }])).toEqual([
      { label: "Oct 1", clicks: 3, impressions: 40 }]);
  });
});
