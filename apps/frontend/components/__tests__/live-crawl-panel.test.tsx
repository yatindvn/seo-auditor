import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompactCrawlBar } from "@/components/live-crawl-panel";

vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({
    liveCrawlMetrics: { progress: 40, pages_crawled: 2, current_url: "https://example.com/foo" },
    activityLog: [
      { id: "1", type: "page_crawled", message: "Crawled page", url: "https://example.com/foo", timestamp: Date.now() },
    ],
    livePageRows: [
      { url: "https://example.com/bar", status: 200, depth: 1, response_time: 120 },
    ],
    isLoading: true,
    setSelectedPage: vi.fn(),
  }),
}));

vi.mock("@/services/api", () => ({
  ApiService: {
    pauseAudit: vi.fn(),
    resumeAudit: vi.fn(),
    stopAudit: vi.fn(),
  },
}));

describe("ActivityDrawer crawled pages tab", () => {
  it("shows crawled page URLs when the Crawled Pages tab is clicked", async () => {
    const user = userEvent.setup();
    render(<CompactCrawlBar />);

    await user.click(screen.getByTitle("View activity feed"));
    await user.click(screen.getByRole("button", { name: /Crawled Pages/i }));

    expect(screen.getByText("https://example.com/bar")).toBeInTheDocument();
  });
});
