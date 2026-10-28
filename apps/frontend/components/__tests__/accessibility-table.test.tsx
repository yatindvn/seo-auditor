import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AccessibilityTable } from "@/components/platform/accessibility-table";

const violation = {
  id: "color-contrast", impact: "serious" as const, help: "Elements must meet minimum color contrast ratio thresholds",
  help_url: "https://dequeuniversity.com/rules/axe/4.14/color-contrast", wcag: ["wcag2aa", "wcag143"],
  nodes_count: 12, targets: ["#hero > a.btn", "footer p"],
};
const row = (over: object = {}) => ({
  url: "https://a.com/", status: "scanned" as const, error: null, score: 83,
  counts: { critical: 1, serious: 1, moderate: 0, minor: 0 }, violations: [violation], ...over,
});

describe("AccessibilityTable", () => {
  it("shows the score with a labelled pill and the counts", () => {
    render(<AccessibilityTable rows={[row()]} status="scanned" reason={null} />);
    expect(screen.getByText("83")).toBeInTheDocument();
    expect(screen.getByText("Needs work")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /https:\/\/a.com\// })).toHaveTextContent("1");
  });

  it("expands a row to list each failed rule with how to fix it", async () => {
    render(<AccessibilityTable rows={[row()]} status="scanned" reason={null} />);
    await userEvent.click(screen.getByRole("button", { name: /show issues for https:\/\/a.com\//i }));
    expect(screen.getByText(violation.help)).toBeInTheDocument();
    expect(screen.getAllByText("Serious")).toHaveLength(2);   // column header + the impact pill
    expect(screen.getByText("12 elements")).toBeInTheDocument();
    expect(screen.getByText("#hero > a.btn")).toBeInTheDocument();
    expect(screen.getByText("wcag2aa")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /how to fix/i });
    expect(link).toHaveAttribute("href", violation.help_url);
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("explains the score and its limits", () => {
    render(<AccessibilityTable rows={[row()]} status="scanned" reason={null} />);
    expect(screen.getByText(/100 minus 10\/7\/3\/1/)).toBeInTheDocument();
    expect(screen.getByText(/not a full WCAG audit/)).toBeInTheDocument();
  });

  it("shows a failed scan and the empty states", () => {
    const { rerender } = render(<AccessibilityTable rows={[row({ status: "failed", error: "RuntimeError: axe is not defined", score: null })]} status="scanned" reason={null} />);
    expect(screen.getByText(/Couldn't scan: RuntimeError: axe is not defined/)).toBeInTheDocument();
    rerender(<AccessibilityTable rows={[]} status="disabled" reason={null} />);
    expect(screen.getByText(/Accessibility audit/)).toBeInTheDocument();
    rerender(<AccessibilityTable rows={[]} status="unavailable" reason="Playwright is not installed" />);
    expect(screen.getByText(/Browser not available on this server: Playwright is not installed/)).toBeInTheDocument();
  });

  it("calls a perfect page good", () => {
    render(<AccessibilityTable rows={[row({ score: 100, counts: { critical: 0, serious: 0, moderate: 0, minor: 0 }, violations: [] })]} status="scanned" reason={null} />);
    expect(screen.getByText("Good")).toBeInTheDocument();
  });
});
