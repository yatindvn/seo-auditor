import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import BacklinksPage from "@/app/projects/[id]/backlinks/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/backlinks" }));

const totals = (over: object = {}) => ({ taken_at: "2026-10-30T10:00:00+00:00", authority: 412, backlinks: 18230,
  referring_domains: 640, broken_backlinks: 3, dry_run: false, ...over });
const overview = (over: object = {}) => ({
  dry_run_provider: false, schedule: null, last_refresh_at: "2026-10-30T10:00:00+00:00",
  latest: totals(), previous: totals({ authority: 400, referring_domains: 600, backlinks: 18000, broken_backlinks: 5 }),
  history: [{ date: "2026-09-01", authority: 400, backlinks: 18000, referring_domains: 600, source: "history" },
            { date: "2026-10-30", authority: 412, backlinks: 18230, referring_domains: 640, source: "snapshot" }],
  ...over,
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "refDomains").mockResolvedValue({ total: 1, items: [{ domain: "news.com", rank: 700, backlinks: 12, first_seen: null }] });
  vi.spyOn(Platform, "backlinkLinks").mockResolvedValue({ total: 1, items: [{ url_from: "https://blog.net/p", url_to: "https://shop.com/old",
    anchor: "shop", domain_from_rank: 600, dofollow: true, first_seen: null, last_seen: null, target_status: 404, crawled_status: 404 }] });
  vi.spyOn(Platform, "listCompetitors").mockResolvedValue({ items: [{ id: 1, domain: "rival.com" }, { id: 2, domain: "other.com" }] } as any);
});

describe("Backlinks tab", () => {
  it("shows an empty state before the first refresh", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview({ latest: null, previous: null, history: [] }) as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    expect(await screen.findByText(/No backlink data yet/)).toBeInTheDocument();
  });

  it("labels authority as DataForSEO's and shows changes (broken: lower is better)", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    expect(await screen.findByText("412")).toBeInTheDocument();
    expect(screen.getByText(/DataForSEO rank, 0–1000/)).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 40")).toBeInTheDocument();     // referring domains 600 -> 640
    expect(screen.getByLabelText("improved by 2")).toBeInTheDocument();      // broken 5 -> 3
    expect(await screen.findByText("news.com")).toBeInTheDocument();
    expect((await screen.findAllByText(/Redirect this URL/)).length).toBeGreaterThan(0);
  });

  it("shows the preview banner on dry run", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview({ dry_run_provider: true }) as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    expect((await screen.findAllByRole("note")).length).toBeGreaterThan(0);
  });

  it("toggles the weekly refresh and refreshes on demand", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    const update = vi.spyOn(Platform, "updateProject").mockResolvedValue({} as any);
    const refresh = vi.spyOn(Platform, "refreshBacklinks").mockResolvedValue({ status: "capped", dry_run: false,
      message: "daily cap of 20 dataforseo_backlinks calls reached" });
    render(<BacklinksPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("switch", { name: /weekly refresh/i }));
    expect(update).toHaveBeenCalledWith(7, { backlink_schedule: "weekly" });
    await userEvent.click(screen.getByRole("button", { name: /refresh now/i }));
    expect(refresh).toHaveBeenCalledWith(7);
    expect(await screen.findByText(/daily cap of 20/)).toBeInTheDocument();
  });

  it("charts have a table view that marks history rows", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    await userEvent.click((await screen.findAllByRole("button", { name: /show as table/i }))[0]);
    expect(screen.getByText(/from DataForSEO history/)).toBeInTheDocument();
  });

  it("runs the link gap with the chosen competitors", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    const gap = vi.spyOn(Platform, "backlinkGap").mockResolvedValue({ my_domain: "shop.com", competitors: ["rival.com", "other.com"],
      dry_run: false, rows: [{ domain: "both.com", rank: 700, linked_count: 2, backlinks_by_competitor: { "rival.com": 1, "other.com": 4 } }] });
    render(<BacklinksPage params={{ id: "7" }} />);
    expect(await screen.findByLabelText("rival.com")).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /run link gap/i }));
    await waitFor(() => expect(gap).toHaveBeenCalledWith(7, ["rival.com", "other.com"]));
    expect(await screen.findByText("both.com")).toBeInTheDocument();
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
  });
});
