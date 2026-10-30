import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ContentPage from "@/app/content/page";
import { Platform } from "@/services/platform";

const row = (position: number, over: object = {}) => ({
  position, url: `https://s${position}.com/p`, domain: `s${position}.com`, title: `Page ${position}`, status: 200, error: null,
  word_count: 1000 + position, h1: `H ${position}`, outline: [{ level: 2, text: "Best rare books" }, { level: 3, text: "First editions" }],
  schema_types: ["Article"], images: 3, internal_links: 20, external_links: 4, readability: 55.5, issues: 2,
  backlinks: 500, referring_domains: 40, ...over });
const search = (over: object = {}) => ({
  id: 7, topic: "rare books", country: "US", language: "en", created_at: new Date(Date.now() - 2 * 3600e3).toISOString(),
  cached: false, dry_run: false, notes: [],
  summary: { median_words: 1500, median_referring_domains: 40, schema_counts: { Article: 6, FAQPage: 2 }, common_h2_terms: [{ term: "rare", count: 8 }] },
  results: [row(1), row(2, { status: 403, error: "HTTP 403", word_count: null, outline: [], schema_types: [] })],
  ...over });

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "contentRecent").mockResolvedValue({ items: [{ id: 3, topic: "old topic", country: "US", language: "en", created_at: "2026-10-30T10:00:00Z", dry_run: false }] });
});

describe("Content Explorer", () => {
  it("searches and shows tiles, results and terms", async () => {
    const run = vi.spyOn(Platform, "contentSearch").mockResolvedValue(search() as any);
    render(<ContentPage />);
    expect(screen.getByText(/≈ \$0\.05–0\.08 per new search/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Topic"), "rare books");
    await userEvent.click(screen.getByRole("button", { name: "Explore" }));
    expect(run).toHaveBeenCalledWith({ topic: "rare books", country: "US", language: "en" });
    expect(await screen.findByText("1,500")).toBeInTheDocument();
    expect(within(screen.getByText("Top schema type").parentElement as HTMLElement).getByText("Article")).toBeInTheDocument();
    expect(screen.getByText(/used by 6 of 1 fetched/)).toBeInTheDocument();
    expect(screen.getByText(/Couldn't fetch \(HTTP 403\)/)).toBeInTheDocument();
    expect(screen.getByText("rare")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /export csv/i })).toHaveAttribute("href", expect.stringContaining("/api/content-explorer/7/csv"));
  });

  it("shows cached state, refreshes, and opens recent searches", async () => {
    vi.spyOn(Platform, "contentGet").mockResolvedValue(search({ cached: true }) as any);
    const run = vi.spyOn(Platform, "contentSearch").mockResolvedValue(search() as any);
    render(<ContentPage />);
    await userEvent.click(await screen.findByRole("button", { name: "old topic" }));
    expect(await screen.findByText(/fetched 2 h ago \(cached\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(run).toHaveBeenCalledWith({ topic: "rare books", country: "US", language: "en", refresh: true });
  });

  it("expands a row's outline and has chart tables", async () => {
    vi.spyOn(Platform, "contentSearch").mockResolvedValue(search() as any);
    render(<ContentPage />);
    await userEvent.type(screen.getByLabelText("Topic"), "rare books");
    await userEvent.click(screen.getByRole("button", { name: "Explore" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show outline: Page 1" }));
    const outline = screen.getByRole("list", { name: "Outline of Page 1" });
    expect(within(outline).getByText("First editions")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /show as table/i })[0]);
    expect(screen.getByRole("cell", { name: "#1" })).toBeInTheDocument();
  });

  it("dry run shows the banner and no cost; errors show", async () => {
    vi.spyOn(Platform, "contentSearch").mockResolvedValueOnce(search({ dry_run: true, notes: ["Backlinks skipped: cap"] }) as any);
    render(<ContentPage />);
    await userEvent.type(screen.getByLabelText("Topic"), "rare books");
    await userEvent.click(screen.getByRole("button", { name: "Explore" }));
    expect(await screen.findByRole("note")).toBeInTheDocument();
    expect(screen.getByText("Dry run: no cost")).toBeInTheDocument();
    expect(screen.getByText("Backlinks skipped: cap")).toBeInTheDocument();
  });
});
