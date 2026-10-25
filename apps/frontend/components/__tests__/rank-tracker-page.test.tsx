import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RanksPage from "@/app/projects/[id]/ranks/page";
import { RankHistoryChart } from "@/components/platform/rank-history-chart";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/ranks" }));

const kw = (id: number, phrase: string, position: number | null, change: number | null) => ({
  id, phrase, country: "US", device: "desktop", language: "en", enabled: true, change,
  latest: position === null ? null : { position, ranking_url: "https://example.com/e", status: "ranked",
                                       checked_at: "2026-10-25T09:00:00+00:00", note: null, competitor_positions: {} },
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [{ id: 7, domain: "example.com", name: "example.com", alert_settings: {} }] } as any);
  vi.spyOn(Platform, "listCompetitors").mockResolvedValue({ items: [{ id: 1, domain: "rival.org" }] });
});

describe("Rank Tracker page", () => {
  it("lists keywords with position and the change as a rank delta", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [kw(1, "espresso", 9, -5)] } as any);
    render(<RanksPage params={{ id: "7" }} />);
    const row = (await screen.findByText("espresso")).closest("tr")!;
    expect(within(row).getByText("9")).toBeInTheDocument();
    expect(within(row).getByLabelText("worse by 5")).toBeInTheDocument();
  });

  it("adds keywords one per line with country and device", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [] } as any);
    const add = vi.spyOn(Platform, "addKeywords").mockResolvedValue({ created: 2, skipped: 0 });
    render(<RanksPage params={{ id: "7" }} />);
    await userEvent.type(await screen.findByLabelText(/keywords to track/i), "espresso{enter}milk frother");
    await userEvent.selectOptions(screen.getByLabelText(/device/i), "mobile");
    await userEvent.click(screen.getByRole("button", { name: /add keywords/i }));
    expect(add).toHaveBeenCalledWith(7, [
      { phrase: "espresso", country: "US", device: "mobile" },
      { phrase: "milk frother", country: "US", device: "mobile" },
    ]);
  });

  it("previews a check on click only, and labels it", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [kw(1, "espresso", 4, null)] } as any);
    const preview = vi.spyOn(Platform, "previewRankCheck").mockResolvedValue({
      dry_run: true, results: [{ phrase: "espresso", position: 3, ranking_url: null, competitor_positions: {} }],
    });
    render(<RanksPage params={{ id: "7" }} />);
    await screen.findByText("espresso");
    expect(preview).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /preview check/i }));
    expect(await screen.findByRole("note")).toHaveTextContent(/made up/i);
  });

  it("invites adding keywords when none are tracked", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [] } as any);
    render(<RanksPage params={{ id: "7" }} />);
    expect(await screen.findByText(/no keywords tracked yet/i)).toBeInTheDocument();
  });
});

describe("RankHistoryChart", () => {
  it("offers the same data as a table, with competitors and gaps", async () => {
    const history = [
      { position: 4, ranking_url: null, status: "ranked", checked_at: "2026-10-20T09:00:00+00:00", note: null, competitor_positions: { "rival.org": 2 } },
      { position: null, ranking_url: null, status: "skipped", checked_at: "2026-10-21T09:00:00+00:00", note: "cap", competitor_positions: {} },
    ] as any;
    render(<RankHistoryChart history={history} competitors={["rival.org"]} myDomain="example.com" />);
    await userEvent.click(screen.getByRole("button", { name: /show as table/i }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("example.com")).toBeInTheDocument();
    expect(within(table).getByText("rival.org")).toBeInTheDocument();
    expect(within(table).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
