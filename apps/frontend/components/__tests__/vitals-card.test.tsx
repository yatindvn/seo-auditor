import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { VitalsCard } from "@/components/platform/vitals-card";
import { ApiError, Platform } from "@/services/platform";

const point = (id: number, over: object = {}) => ({
  audit_id: id, finished_at: `2026-10-2${id}T10:00:00+00:00`, url: "https://a.com/", source: "psi",
  data_kind: "lab", performance_score: 60 + id, lcp_ms: 4800, inp_ms: null, cls: 0.05, tbt_ms: 350,
  rating: "poor", metric_ratings: { lcp_ms: "poor", inp_ms: null, cls: "good", tbt_ms: "needs_improvement" },
  ...over,
});

beforeEach(() => vi.restoreAllMocks());

describe("VitalsCard", () => {
  it("shows the homepage's latest lab numbers with TBT in place of INP", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockResolvedValue({ url: "https://a.com/", points: [point(1), point(2)] } as any);
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByText("4.8 s")).toBeInTheDocument();
    expect(screen.getByText("TBT (lab)")).toBeInTheDocument();
    expect(screen.getByText("350 ms")).toBeInTheDocument();
    expect(screen.getByText(/lab data · psi/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show as table/i }));
    expect(screen.getByRole("cell", { name: "62" })).toBeInTheDocument();
  });

  it("uses INP when the data is from real users", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockResolvedValue({ url: "https://a.com/", points: [
      point(1, { data_kind: "field", inp_ms: 180, metric_ratings: { lcp_ms: "poor", inp_ms: "good", cls: "good", tbt_ms: null } })] } as any);
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByText("INP")).toBeInTheDocument();
    expect(screen.getByText(/field data/i)).toBeInTheDocument();
  });

  it("explains how to start measuring when there is nothing yet", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockResolvedValue({ url: null, points: [] });
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByText(/not measured yet/i)).toBeInTheDocument();
  });

  it("offers a retry on error", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockRejectedValue(new ApiError(503, "central database unavailable"));
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
