/** Each public page explains itself in at least 150 words, the site audit's
 *  thin-content line (counted the same way: words of visible text). */
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

import HomePage from "@/app/(audit)/(home)/page";
import KeywordsPage from "@/app/keywords/page";
import ContentPage from "@/app/content/page";
import ProjectsPage from "@/app/projects/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/" }));
vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ startNewAudit: vi.fn(), setError: vi.fn(), isLoading: false, error: null }),
}));

const words = (el: HTMLElement) => {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("script, style, noscript").forEach((n) => n.remove());
  return (clone.textContent ?? "").toLowerCase().match(/[a-z']+/g)?.length ?? 0;
};

describe("page depth", () => {
  it.each([
    ["home", () => <HomePage />],
    ["keywords", () => <KeywordsPage />],
    ["content", () => <ContentPage />],
  ])("%s has at least 150 words", (_, page) => {
    vi.spyOn(Platform, "contentRecent").mockResolvedValue({ items: [] });
    const { container } = render(page());
    expect(words(container)).toBeGreaterThanOrEqual(150);
  });

  it("projects has at least 150 words even with no projects yet", async () => {
    vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [] });
    const { container } = render(await ProjectsPage());
    expect(words(container)).toBeGreaterThanOrEqual(150);
  });
});
