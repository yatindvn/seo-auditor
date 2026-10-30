import { describe, expect, it } from "vitest";

import { ago, num, topSchema } from "@/lib/content";

describe("content helpers", () => {
  it("says how long ago", () => {
    const now = Date.parse("2026-10-31T12:00:00Z");
    expect(ago("2026-10-31T12:00:00Z", now)).toBe("just now");
    expect(ago("2026-10-31T11:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-10-31T10:00:00Z", now)).toBe("2 h ago");
    expect(ago("2026-10-27T12:00:00Z", now)).toBe("4 d ago");
  });
  it("picks the top schema type and formats numbers", () => {
    expect(topSchema({ median_words: 1, median_referring_domains: null, schema_counts: { FAQPage: 2, Article: 6, Product: 6 }, common_h2_terms: [] }))
      .toEqual({ type: "Article", count: 6 });
    expect(topSchema({ median_words: null, median_referring_domains: null, schema_counts: {}, common_h2_terms: [] })).toBeNull();
    expect(num(null)).toBe("—");
    expect(num(1200)).toBe((1200).toLocaleString());
  });
});
