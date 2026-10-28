import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { RenderingTable } from "@/components/platform/rendering-table";

const row = (over: object = {}) => ({
  url: "https://a.com/", status: "rendered" as const, error: null, render_ms: 812, raw_word_count: 40,
  rendered_word_count: 900, changes: { title: { raw: "Loading…", rendered: "Shop" }, meta_robots: { raw: null, rendered: "noindex" } },
  js_only_links: ["https://a.com/x"], js_only_links_count: 1, ...over,
});

describe("RenderingTable", () => {
  it("shows word counts, change chips and JS-only links", () => {
    render(<RenderingTable rows={[row()]} status="rendered" reason={null} />);
    expect(screen.getByText("40 → 900")).toBeInTheDocument();
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Robots")).toBeInTheDocument();
    expect(screen.getByText("Content")).toBeInTheDocument();
    expect(screen.getByText("0.8 s")).toBeInTheDocument();
  });

  it("expands a row to show raw against rendered", async () => {
    render(<RenderingTable rows={[row()]} status="rendered" reason={null} />);
    await userEvent.click(screen.getByRole("button", { name: /show changes for https:\/\/a.com\//i }));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.getByText("noindex")).toBeInTheDocument();
    expect(screen.getByText("https://a.com/x")).toBeInTheDocument();
  });

  it("says when nothing changed", () => {
    render(<RenderingTable rows={[row({ changes: {}, rendered_word_count: 41, js_only_links: [], js_only_links_count: 0 })]} status="rendered" reason={null} />);
    expect(screen.getByText("No differences")).toBeInTheDocument();
  });

  it("shows a failed render's error", () => {
    render(<RenderingTable rows={[row({ status: "failed", error: "TimeoutError: 20000ms" })]} status="rendered" reason={null} />);
    expect(screen.getByText(/Couldn't render: TimeoutError: 20000ms/)).toBeInTheDocument();
  });

  it("explains the disabled and unavailable states", () => {
    const { rerender } = render(<RenderingTable rows={[]} status="disabled" reason={null} />);
    expect(screen.getByText(/Render JavaScript/)).toBeInTheDocument();
    rerender(<RenderingTable rows={[]} status="unavailable" reason="Playwright is not installed" />);
    expect(screen.getByText(/Browser not available on this server: Playwright is not installed/)).toBeInTheDocument();
  });
});
