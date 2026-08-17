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
          rankings: [{ keyword: "espresso machine", position: 3, status: "ranked", checked_at: "2026-01-01T00:00:00Z" }],
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
              status: "skipped",
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

  it("shows the position for a ranked keyword", () => {
    const pages = [{
      url: "https://example.com/a",
      keyword_analysis: {
        top_keywords: [{ phrase: "cloud", score: null, found_in: ["title"] }],
        rankings: [{ keyword: "cloud", position: 3, status: "ranked" as const, note: null }],
        suggested_keywords: [],
      },
    }] as any;

    render(<KeywordPanel pages={pages} />);
    expect(screen.getByText("#3")).toBeInTheDocument();
  });

  it("shows a skipped banner without claiming the keyword ranks badly", () => {
    const pages = [{
      url: "https://example.com/a",
      keyword_analysis: {
        top_keywords: [{ phrase: "cloud", score: null, found_in: ["title"] }],
        rankings: [{
          keyword: "cloud", position: null, status: "skipped" as const,
          note: "ranking check unavailable — Google CSE not configured",
        }],
        suggested_keywords: [],
      },
    }] as any;

    render(<KeywordPanel pages={pages} />);
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
    // The component's own vocabulary for a skipped ranking is "not checked"
    // (see the ternary in the Rankings list) — a skipped row must render that,
    // not the "not in top 10" wording reserved for status === "not_ranked".
    expect(screen.getByText("not checked")).toBeInTheDocument();
    expect(screen.queryByText("not in top 10")).not.toBeInTheDocument();
  });

  it("renders a page with rankings but zero extracted keywords, instead of hiding it", () => {
    // keyword_extraction.extract_keywords legitimately returns [] for thin
    // pages (image galleries, near-empty landing pages). Rank checks run from
    // the user's nominated keywords independently of extraction, so a page
    // can have rankings with an empty top_keywords array. Quota was spent on
    // this query — the result must still render, not be silently dropped.
    const pages = [{
      url: "https://example.com/gallery",
      keyword_analysis: {
        top_keywords: [],
        rankings: [{ keyword: "photo gallery", position: 4, status: "ranked" as const, note: null }],
        suggested_keywords: [],
      },
    }] as any;

    render(<KeywordPanel pages={pages} />);

    expect(screen.getByText("https://example.com/gallery")).toBeInTheDocument();
    expect(screen.getByText("photo gallery")).toBeInTheDocument();
    expect(screen.getByText("#4")).toBeInTheDocument();
  });

  it("labels a suggestion with the keyword it replaces", () => {
    const pages = [{
      url: "https://example.com/a",
      keyword_analysis: {
        top_keywords: [{ phrase: "cloud", score: null, found_in: ["title"] }],
        rankings: [{ keyword: "cloud", position: null, status: "not_ranked" as const, note: "not found in top 10" }],
        suggested_keywords: [{ phrase: "cloud migration", reason: "related search", replaces: "cloud" }],
      },
    }] as any;

    render(<KeywordPanel pages={pages} />);
    expect(screen.getByText(/instead of/i)).toBeInTheDocument();
    expect(screen.getByText("cloud migration")).toBeInTheDocument();
  });

  describe("not-reached list", () => {
    const crawledPage = (url: string) =>
      makePage({
        url,
        keyword_analysis: {
          top_keywords: [{ phrase: "cloud", score: null, found_in: ["title"] }],
          rankings: [],
          suggested_keywords: [],
        },
      });

    it("does not list a nominated URL that was crawled under a query string", () => {
      // Crawled page kept its query string (crawler.normalize_url preserves query
      // strings when deduping); the user's nominated URL has none. The backend's
      // rank_checker._normalize_url strips the query on both sides before matching,
      // so this page WAS rank-checked and must not be reported as unreached.
      const pages = [crawledPage("https://example.com/services?ref=nav")];
      const rankTargets = [{ url: "https://example.com/services", keywords: ["services"] }];

      render(<KeywordPanel pages={pages} rankTargets={rankTargets} />);

      expect(screen.queryByText(/Not reached by this crawl/i)).not.toBeInTheDocument();
    });

    it("does not list a nominated URL differing only by scheme, www, or trailing slash", () => {
      const pages = [crawledPage("http://www.example.com/about/")];
      const rankTargets = [{ url: "https://example.com/about", keywords: ["about"] }];

      render(<KeywordPanel pages={pages} rankTargets={rankTargets} />);

      expect(screen.queryByText(/Not reached by this crawl/i)).not.toBeInTheDocument();
    });

    it("lists a genuinely uncrawled nominated URL", () => {
      const pages = [crawledPage("https://example.com/")];
      const rankTargets = [{ url: "https://example.com/pricing", keywords: ["pricing"] }];

      render(<KeywordPanel pages={pages} rankTargets={rankTargets} />);

      expect(screen.getByText(/Not reached by this crawl/i)).toBeInTheDocument();
      expect(screen.getByText(/example\.com\/pricing/)).toBeInTheDocument();
    });

    it("renders no not-reached element when rankTargets is omitted", () => {
      const pages = [crawledPage("https://example.com/")];

      render(<KeywordPanel pages={pages} />);

      expect(screen.queryByText(/Not reached by this crawl/i)).not.toBeInTheDocument();
    });
  });
});
