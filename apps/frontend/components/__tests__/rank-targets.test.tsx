import { describe, it, expect } from "vitest";
import { buildRankTargets, countQueries } from "@/lib/rank-targets";

describe("buildRankTargets", () => {
  it("splits comma-separated keywords and trims whitespace", () => {
    const rows = [{ url: "https://a.com/x", keywords: " cloud , devops " }];
    expect(buildRankTargets(rows)).toEqual([
      { url: "https://a.com/x", keywords: ["cloud", "devops"] },
    ]);
  });

  it("drops rows missing a url or keywords", () => {
    const rows = [
      { url: "", keywords: "cloud" },
      { url: "https://a.com/x", keywords: "" },
      { url: "https://a.com/y", keywords: "seo" },
    ];
    expect(buildRankTargets(rows)).toEqual([{ url: "https://a.com/y", keywords: ["seo"] }]);
  });

  it("caps each row at ten keywords to match schema validation", () => {
    const rows = [{ url: "https://a.com/x", keywords: Array.from({ length: 15 }, (_, i) => `k${i}`).join(",") }];
    expect(buildRankTargets(rows)[0].keywords).toHaveLength(10);
  });
});

describe("countQueries", () => {
  it("sums keyword counts across rows", () => {
    const rows = [
      { url: "https://a.com/x", keywords: "one,two" },
      { url: "https://a.com/y", keywords: "three" },
    ];
    expect(countQueries(rows)).toBe(3);
  });

  it("counts nothing for incomplete rows", () => {
    expect(countQueries([{ url: "", keywords: "one,two" }])).toBe(0);
  });
});
