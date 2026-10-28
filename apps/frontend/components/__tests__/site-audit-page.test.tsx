import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SiteAuditPage from "@/app/projects/[id]/audits/page";
import { useSessionParam } from "@/lib/session-param";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/audits" }));

const audit = (id: number) => ({
  id, session_id: `sess_${id}`, status: "completed", trigger: id === 3 ? "scheduled" : "manual",
  start_url: "https://example.com/", started_at: `2026-10-2${id}T10:00:00+00:00`,
  finished_at: `2026-10-2${id}T10:00:00+00:00`, page_count: 40 + id, health_score: 70 + id,
});
const diff = {
  old_audit_id: 2, new_audit_id: 3, health_score_change: 1,
  issues: {
    new: [{ url: "/b", code: "STATUS_404", severity: "critical", message: "404" },
          { url: "/c", code: "MISSING_H1", severity: "warning", message: "no h1" }],
    fixed: [{ url: "/a", code: "THIN_CONTENT", severity: "warning", message: "thin" }],
    new_count: 2, fixed_count: 1, persisting_count: 10,
  },
  pages: { added: ["/fresh"], removed: [], status_changed: [{ url: "/b", old_status: 200, new_status: 404 }],
           added_count: 1, removed_count: 0, status_changed_count: 1 },
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "auditVitals").mockResolvedValue({ audit_id: 3, status: "not_configured", items: [] });
  vi.spyOn(Platform, "auditRendering").mockResolvedValue({ audit_id: 3, status: "disabled", reason: null, items: [] });
  vi.spyOn(Platform, "auditAccessibility").mockResolvedValue({ audit_id: 3, status: "disabled", reason: null, axe_version: null, items: [] });
});

describe("Site Audit page", () => {
  it("compares the newest audit with the previous by default", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3), audit(2), audit(1)], total: 3, offset: 0, limit: 50 } as any);
    const getDiff = vi.spyOn(Platform, "auditDiff").mockResolvedValue(diff as any);
    render(<SiteAuditPage params={{ id: "7" }} />);

    expect(await screen.findByText("STATUS_404")).toBeInTheDocument();
    expect(getDiff).toHaveBeenCalledWith(3, 2);
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("/fresh")).toBeInTheDocument();
    expect(screen.getByText(/200 → 404/)).toBeInTheDocument();
  });

  it("lets you pick which audits to compare", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3), audit(2), audit(1)], total: 3, offset: 0, limit: 50 } as any);
    const getDiff = vi.spyOn(Platform, "auditDiff").mockResolvedValue(diff as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    await screen.findByText("STATUS_404");

    // Option values are audit ids: "1" picks audit 1.
    await userEvent.selectOptions(screen.getByLabelText(/compare against/i), "1");
    expect(getDiff).toHaveBeenLastCalledWith(3, 1);
  });

  it("labels compare options with the audit number, so same-minute audits differ", async () => {
    const sameMinute = (id: number) => ({ ...audit(id), finished_at: "2026-10-25T10:00:00+00:00" });
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [sameMinute(3), sameMinute(2)], total: 2, offset: 0, limit: 50 } as any);
    vi.spyOn(Platform, "auditDiff").mockResolvedValue(diff as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    await screen.findByText("STATUS_404");

    const labels = Array.from((screen.getByLabelText(/^compare audit/i) as HTMLSelectElement).options).map((o) => o.text);
    expect(labels[0]).toMatch(/^#3 · /);
    expect(labels[1]).toMatch(/^#2 · /);
  });

  it("shows Core Web Vitals for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/PSI_API_KEY/)).toBeInTheDocument();
    expect(Platform.auditVitals).toHaveBeenCalledWith(3);
  });

  it("shows JavaScript rendering for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/Not rendered/)).toBeInTheDocument();
    expect(Platform.auditRendering).toHaveBeenCalledWith(3);
  });

  it("shows accessibility for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/Not scanned/)).toBeInTheDocument();
    expect(Platform.auditAccessibility).toHaveBeenCalledWith(3);
  });

  it("links each audit to its full report", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    const link = await screen.findByRole("link", { name: /open report/i });
    expect(link).toHaveAttribute("href", "/dashboard?session=sess_3");
    expect(screen.getByText(/run a second audit to compare/i)).toBeInTheDocument();
  });
});

describe("useSessionParam", () => {
  it("opens the report named in ?session=", () => {
    window.history.pushState({}, "", "/dashboard?session=sess_9");
    const start = vi.fn();
    renderHook(() => useSessionParam("sess_1", start));
    expect(start).toHaveBeenCalledWith("sess_9");
  });

  it("does nothing when it is already open", () => {
    window.history.pushState({}, "", "/dashboard?session=sess_1");
    const start = vi.fn();
    renderHook(() => useSessionParam("sess_1", start));
    expect(start).not.toHaveBeenCalled();
  });
});
