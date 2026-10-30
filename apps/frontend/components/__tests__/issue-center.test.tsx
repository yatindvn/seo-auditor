import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { IssueCenter } from "@/components/issue-center";
import { RecommendationsList } from "@/components/recommendations-list";

const longUrl = "https://books.toscrape.com/catalogue/category/books/historical-fiction_4/index.html";
vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ auditData: { recommendations: [{
    code: "MISSING_META_DESCRIPTION", severity: "warning", affected_pages: 10, impact: "high", estimated_effort: "low",
    priority_score: 60, recommendation: "Add meta descriptions", example_urls: [longUrl],
  }] } }),
}));

// jsdom has no layout, so these guard the classes that let a 390px phone wrap
// long codes and URLs instead of widening the page (checked with Playwright).
describe("IssueCenter on narrow screens", () => {
  it("lets the badge row and long URLs wrap", () => {
    render(<IssueCenter />);
    const code = screen.getByText("MISSING_META_DESCRIPTION");
    expect(code.className).toContain("break-all");
    expect(code.parentElement?.className).toContain("flex-wrap");
    expect(code.parentElement?.parentElement?.className).toContain("min-w-0");
    expect(screen.getByText(longUrl).className).toContain("break-all");
  });
});

describe("RecommendationsList on narrow screens", () => {
  it("lets the page count drop under the text instead of off the card", () => {
    render(<RecommendationsList recommendations={[{ code: "MISSING_META_DESCRIPTION", severity: "warning", affected_pages: 10,
      priority_score: 50, recommendation: "Add a compelling meta description", example_urls: [longUrl] } as any]} />);
    const count = screen.getByText("10 pages");
    const row = count.parentElement!.parentElement!;
    expect(row.className).toContain("flex-wrap");
    expect(row.firstElementChild!.className).toContain("min-w-0");
    expect(screen.getByText("MISSING_META_DESCRIPTION").className).toContain("break-all");
  });
});
