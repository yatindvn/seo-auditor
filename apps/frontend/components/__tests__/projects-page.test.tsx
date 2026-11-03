import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import ProjectsPage from "@/app/projects/page";
import { ProjectTabs } from "@/components/platform/project-tabs";
import { ApiError, Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/projects/7/ranks",
}));

const project = (over = {}) => ({
  id: 7, name: "example.com", domain: "example.com", audit_schedule: null, audit_options: {},
  rank_schedule: "daily" as const, alert_settings: {}, audit_count: 3,
  latest_audit: { id: 30, finished_at: "2026-10-24T10:00:00+00:00", health_score: 72.5 }, ...over,
});

beforeEach(() => vi.restoreAllMocks());

describe("Projects page", () => {
  it("lists projects with health and audit count", async () => {
    vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [project()] });
    render(<ProjectsPage />);
    const card = await screen.findByRole("link", { name: /example\.com/i });
    expect(card).toHaveAttribute("href", "/projects/7");
    expect(within(card).getByText("72.5")).toBeInTheDocument();
    expect(within(card).getByText(/3 audits/i)).toBeInTheDocument();
  });

  it("names each card by what it shows, so voice users can say what they see (axe label-content-name-mismatch)", async () => {
    vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [project()] });
    render(<ProjectsPage />);
    const card = await screen.findByRole("link", { name: /example\.com.*health.*72\.5.*3 audits/i });
    expect(card).not.toHaveAttribute("aria-label");
  });

  it("invites a first audit when there are none", async () => {
    vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [] });
    render(<ProjectsPage />);
    expect(await screen.findByText(/no projects yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /run your first audit/i })).toHaveAttribute("href", "/");
  });

  it("explains an outage", async () => {
    vi.spyOn(Platform, "listProjects").mockRejectedValue(new ApiError(503, "central database unavailable"));
    render(<ProjectsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable right now/i);
  });
});

describe("ProjectTabs", () => {
  it("marks the tab for the current path", () => {
    render(<ProjectTabs projectId={7} />);
    expect(screen.getByRole("link", { name: "Rank Tracker" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Content Gap" })).toHaveAttribute("href", "/projects/7/gap");
  });
});
