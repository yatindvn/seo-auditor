/**
 * The pages table reads a window from the server, not a full array in memory.
 *
 * It used to receive every crawled page as a prop and filter, sort and paginate
 * in the browser. At 5000 pages that array arrives inside a payload too large
 * for the tab to hold, so filtering and sorting move to the query and the table
 * shows one window at a time.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PagesTable } from "@/components/pages-table";
import { ApiService } from "@/services/api";

vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ setSelectedPage: vi.fn() }),
}));

function row(index: number, overrides: Record<string, unknown> = {}) {
  return {
    url: `https://example.com/p${index}`,
    title: `Page ${index}`,
    status: 200,
    depth: 1,
    response_time_ms: 10,
    word_count: 100,
    internal_links_count: 1,
    external_links_count: 0,
    issue_count: 0,
    ...overrides,
  };
}

function envelope(items: unknown[], total: number) {
  return { items, total, offset: 0, limit: 15 };
}

describe("PagesTable", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders the window the server returned", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0), row(1)], 4213),
    );

    render(<PagesTable sessionId="sess_1" />);

    expect(await screen.findByText("https://example.com/p0")).toBeInTheDocument();
    expect(screen.getByText("https://example.com/p1")).toBeInTheDocument();
  });

  it("reports the full total, not the number of rows on screen", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0), row(1)], 4213),
    );

    render(<PagesTable sessionId="sess_1" />);

    expect(await screen.findByText(/4,213/)).toBeInTheDocument();
  });

  it("sends the search to the server rather than filtering in the browser", async () => {
    const getPages = vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0)], 1),
    );
    render(<PagesTable sessionId="sess_1" />);
    await screen.findByText("https://example.com/p0");

    await userEvent.type(screen.getByPlaceholderText(/search/i), "blog");

    await waitFor(() => {
      expect(getPages).toHaveBeenCalledWith(
        "sess_1",
        expect.objectContaining({ filter: "blog" }),
      );
    }, { timeout: 2000 });
  });

  it("sorts through the query, using the column names the API accepts", async () => {
    const getPages = vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0)], 1),
    );
    render(<PagesTable sessionId="sess_1" />);
    await screen.findByText("https://example.com/p0");

    await userEvent.click(screen.getByRole("button", { name: /word count/i }));

    await waitFor(() => {
      expect(getPages).toHaveBeenCalledWith(
        "sess_1",
        expect.objectContaining({ sort: "word_count" }),
      );
    });
  });

  it("surfaces a failed fetch instead of showing an empty table", async () => {
    vi.spyOn(ApiService, "getPages").mockRejectedValue(new Error("backend is down"));

    render(<PagesTable sessionId="sess_1" />);

    expect(await screen.findByText(/backend is down/i)).toBeInTheDocument();
  });

  it("exports through the server, which has every row", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(envelope([row(0)], 4213));
    const download = vi.spyOn(ApiService, "downloadExport").mockResolvedValue(undefined);
    render(<PagesTable sessionId="sess_1" />);
    await screen.findByText("https://example.com/p0");

    await userEvent.click(screen.getByRole("button", { name: /csv/i }));

    expect(download).toHaveBeenCalledWith("csv", "sess_1");
  });
});
