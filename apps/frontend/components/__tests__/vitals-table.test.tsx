import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { VitalsTable } from "@/components/platform/vitals-table";

const row = (over: object = {}) => ({
  url: "https://a.com/", strategy: "mobile", source: "lighthouse" as const, data_kind: "lab" as const,
  rating: "poor" as const, performance_score: 41, lcp_ms: 4800, inp_ms: null, cls: 0.12, fcp_ms: null,
  ttfb_ms: null, tbt_ms: 90, error: null,
  metric_ratings: { lcp_ms: "poor" as const, inp_ms: null, cls: "needs_improvement" as const, tbt_ms: "good" as const },
  ...over,
});

describe("VitalsTable", () => {
  it("shows values with text-labelled ratings and the data kind", () => {
    render(<VitalsTable rows={[row()]} status="measured" />);
    expect(screen.getByText("4.8 s")).toBeInTheDocument();
    expect(screen.getByText("Poor")).toBeInTheDocument();
    expect(screen.getByText("Needs improvement")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument();
    expect(screen.getByText(/lab · lighthouse/i)).toBeInTheDocument();
  });

  it("shows why a page was not measured", () => {
    render(<VitalsTable rows={[row({ source: "not_measured", error: "psi: daily cap of 50 psi calls reached" })]} status="measured" />);
    expect(screen.getByText(/daily cap of 50/)).toBeInTheDocument();
  });

  it("explains how to turn measurement on", () => {
    render(<VitalsTable rows={[]} status="not_configured" />);
    expect(screen.getByText(/PSI_API_KEY/)).toBeInTheDocument();
  });

  it("says when it was turned off for the audit", () => {
    render(<VitalsTable rows={[]} status="disabled" />);
    expect(screen.getByText(/turned off for this audit/i)).toBeInTheDocument();
  });
});
