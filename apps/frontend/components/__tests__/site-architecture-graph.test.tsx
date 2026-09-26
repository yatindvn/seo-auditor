/**
 * The architecture graph draws sections, not pages.
 *
 * A node per page is ~5000 nodes and a few hundred thousand edges at the Full
 * Site Crawl preset, which no browser renders interactively. Pages group by
 * their first path segment and one section expands at a time.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SiteArchitectureGraph } from "@/components/site-architecture-graph";
import { ApiService } from "@/services/api";

const setSelectedPage = vi.fn();

vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ activeSessionId: "sess_1", setSelectedPage }),
}));

const CLUSTERED = {
  clustered: true,
  nodes: [
    { id: "home", label: "home", count: 1, url: "https://example.com/", is_page: true },
    { id: "/blog", label: "/blog", count: 412, url: null, is_page: false },
    { id: "/products", label: "/products", count: 2847, url: null, is_page: false },
  ],
  links: [{ source: "home", target: "/blog", weight: 12 }],
};

const EXPANDED = {
  clustered: false,
  expanded: "/blog",
  nodes: [
    { url: "https://example.com/blog/a", depth: 1, status: 200, title: "A" },
    { url: "https://example.com/blog/b", depth: 2, status: 200, title: "B" },
  ],
  links: [{ source: "https://example.com/blog/a", target: "https://example.com/blog/b" }],
};

describe("SiteArchitectureGraph", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setSelectedPage.mockClear();
  });

  it("renders one node per section, not per page", async () => {
    vi.spyOn(ApiService, "getArchitecture").mockResolvedValue(CLUSTERED);

    render(<SiteArchitectureGraph />);

    await waitFor(() => {
      expect(screen.getAllByTestId("graph-node")).toHaveLength(3);
    });
  });

  it("shows how many pages a section stands for", async () => {
    vi.spyOn(ApiService, "getArchitecture").mockResolvedValue(CLUSTERED);

    render(<SiteArchitectureGraph />);

    expect(await screen.findByText(/2,847/)).toBeInTheDocument();
  });

  it("expands a section into its pages on click", async () => {
    const getArchitecture = vi.spyOn(ApiService, "getArchitecture")
      .mockResolvedValueOnce(CLUSTERED)
      .mockResolvedValueOnce(EXPANDED);
    render(<SiteArchitectureGraph />);
    await screen.findByText("/blog");

    await userEvent.click(screen.getByText("/blog"));

    await waitFor(() => {
      expect(getArchitecture).toHaveBeenLastCalledWith("sess_1", "/blog");
    });
    expect(await screen.findByText(/example\.com\/blog\/a/)).toBeInTheDocument();
  });

  it("offers a way back to the whole site once expanded", async () => {
    vi.spyOn(ApiService, "getArchitecture")
      .mockResolvedValueOnce(CLUSTERED)
      .mockResolvedValueOnce(EXPANDED)
      .mockResolvedValueOnce(CLUSTERED);
    render(<SiteArchitectureGraph />);
    await screen.findByText("/blog");
    await userEvent.click(screen.getByText("/blog"));
    await screen.findByText(/example\.com\/blog\/a/);

    await userEvent.click(screen.getByRole("button", { name: /all sections/i }));

    await waitFor(() => expect(screen.getByText("/products")).toBeInTheDocument());
  });

  it("opens a single page rather than expanding it", async () => {
    vi.spyOn(ApiService, "getArchitecture").mockResolvedValue(CLUSTERED);
    render(<SiteArchitectureGraph />);
    await screen.findByText("home");

    await userEvent.click(screen.getByText("home"));

    expect(setSelectedPage).toHaveBeenCalledWith(
      expect.objectContaining({ url: "https://example.com/" }),
    );
  });
});
