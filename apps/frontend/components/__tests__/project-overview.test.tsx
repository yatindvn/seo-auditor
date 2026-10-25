import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import OverviewPage from "@/app/projects/[id]/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7" }));

const audit = (id: number, score: number) => ({
  id, session_id: `s${id}`, status: "completed", trigger: "manual", start_url: "https://example.com/",
  started_at: `2026-10-2${id}T10:00:00+00:00`, finished_at: `2026-10-2${id}T10:00:00+00:00`, page_count: 40, health_score: score,
});
const kw = (id: number, position: number, change: number) => ({
  id, phrase: `keyword ${id}`, country: "US", device: "desktop", language: "en", enabled: true, change,
  latest: { position, ranking_url: null, status: "ranked", checked_at: "", note: null, competitor_positions: {} },
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [kw(1, 4, -5), kw(2, 10, 2)] } as any);
});

describe("Project overview", () => {
  it("shows KPIs with the health change and the diff", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(2, 75), audit(1, 72)], total: 2, offset: 0, limit: 50 } as any);
    const diff = vi.spyOn(Platform, "auditDiff").mockResolvedValue({
      old_audit_id: 1, new_audit_id: 2, health_score_change: 3,
      issues: { new: [], fixed: [], new_count: 4, fixed_count: 9, persisting_count: 20 },
      pages: { added: [], removed: [], status_changed: [], added_count: 0, removed_count: 0, status_changed_count: 0 },
    });
    render(<OverviewPage params={{ id: "7" }} />);

    expect(await screen.findByText("75")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 3")).toBeInTheDocument();
    expect(await screen.findByText(/4 new/i)).toBeInTheDocument();
    expect(screen.getByText(/9 fixed/i)).toBeInTheDocument();
    expect(diff).toHaveBeenCalledWith(2);
    expect(screen.getByText("7")).toBeInTheDocument();            // average position of 4 and 10
    expect(screen.getByText("keyword 1")).toBeInTheDocument();    // biggest move
  });

  it("does not ask for a diff with a single audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(1, 72)], total: 1, offset: 0, limit: 50 } as any);
    const diff = vi.spyOn(Platform, "auditDiff");
    render(<OverviewPage params={{ id: "7" }} />);
    expect(await screen.findByText(/run a second audit to compare/i)).toBeInTheDocument();
    expect(diff).not.toHaveBeenCalled();
  });

  it("invites a first audit for a project with none", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 } as any);
    render(<OverviewPage params={{ id: "7" }} />);
    expect(await screen.findByText(/no audits yet/i)).toBeInTheDocument();
  });
});
