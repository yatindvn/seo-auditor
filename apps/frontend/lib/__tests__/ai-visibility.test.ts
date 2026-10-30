import { describe, expect, it } from "vitest";

import { estimate, ordinal, pct, safeUrl, segments } from "@/lib/ai-visibility";

describe("ai-visibility helpers", () => {
  it("splits text at highlights, ignoring bad ranges", () => {
    expect(segments("Amazon then BTS!", [{ start: 12, end: 15, owner: "me" }, { start: 0, end: 6, owner: "amz" }, { start: 3, end: 5, owner: "x" }]))
      .toEqual([{ text: "Amazon", owner: "amz" }, { text: " then " }, { text: "BTS", owner: "me" }, { text: "!" }]);
    expect(segments("abc", [{ start: 1, end: 9, owner: "x" }])).toEqual([{ text: "abc" }]);
  });
  it("formats", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]);
    expect(pct(0.756)).toBe("76%");
    expect(estimate(2, 3)).toBe("≈ $0.18");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("https://a.com/")).toBe("https://a.com/");
  });
});
