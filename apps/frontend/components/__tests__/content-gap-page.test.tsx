import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import GapPage from "@/app/projects/[id]/gap/page";
import { ApiError, Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/gap" }));

const result = {
  my_domain: "example.com", competitors: ["rival.org", "other.net"], dry_run: true, total_gaps: 1,
  rows: [{ keyword: "milk frother", search_volume: 4000, difficulty: 20, opportunity: 3200,
           best_competitor_position: 4, competitors: { "rival.org": { position: 4, url: "https://rival.org/m" } } }],
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "listCompetitors").mockResolvedValue({ items: [{ id: 1, domain: "rival.org" }, { id: 2, domain: "other.net" }] });
});

describe("Content Gap page", () => {
  it("does nothing until Run, then shows ranked gaps with the preview banner", async () => {
    const gap = vi.spyOn(Platform, "contentGap").mockResolvedValue(result);
    render(<GapPage params={{ id: "7" }} />);
    await screen.findByLabelText("rival.org");
    expect(gap).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /^run/i }));
    expect(gap).toHaveBeenCalledWith(7, { competitors: ["rival.org", "other.net"], country: "US", language: "en", limit: 500 });
    expect(await screen.findByText("milk frother")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/made up/i);
    expect(screen.getByRole("link", { name: /download csv \(preview\)/i }).getAttribute("href"))
      .toMatch(/content-gap\.csv\?country=US&language=en&limit=500&competitor=rival\.org&competitor=other\.net/);
  });

  it("runs only for the ticked competitors", async () => {
    const gap = vi.spyOn(Platform, "contentGap").mockResolvedValue(result);
    render(<GapPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByLabelText("other.net"));
    await userEvent.click(screen.getByRole("button", { name: /^run/i }));
    expect(gap).toHaveBeenCalledWith(7, expect.objectContaining({ competitors: ["rival.org"] }));
  });

  it("shows why it could not run", async () => {
    vi.spyOn(Platform, "contentGap").mockRejectedValue(new ApiError(429, "daily cap of 20 dataforseo_labs calls reached"));
    render(<GapPage params={{ id: "7" }} />);
    await screen.findByLabelText("rival.org");
    await userEvent.click(screen.getByRole("button", { name: /^run/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/daily cap of 20/);
  });

  it("asks for competitors when the project has none", async () => {
    vi.spyOn(Platform, "listCompetitors").mockResolvedValue({ items: [] });
    render(<GapPage params={{ id: "7" }} />);
    expect(await screen.findByText(/add competitors first/i)).toBeInTheDocument();
  });
});
