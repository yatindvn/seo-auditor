import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KeywordPanel } from "@/components/keyword-panel";
import type { PageItem } from "@seo-auditor/shared";

function makePage(overrides: Partial<PageItem> = {}): PageItem {
  return {
    url: "https://example.com/",
    status_code: 200,
    depth: 0,
    response_time_ms: 100,
    title: "Example",
    meta_description: null,
    h1: null,
    word_count: 500,
    canonical: null,
    critical_issues: 0,
    warning_issues: 0,
    info_issues: 0,
    issue_codes: "",
    ...overrides,
  };
}

describe("KeywordPanel", () => {
  it("renders extracted keywords, rankings, and suggestions for a page", () => {
    const pages = [
      makePage({
        url: "https://example.com/espresso",
        keyword_analysis: {
          top_keywords: [{ phrase: "espresso machine", score: 5, found_in: ["title", "h1"] }],
          rankings: [{ keyword: "espresso machine", position: 3, checked_at: "2026-01-01T00:00:00Z" }],
          suggested_keywords: [{ phrase: "manual pour over kettle", reason: "related search" }],
        },
      }),
    ];

    render(<KeywordPanel pages={pages} />);

    expect(screen.getAllByText(/espresso machine/).length).toBeGreaterThan(0);
    expect(screen.getByText("#3")).toBeInTheDocument();
    expect(screen.getByText("manual pour over kettle")).toBeInTheDocument();
    expect(screen.getByText("related search")).toBeInTheDocument();
  });

  it("shows a banner when rank-checking was skipped site-wide", () => {
    const pages = [
      makePage({
        keyword_analysis: {
          top_keywords: [{ phrase: "espresso machine", score: 5, found_in: ["title"] }],
          rankings: [
            {
              keyword: "espresso machine",
              position: null,
              note: "ranking check unavailable — Google CSE not configured",
            },
          ],
          suggested_keywords: [],
        },
      }),
    ];

    render(<KeywordPanel pages={pages} />);

    expect(
      screen.getAllByText("ranking check unavailable — Google CSE not configured").length
    ).toBeGreaterThan(0);
  });

  it("renders a fallback message when no page has keyword data", () => {
    render(<KeywordPanel pages={[makePage()]} />);

    expect(screen.getByText("No keyword data available for this audit.")).toBeInTheDocument();
  });
});
