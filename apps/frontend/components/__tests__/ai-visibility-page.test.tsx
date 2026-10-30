import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AiVisibilityPage from "@/app/projects/[id]/ai-visibility/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/ai-visibility" }));

const rates = (m: number, p: number | null, c: number) => ({ mention_rate: m, avg_position: p, cited_rate: c });
const summary = (id: number, m: number, p: number | null, c: number) => ({
  run_id: id, started_at: `2026-10-2${id}T10:00:00+00:00`, dry_run: false, calls: 6, errors: 0, ...rates(m, p, c),
  by_provider: { claude: rates(m, p, c), openai: rates(m, p, c) } });
const providers = [{ name: "claude", model: "claude-sonnet-5", dry_run: false, configured: true, hint: null },
                   { name: "openai", model: "gpt-x", dry_run: false, configured: true, hint: null },
                   { name: "gemini", model: null, dry_run: false, configured: false, hint: "set GEMINI_API_KEY and GEMINI_MODEL" }];
const overview = (over: object = {}) => ({
  providers, dry_run: false, schedule: null, last_run_at: null,
  latest: summary(2, 0.6, 1.5, 0.4), previous: summary(1, 0.4, 2, 0.4),
  trend: [{ run_id: 1, started_at: "2026-10-21T10:00:00+00:00", mention_rate: 0.4, by_provider: { claude: 0.5, openai: 0.3 } },
          { run_id: 2, started_at: "2026-10-22T10:00:00+00:00", mention_rate: 0.6, by_provider: { claude: 0.7, openai: 0.5 } }],
  share_of_voice: [{ owner: "books.toscrape.com", is_self: true, rate: 0.6 }, { owner: "amazon.com", is_self: false, rate: 0.5 }],
  top_cited: [{ domain: "books.toscrape.com", count: 3, is_self: true }],
  ...over,
});
const answer = { id: 1, prompt: "best rare books", provider: "claude", model: "claude-sonnet-5", mentioned: true, position: 2,
  brands: ["amazon.com", "books.toscrape.com"], cited: true, error: null, answer: "Amazon then Books to Scrape.",
  citations: [{ url: "https://books.toscrape.com/", title: "Books" }, { url: "javascript:alert(1)", title: "evil" }],
  highlights: [{ start: 0, end: 6, owner: "amazon.com" }, { start: 12, end: 27, owner: "books.toscrape.com" }] };

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "aiPrompts").mockResolvedValue({ items: [{ id: 1, text: "best rare books", enabled: true }, { id: 2, text: "cheap books", enabled: true }] });
  vi.spyOn(Platform, "aiBrands").mockResolvedValue({ self: { domain: "books.toscrape.com", terms: ["BTS"] },
    competitors: [{ domain: "amazon.com", terms: ["Amazon"] }] });
  vi.spyOn(Platform, "aiAnswers").mockResolvedValue({ run_id: 2, total: 1, items: [answer] });
});

describe("AI Visibility tab", () => {
  it("shows KPIs with changes (position: lower is better)", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText("60%")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 20 pts")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 0.5")).toBeInTheDocument();
    expect(screen.getByText(/set GEMINI_API_KEY and GEMINI_MODEL/)).toBeInTheDocument();
  });

  it("shows an empty state before the first run, and the preview banner on dry run", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview({ latest: null, previous: null, trend: [], share_of_voice: [], top_cited: [], dry_run: true }) as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
    expect(screen.getAllByRole("note").length).toBeGreaterThan(0);
    expect(screen.getByText(/Dry run: no cost/)).toBeInTheDocument();
  });

  it("runs now with a cost estimate, and toggles weekly", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    const run = vi.spyOn(Platform, "runAi").mockResolvedValue({ status: "ran", run_id: 3, calls: 4, errors: 1, dry_run: false, mention_rate: 0.5 });
    const update = vi.spyOn(Platform, "updateProject").mockResolvedValue({} as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText(/≈ \$0\.12/)).toBeInTheDocument();          // 2 prompts × 2 configured models
    await userEvent.click(screen.getByRole("button", { name: /run now/i }));
    expect(run).toHaveBeenCalledWith(7);
    expect(await screen.findByText(/Ran 4 calls \(1 failed\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: /weekly/i }));
    expect(update).toHaveBeenCalledWith(7, { ai_schedule: "weekly" });
  });

  it("adds prompts and brand aliases", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    const add = vi.spyOn(Platform, "addAiPrompt").mockResolvedValue({ id: 3, text: "rare first editions", enabled: true });
    const save = vi.spyOn(Platform, "saveAiBrands").mockResolvedValue({ self: { domain: "books.toscrape.com", terms: ["BTS", "Books to Scrape"] }, competitors: [] });
    render(<AiVisibilityPage params={{ id: "7" }} />);
    await userEvent.type(await screen.findByLabelText(/new prompt/i), "rare first editions");
    await userEvent.click(screen.getByRole("button", { name: /add prompt/i }));
    expect(add).toHaveBeenCalledWith(7, "rare first editions");
    await userEvent.type(screen.getByLabelText(/^alias for books.toscrape.com/i), "Books to Scrape");
    await userEvent.click(screen.getByRole("button", { name: /add alias for books.toscrape.com/i }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(7, { self: ["BTS", "Books to Scrape"] }));
  });

  it("expands an answer with marked brands and only safe links", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText("2nd of 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show answer: best rare books \(claude\)/i }));
    const marks = document.querySelectorAll("mark");
    expect([...marks].map((m) => m.textContent)).toEqual(["Amazon", "Books to Scrape"]);
    const link = screen.getByRole("link", { name: "Books" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "evil" })).toBeNull();
  });

  it("charts have table views", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    const toggles = await screen.findAllByRole("button", { name: /show as table/i });
    await userEvent.click(toggles[1]);
    expect(screen.getByRole("cell", { name: "amazon.com" })).toBeInTheDocument();
  });
});
