import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SearchConsolePage from "@/app/projects/[id]/search-console/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/search-console" }));

const overview = (over: object = {}) => ({
  configured: true, dry_run: false, client_email: "sa@proj.iam.gserviceaccount.com", property: "sc-domain:shop.com",
  last_sync_at: "2026-10-29T06:00:00+00:00",
  kpis: { clicks: 560, impressions: 2800, ctr: 0.2, position: 5 },
  previous_kpis: { clicks: 280, impressions: 2800, ctr: 0.1, position: 10 },
  daily: [{ date: "2026-10-01", clicks: 20, impressions: 100, ctr: 0.2, position: 5 }],
  ...over,
});
const list = { total: 1, items: [{ key: "https://shop.com/", clicks: 50, impressions: 900, ctr: 0.055, position: 3 }] };

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "gscPages").mockResolvedValue(list);
  vi.spyOn(Platform, "gscQueries").mockResolvedValue({ total: 1, items: [{ key: "buy books", clicks: 30, impressions: 500, ctr: 0.06, position: 4 }] });
  vi.spyOn(Platform, "gscSites").mockResolvedValue({ configured: true, dry_run: false, client_email: "sa@proj.iam.gserviceaccount.com",
    sites: [{ site_url: "sc-domain:shop.com", permission: "siteOwner" }] });
});

describe("Search Console tab", () => {
  it("explains setup when not configured", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ configured: false, property: null, kpis: null, previous_kpis: null, daily: [] }) as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByText(/GSC_SERVICE_ACCOUNT_FILE/)).toBeInTheDocument();
  });

  it("asks to add the service account when no property is set", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ property: null, kpis: null, previous_kpis: null, daily: [] }) as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByText(/sa@proj.iam.gserviceaccount.com/)).toBeInTheDocument();
  });

  it("shows KPIs with changes (position: lower is better)", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview() as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByText("560")).toBeInTheDocument();
    expect(screen.getByText("20.0%")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 280")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 5")).toBeInTheDocument();   // position 10 → 5
    expect(await screen.findByText("buy books")).toBeInTheDocument();
  });

  it("shows the preview banner in dry run", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ dry_run: true }) as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByRole("note")).toBeInTheDocument();
  });

  it("syncs on demand and re-sorts tables", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview() as any);
    const sync = vi.spyOn(Platform, "gscSync").mockResolvedValue({ status: "synced", property: "sc-domain:shop.com", days: 90, pages: 10, queries: 10, dry_run: false });
    render(<SearchConsolePage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /sync now/i }));
    expect(sync).toHaveBeenCalledWith(7);
    expect(await screen.findByText(/synced 90 days, 10 pages, 10 queries/i)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /^impressions$/i })[0]);
    await waitFor(() => expect(Platform.gscPages).toHaveBeenLastCalledWith(7, "impressions", 0));
  });

  it("charts have a table view", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview() as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    const toggles = await screen.findAllByRole("button", { name: /show as table/i });
    await userEvent.click(toggles[0]);
    expect(screen.getByRole("cell", { name: "Oct 1" })).toBeInTheDocument();
  });

  it("lets you pick the property", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ property: null, kpis: null, previous_kpis: null, daily: [] }) as any);
    const update = vi.spyOn(Platform, "updateProject").mockResolvedValue({} as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    await userEvent.selectOptions(await screen.findByLabelText(/property/i), "sc-domain:shop.com");
    expect(update).toHaveBeenCalledWith(7, { gsc_property: "sc-domain:shop.com" });
  });
});
