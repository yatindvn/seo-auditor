/**
 * The Full Site Crawl preset.
 *
 * Disabled since 551c5b9, for a quadratic duplicate pass that 8d29bcd replaced
 * and this branch replaced again. The comment justifying it quoted a docstring
 * that no longer exists.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LandingPage from "@/app/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({
    startNewAudit: vi.fn(),
    setError: vi.fn(),
    isLoading: false,
    error: null,
  }),
}));

const PRESET_DESC = /Enterprise, ecommerce, large docs/i;

function fullSitePreset() {
  return screen.getByText(PRESET_DESC).closest("button");
}

describe("crawl presets", () => {
  it("offers Full Site Crawl as a selectable preset", async () => {
    render(<LandingPage />);

    const preset = fullSitePreset();

    expect(preset).not.toBeNull();
    expect(preset).not.toBeDisabled();
  });

  it("no longer explains why it is closed", () => {
    render(<LandingPage />);

    expect(screen.queryByText(/temporarily closed/i)).toBeNull();
    expect(screen.queryByText(/being optimised/i)).toBeNull();
  });

  it("selecting it applies the preset's page count", async () => {
    render(<LandingPage />);

    await userEvent.click(fullSitePreset()!);

    // The estimate panel reflects the selected preset, and is visible without
    // opening Advanced Overrides.
    expect(await screen.findByText("~5000")).toBeInTheDocument();
  });

  it("states the real page ceiling rather than the one it used to claim", async () => {
    render(<LandingPage />);

    await userEvent.click(fullSitePreset()!);

    // The warning claimed 5,000 while the API refused anything over 1,000.
    // Both are 5,000 now, so the copy and the cap finally agree.
    expect(await screen.findByText(/up to 5,000 pages/i)).toBeInTheDocument();
  });
});
