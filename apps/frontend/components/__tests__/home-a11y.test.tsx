/** The homepage form and outline, as the site audit checks them. */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import LandingPage from "@/app/(audit)/(home)/page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ startNewAudit: vi.fn(), setError: vi.fn(), isLoading: false, error: null }),
}));

describe("homepage accessibility", () => {
  it("connects the Target URL label to its field (a placeholder is not a label)", () => {
    render(<LandingPage />);
    const field = screen.getByLabelText("Target URL");
    expect(field).toHaveAttribute("placeholder", "https://example.com");
  });

  it("never skips a heading level", () => {
    const { container } = render(<LandingPage />);
    const levels = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((h) => Number(h.tagName[1]));
    expect(levels[0]).toBe(1);
    levels.slice(1).forEach((level, i) => expect(level - levels[i]).toBeLessThanOrEqual(1));
    expect(screen.getByRole("heading", { level: 2, name: "What every audit covers" })).toBeInTheDocument();
  });
});
