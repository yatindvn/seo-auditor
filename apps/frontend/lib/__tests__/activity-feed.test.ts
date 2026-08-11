import { describe, it, expect } from "vitest";
import { formatCrawlTime, matchesActivityFilter } from "@/lib/activity-feed";
import type { ActivityLogEvent } from "@seo-auditor/shared";

function makeEvent(overrides: Partial<ActivityLogEvent> = {}): ActivityLogEvent {
  return {
    id: "1",
    type: "page_crawled",
    message: "Crawled /foo",
    timestamp: "0",
    url: "https://example.com/foo",
    ...overrides,
  };
}

describe("formatCrawlTime", () => {
  it("formats sub-minute durations as seconds", () => {
    expect(formatCrawlTime(42)).toBe("42s");
  });

  it("formats minute-plus durations as mm:ss", () => {
    expect(formatCrawlTime(125)).toBe("02:05");
  });
});

describe("matchesActivityFilter", () => {
  it("excludes events that don't match the search query", () => {
    const event = makeEvent({ message: "Crawled /foo", url: "https://example.com/foo" });
    expect(matchesActivityFilter(event, "bar", "all")).toBe(false);
  });

  it("includes events that match the search query", () => {
    const event = makeEvent({ message: "Crawled /foo", url: "https://example.com/foo" });
    expect(matchesActivityFilter(event, "foo", "all")).toBe(true);
  });

  it("filters to only link events when filterType is link", () => {
    const linkEvent = makeEvent({ type: "internal_link" });
    const pageEvent = makeEvent({ type: "page_crawled" });
    expect(matchesActivityFilter(linkEvent, "", "link")).toBe(true);
    expect(matchesActivityFilter(pageEvent, "", "link")).toBe(false);
  });
});
