import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import KeywordsPage from "@/app/keywords/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/keywords" }));

const result = {
  seed: "espresso machine", country: "US", language: "en", dry_run: true, notes: [],
  keywords: [
    { keyword: "espresso machine", source: "seed", search_volume: 74000, cpc: 1.2, competition: "HIGH", difficulty: 62, traffic_potential_estimate: 20720 },
    { keyword: "is an espresso machine worth it?", source: "people_also_ask", search_volume: null, cpc: null, competition: null, difficulty: null, traffic_potential_estimate: null },
  ],
  clusters: [["espresso machine", "best espresso machine"]],
};

beforeEach(() => vi.restoreAllMocks());

describe("Keywords Explorer", () => {
  it("explores without clustering by default and labels the estimate", async () => {
    const explore = vi.spyOn(Platform, "explore").mockResolvedValue(result as any);
    render(<KeywordsPage />);
    expect(screen.getByLabelText(/group into clusters/i)).not.toBeChecked();
    await userEvent.type(screen.getByLabelText(/seed keyword/i), "Espresso Machine");
    await userEvent.click(screen.getByRole("button", { name: /explore/i }));

    expect(explore).toHaveBeenCalledWith({ seed: "Espresso Machine", country: "US", language: "en", cluster: false });
    expect(await screen.findByText("is an espresso machine worth it?")).toBeInTheDocument();
    expect(screen.getByText(/traffic \(est\.\)/i)).toBeInTheDocument();
    expect(screen.getByText("People Also Ask")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/made up/i);
  });

  it("shows clusters when asked for", async () => {
    vi.spyOn(Platform, "explore").mockResolvedValue(result as any);
    render(<KeywordsPage />);
    await userEvent.type(screen.getByLabelText(/seed keyword/i), "espresso machine");
    await userEvent.click(screen.getByLabelText(/group into clusters/i));
    await userEvent.click(screen.getByRole("button", { name: /explore/i }));
    expect(await screen.findByText("best espresso machine")).toBeInTheDocument();
  });

  it("starts with an empty state and no request", () => {
    const explore = vi.spyOn(Platform, "explore");
    render(<KeywordsPage />);
    expect(screen.getByText(/enter a seed keyword/i)).toBeInTheDocument();
    expect(explore).not.toHaveBeenCalled();
  });
});
