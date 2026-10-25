# Phase 4: Dashboard Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Phases 1–3 a UI: a projects list, a project overview, Site Audit history with diffs, Rank Tracker, Content Gap, and a Keywords Explorer, each with explicit loading, empty and error states, at desktop and phone widths.

**Architecture:** Next.js 14 app-router pages under `app/projects/[id]/…` and `app/keywords`, sharing a global nav (in the root layout) and a frosted project sub-nav (in the project layout). Data comes from a typed `services/platform.ts` (throwing `ApiError`) through a small `useApi` hook. `AsyncState` turns each request into skeleton, empty, error or content. Chart data comes from pure transforms in `lib/platform-charts.ts`, which is what the tests check, since Recharts doesn't render in jsdom. Real rendering is checked in a browser.

**Tech Stack:** Next.js 14, React 18, Tailwind 3, shadcn-style `components/ui`, Recharts 3, lucide-react, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-25-dashboard-platform-design.md`

## Global Constraints

- Branch `feat/dashboard-platform`. Baseline: frontend 57 tests passing, `tsc` clean. Backend 472 + 1 skipped (untouched, except for no changes at all).
- **Design rules** (`DESIGN.md` plus the adaptations from Task 1):
  - Cards are `rounded-[18px] border bg-card` with **no shadow**.
  - Primary actions use the `Button` default variant with `rounded-full active:scale-95`.
  - Headlines are `font-semibold tracking-tight`. Body is `text-sm`, tables `text-[13px]`.
  - Severity uses only the `getSeverityBadge` classes (rose / amber / slate).
- **Chart colors** (validated with the dataviz validator against the app's card surfaces, white and `#050b1c`). Categorical slots, in fixed order, never cycled:
  - Light: `#2a78d6, #eb6834, #1baf7a, #eda100, #e87ba4, #008300`
  - Dark: `#3987e5, #d95926, #199e70, #c98500, #d55181, #008300`

  Slot 1 is always the project's own domain, and competitors take slots 2–6 in their listed order. In light mode, slots 3–5 are below 3:1 against white, so the rank chart **must** have a legend, end labels and a table view. The health trend is a single series (slot 1) with no legend.
- **Costly actions** (content gap, clustering, rank preview) run **only on click**.
- Every page has loading, empty and error states.
- Tests: `cd apps/frontend && npx vitest run && npx tsc --noEmit`. After any change to `packages/shared`, run `cd packages/shared && npm run build` first.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Design adaptations, types, API client, `useApi`

**Files:**
- Modify: `apps/frontend/DESIGN.md` (append the adaptations section; the file is committed in this task)
- Create: `packages/shared/src/types/platform.ts`; modify `packages/shared/src/types/index.ts` (re-export, plus `audit_id`/`project_id` on `AuditResponse`)
- Create: `apps/frontend/services/platform.ts`, `apps/frontend/lib/use-api.ts`
- Test: `apps/frontend/lib/__tests__/platform-service.test.ts`, `apps/frontend/lib/__tests__/use-api.test.tsx`

**Interfaces (produced):**
- Shared types: `ProjectSummary`, `AlertSettings`, `AuditListItem`, `PageList<T>`, `DiffIssue`, `AuditDiff`, `RankCheckView`, `TrackedKeyword`, `CompetitorDomain`, `RankPreview`, `ExploreKeyword`, `ExploreResult`, `GapRow`, `GapResult`
- `services/platform.ts`: `ApiError(status, detail)` and the `Platform` object whose methods appear in Step 4. `status === 0` means unreachable.
- `lib/use-api.ts`: `useApi<T>(fetcher | null, deps) -> {data, error, isLoading, reload}`

- [ ] **Step 1: Append to `apps/frontend/DESIGN.md`**

```markdown

---

## SEO dashboard adaptations (this project)

This file describes Apple's marketing site. The SEO Auditor is a data
dashboard, so it follows the guide selectively. Where this section and the
guide disagree, **this section wins**.

**Adopted**
- One blue accent (`--primary`) for every interactive element and link.
- Cards: `bg-card`, 1px hairline `border`, **no shadow**, `rounded-[18px]`.
- Primary actions are pills (`rounded-full`) with the `active:scale-95` press.
  Search inputs are pills.
- Headlines: weight 600, `tracking-tight`. No weight 500 for headings.
- The frosted sticky sub-nav (`bg-background/80 backdrop-blur`) for project tabs.

**Overridden**
- **Severity colors exist** (the guide allows one accent): critical = rose,
  warning = amber, info = slate. They are used only for severity, always with
  a text label, and the classes are `getSeverityBadge` in `lib/utils.ts`.
- **Chart colors exist:** categorical slots in fixed order, validated for
  colour-vision deficiency and contrast against the card surfaces. Light
  `#2a78d6 #eb6834 #1baf7a #eda100 #e87ba4 #008300`, dark `#3987e5 #d95926
  #199e70 #c98500 #d55181 #008300`. Slot 1 is always "my site". Charts with
  2+ series carry a legend, direct labels and a table view.
- **Density:** body 14px (`text-sm`), tables 13px, card padding 20–24px,
  section gaps 24–32px. Not 17px body or 80px sections.
- **States the guide doesn't cover:** every data view has loading (skeleton),
  empty (message + one primary action) and error (message + Retry) states.
- **Dark mode:** the `.dark` tokens in `globals.css`.
- **Not used:** full-bleed alternating product tiles, photography rules, the
  product drop-shadow.
```

- [ ] **Step 2: Shared types**

Create `packages/shared/src/types/platform.ts`:

```ts
// Central-database and keyword-research API shapes (backend Phases 1-3).

export interface AlertSettings {
  drop_threshold?: number;
  top10_alerts?: boolean;
  gain_threshold?: number | null;
}

export interface ProjectSummary {
  id: number;
  name: string;
  domain: string;
  audit_schedule: "daily" | "weekly" | null;
  audit_options: Record<string, unknown>;
  rank_schedule: "daily" | null;
  alert_settings: AlertSettings;
  audit_count: number;
  latest_audit: { id: number; finished_at: string; health_score: number | null } | null;
}

export interface PageList<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface AuditListItem {
  id: number;
  session_id: string;
  status: "completed" | "partial" | "failed";
  trigger: "manual" | "scheduled" | "import";
  start_url: string;
  started_at: string;
  finished_at: string;
  page_count: number;
  health_score: number | null;
}

export interface DiffIssue {
  url: string;
  code: string;
  severity: string;
  message: string;
}

export interface AuditDiff {
  old_audit_id: number;
  new_audit_id: number;
  health_score_change: number | null;
  issues: { new: DiffIssue[]; fixed: DiffIssue[]; new_count: number; fixed_count: number; persisting_count: number };
  pages: {
    added: string[];
    removed: string[];
    status_changed: { url: string; old_status: number | null; new_status: number | null }[];
    added_count: number;
    removed_count: number;
    status_changed_count: number;
  };
}

export interface RankCheckView {
  position: number | null;
  ranking_url: string | null;
  status: "ranked" | "not_ranked" | "skipped";
  checked_at: string;
  note: string | null;
  competitor_positions: Record<string, number | null>;
}

export interface TrackedKeyword {
  id: number;
  phrase: string;
  country: string;
  device: "desktop" | "mobile";
  language: string;
  enabled: boolean;
  latest: RankCheckView | null;
  /** previous position minus latest: positive = improved */
  change: number | null;
}

export interface CompetitorDomain {
  id: number;
  domain: string;
}

export interface RankPreview {
  dry_run: true;
  results: {
    phrase: string;
    position: number | null;
    ranking_url: string | null;
    competitor_positions: Record<string, number | null>;
  }[];
}

export interface ExploreKeyword {
  keyword: string;
  source: "seed" | "autocomplete" | "people_also_ask";
  search_volume: number | null;
  cpc: number | null;
  competition: string | null;
  difficulty: number | null;
  traffic_potential_estimate: number | null;
}

export interface ExploreResult {
  seed: string;
  country: string;
  language: string;
  dry_run: boolean;
  keywords: ExploreKeyword[];
  clusters: string[][];
  notes: string[];
}

export interface GapRow {
  keyword: string;
  search_volume: number | null;
  difficulty: number | null;
  opportunity: number;
  best_competitor_position: number;
  competitors: Record<string, { position: number; url: string }>;
}

export interface GapResult {
  my_domain: string;
  competitors: string[];
  dry_run: boolean;
  rows: GapRow[];
  total_gaps: number;
}
```

In `packages/shared/src/types/index.ts`:
- Append `export * from "./platform";`.
- In `AuditResponse`, after `reuse?: ReuseSummary;`, add:

```ts
  audit_id?: number | null;
  project_id?: number | null;
  persisted?: boolean;
```

- [ ] **Step 3: Write the failing tests**

`apps/frontend/lib/__tests__/platform-service.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, Platform } from "@/services/platform";

function respond(status: number, body: unknown) {
  return vi.spyOn(global, "fetch").mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), { status }),
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Platform API client", () => {
  it("returns parsed JSON on success", async () => {
    respond(200, { items: [{ id: 1 }] });
    expect(await Platform.listProjects()).toEqual({ items: [{ id: 1 }] });
  });

  it("throws ApiError with FastAPI's detail", async () => {
    respond(429, { detail: "daily cap of 20 dataforseo_labs calls reached" });
    await expect(Platform.contentGap(1, {})).rejects.toMatchObject({
      status: 429, detail: "daily cap of 20 dataforseo_labs calls reached",
    });
  });

  it("reports an unreachable server as status 0", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await Platform.listProjects().catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
  });

  it("handles 204 with no body", async () => {
    respond(204, undefined);
    await expect(Platform.deleteKeyword(3)).resolves.toBeUndefined();
  });

  it("sends JSON bodies and builds CSV links with repeated competitors", async () => {
    const fetchSpy = respond(200, { created: 1, skipped: 0 });
    await Platform.addKeywords(7, [{ phrase: "espresso", country: "GB", device: "mobile" }]);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/projects\/7\/keywords$/);
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      keywords: [{ phrase: "espresso", country: "GB", device: "mobile" }],
    });
    expect(Platform.contentGapCsvUrl(7, ["a.com", "b.org"])).toMatch(
      /\/api\/projects\/7\/content-gap\.csv\?country=US&language=en&limit=500&competitor=a\.com&competitor=b\.org$/,
    );
  });
});
```

`apps/frontend/lib/__tests__/use-api.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import { useApi } from "@/lib/use-api";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

describe("useApi", () => {
  it("goes loading -> data", async () => {
    const { result } = renderHook(() => useApi(() => Promise.resolve(42), []));
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.data).toBe(42));
    expect(result.current.isLoading).toBe(false);
  });

  it("captures errors and retries on reload", async () => {
    let calls = 0;
    const fetcher = () => (++calls === 1 ? Promise.reject(new Error("down")) : Promise.resolve("ok"));
    const { result } = renderHook(() => useApi(fetcher, []));
    await waitFor(() => expect(result.current.error?.message).toBe("down"));
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe("ok"));
    expect(result.current.error).toBeNull();
  });

  it("ignores a stale response when deps change", async () => {
    const slow = deferred<string>();
    const { result, rerender } = renderHook(
      ({ id }) => useApi(() => (id === 1 ? slow.promise : Promise.resolve("second")), [id]),
      { initialProps: { id: 1 } },
    );
    rerender({ id: 2 });
    await waitFor(() => expect(result.current.data).toBe("second"));
    await act(async () => slow.resolve("first"));
    expect(result.current.data).toBe("second");
  });

  it("does nothing when the fetcher is null", () => {
    const { result } = renderHook(() => useApi(null, []));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeNull();
  });
});
```

- [ ] **Step 4: Run to verify they fail, then implement**

Run: `cd packages/shared && npm run build && cd ../../apps/frontend && npx vitest run lib/__tests__/platform-service.test.ts lib/__tests__/use-api.test.tsx`
Expected: FAIL (the modules don't exist).

Create `apps/frontend/services/platform.ts`:

```ts
import type {
  AuditDiff, AuditListItem, CompetitorDomain, ExploreResult, GapResult, PageList,
  ProjectSummary, RankCheckView, RankPreview, TrackedKeyword, AlertSettings,
} from "@seo-auditor/shared";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || process.env.VITE_API_URL || "http://127.0.0.1:5000";

/** A failed API call. status 0 = the server could not be reached. */
export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  if (res.status === 204) return undefined as T;
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    throw new ApiError(res.status, typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return body as T;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});
const patch = (body: unknown): RequestInit => ({ method: "PATCH", body: JSON.stringify(body) });

export interface NewKeyword { phrase: string; country?: string; device?: "desktop" | "mobile" }

export const Platform = {
  listProjects: () => request<{ items: ProjectSummary[] }>("/projects"),
  updateProject: (id: number, body: Partial<{ name: string; rank_schedule: "daily" | null; alert_settings: AlertSettings }>) =>
    request<ProjectSummary>(`/projects/${id}`, patch(body)),
  listAudits: (id: number, limit = 50, offset = 0) =>
    request<PageList<AuditListItem>>(`/projects/${id}/audits?limit=${limit}&offset=${offset}`),
  auditDiff: (auditId: number, against?: number) =>
    request<AuditDiff>(`/audits/${auditId}/diff${against != null ? `?against=${against}` : ""}`),

  listKeywords: (id: number) => request<{ items: TrackedKeyword[] }>(`/projects/${id}/keywords`),
  addKeywords: (id: number, keywords: NewKeyword[]) =>
    request<{ created: number; skipped: number }>(`/projects/${id}/keywords`, post({ keywords })),
  setKeywordEnabled: (keywordId: number, enabled: boolean) =>
    request<{ id: number; enabled: boolean }>(`/keywords/${keywordId}`, patch({ enabled })),
  deleteKeyword: (keywordId: number) => request<void>(`/keywords/${keywordId}`, { method: "DELETE" }),
  keywordHistory: (keywordId: number, days = 90) =>
    request<{ items: RankCheckView[] }>(`/keywords/${keywordId}/history?days=${days}`),
  listCompetitors: (id: number) => request<{ items: CompetitorDomain[] }>(`/projects/${id}/competitors`),
  addCompetitor: (id: number, domain: string) =>
    request<CompetitorDomain>(`/projects/${id}/competitors`, post({ domain })),
  deleteCompetitor: (id: number, competitorId: number) =>
    request<void>(`/projects/${id}/competitors/${competitorId}`, { method: "DELETE" }),
  previewRankCheck: (id: number) => request<RankPreview>(`/projects/${id}/rank-checks/run`, post()),

  explore: (body: { seed: string; country?: string; language?: string; cluster?: boolean }) =>
    request<ExploreResult>("/keywords/explore", post(body)),
  exploreCsvUrl: (seed: string, country = "US", language = "en") =>
    `${API_BASE_URL}/api/keywords/explore.csv?${new URLSearchParams({ seed, country, language })}`,
  contentGap: (id: number, body: { competitors?: string[]; country?: string; language?: string; limit?: number }) =>
    request<GapResult>(`/projects/${id}/content-gap`, post(body)),
  contentGapCsvUrl: (id: number, competitors: string[], country = "US", language = "en", limit = 500) => {
    const params = new URLSearchParams({ country, language, limit: String(limit) });
    competitors.forEach((c) => params.append("competitor", c));
    return `${API_BASE_URL}/api/projects/${id}/content-gap.csv?${params}`;
  },
};
```

Create `apps/frontend/lib/use-api.ts`:

```ts
"use client";

import { DependencyList, useCallback, useEffect, useRef, useState } from "react";

export interface UseApiResult<T> {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  reload: () => void;
}

/** Fetch on mount and whenever `deps` change. A response that arrives after a
 *  newer request started is dropped, so fast tab or filter changes never show
 *  stale data. A null fetcher means "don't fetch yet". */
export function useApi<T>(fetcher: (() => Promise<T>) | null, deps: DependencyList): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setLoading] = useState(fetcher !== null);
  const [nonce, setNonce] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    if (!fetcher) {
      setLoading(false);
      return;
    }
    const id = ++latest.current;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (id === latest.current) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (id === latest.current) {
          setError(e instanceof Error ? e : new Error(String(e)));
          setLoading(false);
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, isLoading, reload };
}
```

- [ ] **Step 5: Verify and commit**

Run: `cd packages/shared && npm run build && cd ../../apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, tsc clean.

```bash
git add apps/frontend/DESIGN.md packages/shared/src/types/platform.ts packages/shared/src/types/index.ts apps/frontend/services/platform.ts apps/frontend/lib/use-api.ts apps/frontend/lib/__tests__/platform-service.test.ts apps/frontend/lib/__tests__/use-api.test.tsx
git commit -m "feat: platform API client, useApi hook, shared types; DESIGN.md adaptations"
```

---

### Task 2: Shared UI pieces and chart data transforms

**Files:**
- Create: `apps/frontend/components/platform/async-state.tsx`, `delta-badge.tsx`, `dry-run-banner.tsx`, `kpi-tile.tsx`, `page-header.tsx`
- Create: `apps/frontend/lib/platform-charts.ts`
- Test: `apps/frontend/components/__tests__/platform-pieces.test.tsx`, `apps/frontend/lib/__tests__/platform-charts.test.ts`

**Interfaces (produced):**
- `AsyncState<T>({state, isEmpty?, emptyTitle?, emptyText?, emptyAction?, children: (data: T) => ReactNode})` and `EmptyState({title, text?, action?})`
- `DeltaBadge({value, lowerIsBetter?, suffix?})`, where `value` = new − old
- `DryRunBanner({show})`, `KpiTile({label, value, delta?, hint?})`, `PageHeader({title, description?, actions?})`
- `platform-charts`:
  - `SERIES_LIGHT`, `SERIES_DARK: string[]`
  - `healthTrend(audits: AuditListItem[]) -> {label: string; score: number | null}[]` (oldest first)
  - `rankSeries(history: RankCheckView[], competitors: string[]) -> {points: Array<{label: string; me: number | null; [domain]: number | null}>; maxPosition: number}`
  - `averagePosition(keywords) -> number | null`
  - `biggestMoves(keywords, n) -> TrackedKeyword[]`

- [ ] **Step 1: Write the failing tests**

`apps/frontend/lib/__tests__/platform-charts.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { averagePosition, biggestMoves, healthTrend, rankSeries } from "@/lib/platform-charts";

const audit = (id: number, finished: string, score: number | null) => ({
  id, session_id: `s${id}`, status: "completed" as const, trigger: "manual" as const,
  start_url: "https://example.com/", started_at: finished, finished_at: finished, page_count: 10, health_score: score,
});

describe("healthTrend", () => {
  it("orders oldest first and keeps missing scores as null", () => {
    const points = healthTrend([audit(2, "2026-10-20T10:00:00+00:00", 70), audit(1, "2026-10-10T10:00:00+00:00", null)]);
    expect(points.map((p) => p.score)).toEqual([null, 70]);
  });
});

describe("rankSeries", () => {
  const check = (day: string, position: number | null, status = position ? "ranked" : "not_ranked",
                 competitors: Record<string, number | null> = {}) => ({
    position, ranking_url: null, status: status as any, checked_at: `2026-10-${day}T09:00:00+00:00`,
    note: null, competitor_positions: competitors,
  });

  it("maps my position and each competitor per check", () => {
    const { points } = rankSeries([check("20", 4, "ranked", { "rival.org": 2 }), check("21", 9, "ranked", { "rival.org": null })], ["rival.org"]);
    expect(points).toEqual([
      expect.objectContaining({ me: 4, "rival.org": 2 }),
      expect.objectContaining({ me: 9, "rival.org": null }),
    ]);
  });

  it("turns skipped checks into gaps, not zeros", () => {
    const { points } = rankSeries([check("20", 4), check("21", null, "skipped"), check("22", 6)], []);
    expect(points.map((p) => p.me)).toEqual([4, null, 6]);
  });

  it("reports the worst position seen for the reversed axis domain", () => {
    expect(rankSeries([check("20", 4, "ranked", { a: 30 })], ["a"]).maxPosition).toBe(30);
    expect(rankSeries([], []).maxPosition).toBe(10);
  });
});

describe("keyword summaries", () => {
  const kw = (id: number, position: number | null, change: number | null) => ({
    id, phrase: `k${id}`, country: "US", device: "desktop" as const, language: "en", enabled: true, change,
    latest: position === null ? null : { position, ranking_url: null, status: "ranked" as const,
                                         checked_at: "", note: null, competitor_positions: {} },
  });

  it("averages ranked positions only", () => {
    expect(averagePosition([kw(1, 4, null), kw(2, 10, null), kw(3, null, null)])).toBe(7);
    expect(averagePosition([kw(1, null, null)])).toBeNull();
  });

  it("biggest moves are by absolute change", () => {
    expect(biggestMoves([kw(1, 4, 1), kw(2, 9, -5), kw(3, 3, 3), kw(4, 5, null)], 2).map((k) => k.id)).toEqual([2, 3]);
  });
});
```

`apps/frontend/components/__tests__/platform-pieces.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AsyncState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { ApiError } from "@/services/platform";

const state = (over: Partial<{ data: any; error: Error | null; isLoading: boolean }>) => ({
  data: null, error: null, isLoading: false, reload: vi.fn(), ...over,
});

describe("AsyncState", () => {
  it("shows a skeleton while loading", () => {
    render(<AsyncState state={state({ isLoading: true })}>{() => "content"}</AsyncState>);
    expect(screen.getByTestId("async-loading")).toBeInTheDocument();
  });

  it("explains a 503 and retries", async () => {
    const s = state({ error: new ApiError(503, "central database unavailable") });
    render(<AsyncState state={s}>{() => "content"}</AsyncState>);
    expect(screen.getByRole("alert")).toHaveTextContent(/unavailable right now/i);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(s.reload).toHaveBeenCalled();
  });

  it("shows the empty state with its action", () => {
    render(
      <AsyncState state={state({ data: [] })} isEmpty={(d: any[]) => d.length === 0}
                  emptyTitle="No projects yet" emptyAction={<a href="/">Run an audit</a>}>
        {() => "content"}
      </AsyncState>,
    );
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run an audit" })).toBeInTheDocument();
  });

  it("renders children with data", () => {
    render(<AsyncState state={state({ data: { n: 3 } })}>{(d: any) => `n=${d.n}`}</AsyncState>);
    expect(screen.getByText("n=3")).toBeInTheDocument();
  });
});

describe("DeltaBadge", () => {
  it("higher is better by default", () => {
    render(<DeltaBadge value={3} />);
    expect(screen.getByLabelText("improved by 3")).toHaveTextContent("▲3");
  });

  it("for ranks a lower number is an improvement", () => {
    render(<DeltaBadge value={-5} lowerIsBetter />);
    expect(screen.getByLabelText("improved by 5")).toHaveTextContent("▲5");
  });

  it("a worse rank points down", () => {
    render(<DeltaBadge value={5} lowerIsBetter />);
    expect(screen.getByLabelText("worse by 5")).toHaveTextContent("▼5");
  });

  it("renders nothing for no change or no data", () => {
    const { container } = render(<><DeltaBadge value={0} /><DeltaBadge value={null} /></>);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DryRunBanner", () => {
  it("is visible only for dry-run data", () => {
    const { rerender } = render(<DryRunBanner show />);
    expect(screen.getByRole("note")).toHaveTextContent(/made up/i);
    rerender(<DryRunBanner show={false} />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/frontend && npx vitest run lib/__tests__/platform-charts.test.ts components/__tests__/platform-pieces.test.tsx`
Expected: FAIL (the modules don't exist).

- [ ] **Step 3: Implement**

`apps/frontend/lib/platform-charts.ts`:

```ts
import type { AuditListItem, RankCheckView, TrackedKeyword } from "@seo-auditor/shared";

// Categorical slots in fixed order, validated (dataviz validate_palette.js)
// against the card surfaces: white (light) and #050b1c (dark). Slot 1 is
// always the project's own site; competitors follow in listed order.
export const SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
export const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"];

const dayLabel = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export function healthTrend(audits: AuditListItem[]) {
  return [...audits]
    .sort((a, b) => a.finished_at.localeCompare(b.finished_at) || a.id - b.id)
    .map((a) => ({ label: dayLabel(a.finished_at), score: a.health_score }));
}

export type RankPoint = { label: string; me: number | null } & Record<string, number | null | string>;

export function rankSeries(history: RankCheckView[], competitors: string[]) {
  let maxPosition = 10;
  const points: RankPoint[] = history.map((check) => {
    // A skipped check measured nothing: a gap in the line, never a zero.
    const me = check.status === "skipped" ? null : check.position;
    const point: RankPoint = { label: dayLabel(check.checked_at), me };
    if (me != null) maxPosition = Math.max(maxPosition, me);
    for (const domain of competitors) {
      const value = check.status === "skipped" ? null : check.competitor_positions?.[domain] ?? null;
      point[domain] = value;
      if (value != null) maxPosition = Math.max(maxPosition, value);
    }
    return point;
  });
  return { points, maxPosition };
}

export function averagePosition(keywords: TrackedKeyword[]): number | null {
  const ranked = keywords.map((k) => k.latest?.position).filter((p): p is number => p != null);
  if (!ranked.length) return null;
  return Math.round((ranked.reduce((a, b) => a + b, 0) / ranked.length) * 10) / 10;
}

export function biggestMoves(keywords: TrackedKeyword[], n: number): TrackedKeyword[] {
  return keywords
    .filter((k) => k.change != null && k.change !== 0)
    .sort((a, b) => Math.abs(b.change!) - Math.abs(a.change!))
    .slice(0, n);
}
```

`apps/frontend/components/platform/async-state.tsx`:

```tsx
"use client";

import React from "react";
import { AlertTriangle, Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { UseApiResult } from "@/lib/use-api";
import { ApiError } from "@/services/platform";

function errorTitle(error: Error): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Can't reach the server";
    if (error.status === 503) return "Project data is unavailable right now";
    if (error.status === 404) return "Not found";
  }
  return "Something went wrong";
}

export function EmptyState({ title, text, action }: { title: string; text?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[18px] border border-dashed bg-card px-6 py-12 text-center">
      <Inbox className="h-6 w-6 text-muted-foreground" aria-hidden />
      <p className="font-semibold tracking-tight">{title}</p>
      {text && <p className="max-w-md text-sm text-muted-foreground">{text}</p>}
      {action}
    </div>
  );
}

interface AsyncStateProps<T> {
  state: UseApiResult<T>;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyText?: string;
  emptyAction?: React.ReactNode;
  children: (data: T) => React.ReactNode;
}

export function AsyncState<T>({ state, isEmpty, emptyTitle = "Nothing here yet", emptyText, emptyAction, children }: AsyncStateProps<T>) {
  if (state.isLoading && state.data === null) {
    return (
      <div data-testid="async-loading" aria-busy="true" className="space-y-3">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-28 w-full rounded-[18px]" />
      </div>
    );
  }
  if (state.error) {
    return (
      <div role="alert" className="flex flex-col items-start gap-3 rounded-[18px] border border-rose-200 bg-rose-50/60 p-6 dark:border-rose-900 dark:bg-rose-950/30">
        <div className="flex items-center gap-2 font-semibold tracking-tight text-rose-700 dark:text-rose-400">
          <AlertTriangle className="h-4 w-4" aria-hidden /> {errorTitle(state.error)}
        </div>
        <p className="text-sm text-muted-foreground">{state.error.message}</p>
        <Button variant="outline" size="sm" className="rounded-full active:scale-95" onClick={state.reload}>Retry</Button>
      </div>
    );
  }
  if (state.data === null) return null;
  if (isEmpty?.(state.data)) return <EmptyState title={emptyTitle} text={emptyText} action={emptyAction} />;
  return <>{children(state.data)}</>;
}
```

`apps/frontend/components/platform/delta-badge.tsx`:

```tsx
import { cn } from "@/lib/utils";

/** `value` is new minus old. For ranks a lower number is better, so pass
 *  `lowerIsBetter` and a drop from 9 to 4 (value -5) shows as an improvement. */
export function DeltaBadge({ value, lowerIsBetter = false, suffix = "" }: {
  value: number | null | undefined; lowerIsBetter?: boolean; suffix?: string;
}) {
  if (value == null || value === 0) return null;
  const improved = lowerIsBetter ? value < 0 : value > 0;
  const size = Math.round(Math.abs(value) * 10) / 10;
  return (
    <span
      aria-label={`${improved ? "improved" : "worse"} by ${size}${suffix}`}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
        improved ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" : "bg-rose-500/10 text-rose-700 dark:text-rose-400",
      )}
    >
      {improved ? "▲" : "▼"}{size}{suffix}
    </span>
  );
}
```

`apps/frontend/components/platform/dry-run-banner.tsx`:

```tsx
import { FlaskConical } from "lucide-react";

export function DryRunBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div role="note" className="flex items-center gap-2 rounded-[18px] border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
      <FlaskConical className="h-4 w-4 shrink-0" aria-hidden />
      Preview data. DataForSEO is not live, so these numbers are made up.
    </div>
  );
}
```

`apps/frontend/components/platform/kpi-tile.tsx`:

```tsx
import React from "react";

export function KpiTile({ label, value, delta, hint }: {
  label: string; value: React.ReactNode; delta?: React.ReactNode; hint?: string;
}) {
  return (
    <div className="rounded-[18px] border bg-card p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-3xl font-semibold tracking-tight tabular-nums">{value}</span>
        {delta}
      </div>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
```

`apps/frontend/components/platform/page-header.tsx`:

```tsx
import React from "react";

export function PageHeader({ title, description, actions }: {
  title: string; description?: string; actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

```bash
git add apps/frontend/components/platform apps/frontend/lib/platform-charts.ts apps/frontend/lib/__tests__/platform-charts.test.ts apps/frontend/components/__tests__/platform-pieces.test.tsx
git commit -m "feat: async states, delta badge, dry-run banner, KPI tile; chart data transforms"
```

---

### Task 3: Navigation, project shell, projects list

**Files:**
- Create: `apps/frontend/components/platform/global-nav.tsx`, `project-tabs.tsx`, `project-switcher.tsx`
- Create: `apps/frontend/app/projects/page.tsx`, `apps/frontend/app/projects/[id]/layout.tsx`
- Modify: `apps/frontend/app/layout.tsx` (render `GlobalNav`)
- Test: `apps/frontend/components/__tests__/projects-page.test.tsx`

**Interfaces (produced):**
- `GlobalNav()`
- `ProjectTabs({projectId})`: links `/projects/{id}`, `/audits`, `/ranks`, `/gap`, with the active one by pathname
- `ProjectSwitcher({projectId})`: a `<select>` that keeps the current tab when switching
- The page `app/projects/page.tsx` default export
- `app/projects/[id]/layout.tsx` (params `{id: string}`)

- [ ] **Step 1: Write the failing tests**

`apps/frontend/components/__tests__/projects-page.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import ProjectsPage from "@/app/projects/page";
import { ProjectTabs } from "@/components/platform/project-tabs";
import { ApiError, Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/projects/7/ranks",
}));

const project = (over = {}) => ({
  id: 7, name: "example.com", domain: "example.com", audit_schedule: null, audit_options: {},
  rank_schedule: "daily" as const, alert_settings: {}, audit_count: 3,
  latest_audit: { id: 30, finished_at: "2026-10-24T10:00:00+00:00", health_score: 72.5 }, ...over,
});

beforeEach(() => vi.restoreAllMocks());

describe("Projects page", () => {
  it("lists projects with health and audit count", async () => {
    vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [project()] });
    render(<ProjectsPage />);
    const card = await screen.findByRole("link", { name: /example\.com/i });
    expect(card).toHaveAttribute("href", "/projects/7");
    expect(within(card).getByText("72.5")).toBeInTheDocument();
    expect(within(card).getByText(/3 audits/i)).toBeInTheDocument();
  });

  it("invites a first audit when there are none", async () => {
    vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [] });
    render(<ProjectsPage />);
    expect(await screen.findByText(/no projects yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /run your first audit/i })).toHaveAttribute("href", "/");
  });

  it("explains an outage", async () => {
    vi.spyOn(Platform, "listProjects").mockRejectedValue(new ApiError(503, "central database unavailable"));
    render(<ProjectsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable right now/i);
  });
});

describe("ProjectTabs", () => {
  it("marks the tab for the current path", () => {
    render(<ProjectTabs projectId={7} />);
    expect(screen.getByRole("link", { name: "Rank Tracker" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Content Gap" })).toHaveAttribute("href", "/projects/7/gap");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx vitest run components/__tests__/projects-page.test.tsx`
Expected: FAIL (the modules don't exist).

- [ ] **Step 3: Implement**

`components/platform/global-nav.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, Plus, Search } from "lucide-react";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/projects", label: "Projects" },
  { href: "/keywords", label: "Keywords Explorer" },
];

export function GlobalNav() {
  const pathname = usePathname() || "/";
  const [open, setOpen] = useState(false);
  const linkClass = (href: string) =>
    cn("rounded-full px-3 py-1.5 text-sm transition-colors hover:text-foreground",
       pathname.startsWith(href) ? "text-foreground font-medium" : "text-muted-foreground");

  return (
    <header className="sticky top-0 z-40 h-[52px] border-b bg-background/95 backdrop-blur">
      <nav className="mx-auto flex h-full max-w-7xl items-center gap-2 px-4 sm:px-6" aria-label="Main">
        <Link href="/projects" className="mr-2 flex items-center gap-2 font-semibold tracking-tight">
          <Search className="h-4 w-4 text-primary" aria-hidden /> SEO Auditor
        </Link>
        <div className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={linkClass(l.href)}
                  aria-current={pathname.startsWith(l.href) ? "page" : undefined}>{l.label}</Link>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/" className="inline-flex h-9 items-center gap-1.5 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground active:scale-95">
            <Plus className="h-4 w-4" aria-hidden /> New audit
          </Link>
          <button type="button" className="inline-flex h-11 w-11 items-center justify-center rounded-full md:hidden"
                  aria-label="Menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <Menu className="h-5 w-5" />
          </button>
        </div>
      </nav>
      {open && (
        <div className="border-b bg-background px-4 py-2 md:hidden">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)}
                  className="block rounded-lg px-3 py-3 text-sm">{l.label}</Link>
          ))}
        </div>
      )}
    </header>
  );
}
```

`components/platform/project-tabs.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

export const TABS = [
  { suffix: "", label: "Overview" },
  { suffix: "/audits", label: "Site Audit" },
  { suffix: "/ranks", label: "Rank Tracker" },
  { suffix: "/gap", label: "Content Gap" },
];

export function activeSuffix(pathname: string, projectId: number): string {
  const rest = pathname.replace(`/projects/${projectId}`, "");
  return TABS.slice(1).find((t) => rest.startsWith(t.suffix))?.suffix ?? "";
}

export function ProjectTabs({ projectId }: { projectId: number }) {
  const current = activeSuffix(usePathname() || "", projectId);
  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto" role="navigation" aria-label="Project">
      {TABS.map((t) => {
        const active = t.suffix === current;
        return (
          <Link key={t.label} href={`/projects/${projectId}${t.suffix}`} aria-current={active ? "page" : undefined}
                className={cn("whitespace-nowrap rounded-full px-3 py-1.5 text-sm transition-colors",
                              active ? "bg-foreground text-background font-medium" : "text-muted-foreground hover:text-foreground")}>
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}
```

`components/platform/project-switcher.tsx`:

```tsx
"use client";

import { usePathname, useRouter } from "next/navigation";

import { activeSuffix } from "@/components/platform/project-tabs";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export function ProjectSwitcher({ projectId }: { projectId: number }) {
  const router = useRouter();
  const pathname = usePathname() || "";
  const projects = useApi(() => Platform.listProjects(), []);
  const items = projects.data?.items ?? [];
  const current = items.find((p) => p.id === projectId);

  return (
    <label className="flex min-w-0 items-center gap-2">
      <span className="sr-only">Project</span>
      <select
        className="h-9 max-w-[16rem] truncate rounded-full border bg-card px-3 text-sm font-semibold tracking-tight"
        value={projectId}
        onChange={(e) => router.push(`/projects/${e.target.value}${activeSuffix(pathname, projectId)}`)}
      >
        {!current && <option value={projectId}>Project #{projectId}</option>}
        {items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>
  );
}
```

`app/projects/[id]/layout.tsx`:

```tsx
import React from "react";

import { ProjectSwitcher } from "@/components/platform/project-switcher";
import { ProjectTabs } from "@/components/platform/project-tabs";

export default function ProjectLayout({ children, params }: { children: React.ReactNode; params: { id: string } }) {
  const projectId = Number(params.id);
  return (
    <div className="min-h-screen bg-background">
      <div className="sticky top-[52px] z-30 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4 sm:px-6">
          <ProjectSwitcher projectId={projectId} />
          <ProjectTabs projectId={projectId} />
        </div>
      </div>
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </div>
  );
}
```

`app/projects/page.tsx`:

```tsx
"use client";

import Link from "next/link";

import { AsyncState } from "@/components/platform/async-state";
import { PageHeader } from "@/components/platform/page-header";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export default function ProjectsPage() {
  const projects = useApi(() => Platform.listProjects(), []);
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title="Projects" description="One project per site. Audits and rank checks are filed under their domain." />
      <AsyncState
        state={projects}
        isEmpty={(d) => d.items.length === 0}
        emptyTitle="No projects yet"
        emptyText="A project is created automatically the first time you audit a site."
        emptyAction={<Link href="/" className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">Run your first audit</Link>}
      >
        {(data) => (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((p) => (
              <Link key={p.id} href={`/projects/${p.id}`} aria-label={p.name}
                    className="group rounded-[18px] border bg-card p-5 transition-colors hover:border-primary/40">
                <p className="truncate font-semibold tracking-tight group-hover:text-primary">{p.name}</p>
                <p className="truncate text-xs text-muted-foreground">{p.domain}</p>
                <div className="mt-4 flex items-end justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">Health</p>
                    <p className="text-2xl font-semibold tabular-nums">{p.latest_audit?.health_score ?? "—"}</p>
                  </div>
                  <p className="text-right text-xs text-muted-foreground">
                    {p.audit_count} audits
                    {p.latest_audit && <><br />last {new Date(p.latest_audit.finished_at).toLocaleDateString()}</>}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        )}
      </AsyncState>
    </main>
  );
}
```

`app/layout.tsx`: import `GlobalNav` and render it before the provider's children:

```tsx
import { GlobalNav } from "@/components/platform/global-nav";
...
      <body>
        <AuditProvider>
          <GlobalNav />
          {children}
        </AuditProvider>
      </body>
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS. The existing page tests render pages without the layout, so they're unaffected.

```bash
git add apps/frontend/components/platform/global-nav.tsx apps/frontend/components/platform/project-tabs.tsx apps/frontend/components/platform/project-switcher.tsx apps/frontend/app/projects apps/frontend/app/layout.tsx apps/frontend/components/__tests__/projects-page.test.tsx
git commit -m "feat: global nav, project shell with switcher and tabs, projects list"
```

---

### Task 4: Project overview

**Files:**
- Create: `apps/frontend/components/platform/health-trend-chart.tsx`, `apps/frontend/app/projects/[id]/page.tsx`
- Test: `apps/frontend/components/__tests__/project-overview.test.tsx`

**Interfaces (produced):** `HealthTrendChart({audits})`, and the page default export `({params: {id}})`.

- [ ] **Step 1: Write the failing tests**

`apps/frontend/components/__tests__/project-overview.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import OverviewPage from "@/app/projects/[id]/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7" }));

const audit = (id: number, score: number) => ({
  id, session_id: `s${id}`, status: "completed", trigger: "manual", start_url: "https://example.com/",
  started_at: `2026-10-2${id}T10:00:00+00:00`, finished_at: `2026-10-2${id}T10:00:00+00:00`, page_count: 40, health_score: score,
});
const kw = (id: number, position: number, change: number) => ({
  id, phrase: `keyword ${id}`, country: "US", device: "desktop", language: "en", enabled: true, change,
  latest: { position, ranking_url: null, status: "ranked", checked_at: "", note: null, competitor_positions: {} },
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [kw(1, 4, -5), kw(2, 10, 2)] } as any);
});

describe("Project overview", () => {
  it("shows KPIs with the health change and the diff", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(2, 75), audit(1, 72)], total: 2, offset: 0, limit: 50 } as any);
    const diff = vi.spyOn(Platform, "auditDiff").mockResolvedValue({
      old_audit_id: 1, new_audit_id: 2, health_score_change: 3,
      issues: { new: [], fixed: [], new_count: 4, fixed_count: 9, persisting_count: 20 },
      pages: { added: [], removed: [], status_changed: [], added_count: 0, removed_count: 0, status_changed_count: 0 },
    });
    render(<OverviewPage params={{ id: "7" }} />);

    expect(await screen.findByText("75")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 3")).toBeInTheDocument();
    expect(await screen.findByText(/4 new/i)).toBeInTheDocument();
    expect(screen.getByText(/9 fixed/i)).toBeInTheDocument();
    expect(diff).toHaveBeenCalledWith(2);
    expect(screen.getByText("7")).toBeInTheDocument();            // average position of 4 and 10
    expect(screen.getByText("keyword 1")).toBeInTheDocument();    // biggest move
  });

  it("does not ask for a diff with a single audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(1, 72)], total: 1, offset: 0, limit: 50 } as any);
    const diff = vi.spyOn(Platform, "auditDiff");
    render(<OverviewPage params={{ id: "7" }} />);
    expect(await screen.findByText(/run a second audit to compare/i)).toBeInTheDocument();
    expect(diff).not.toHaveBeenCalled();
  });

  it("invites a first audit for a project with none", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 } as any);
    render(<OverviewPage params={{ id: "7" }} />);
    expect(await screen.findByText(/no audits yet/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx vitest run components/__tests__/project-overview.test.tsx`
Expected: FAIL (the module doesn't exist).

- [ ] **Step 3: Implement**

`components/platform/health-trend-chart.tsx`:

```tsx
"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AuditListItem } from "@seo-auditor/shared";

import { healthTrend, SERIES_LIGHT } from "@/lib/platform-charts";

/** One series (the project's health score), so no legend: the card title names it. */
export function HealthTrendChart({ audits }: { audits: AuditListItem[] }) {
  const data = healthTrend(audits);
  return (
    <div className="h-60 w-full sm:h-80" role="img" aria-label="Health score over time">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
          <Line type="monotone" dataKey="score" name="Health" stroke={SERIES_LIGHT[0]} strokeWidth={2}
                dot={{ r: 4 }} activeDot={{ r: 5 }} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

`app/projects/[id]/page.tsx`:

```tsx
"use client";

import Link from "next/link";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { HealthTrendChart } from "@/components/platform/health-trend-chart";
import { KpiTile } from "@/components/platform/kpi-tile";
import { averagePosition, biggestMoves } from "@/lib/platform-charts";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export default function OverviewPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const audits = useApi(() => Platform.listAudits(projectId, 50), [projectId]);
  const keywords = useApi(() => Platform.listKeywords(projectId), [projectId]);
  const items = audits.data?.items ?? [];
  const [latest, previous] = items;
  const diff = useApi(latest && previous ? () => Platform.auditDiff(latest.id) : null, [latest?.id, previous?.id]);

  const kwItems = keywords.data?.items ?? [];
  const avg = averagePosition(kwItems);
  const moves = biggestMoves(kwItems, 5);
  const healthDelta = latest?.health_score != null && previous?.health_score != null
    ? Math.round((latest.health_score - previous.health_score) * 10) / 10 : null;

  return (
    <AsyncState
      state={audits}
      isEmpty={(d) => d.items.length === 0}
      emptyTitle="No audits yet"
      emptyText="Audit this site to see its health, history and issues here."
      emptyAction={<Link href="/" className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">Run an audit</Link>}
    >
      {() => (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiTile label="Health" value={latest.health_score ?? "—"} delta={<DeltaBadge value={healthDelta} />} />
            <KpiTile label="Tracked keywords" value={kwItems.length} hint={kwItems.length ? undefined : "Add some in Rank Tracker"} />
            <KpiTile label="Avg. position" value={avg ?? "—"} hint="across ranked keywords" />
            <KpiTile label="Pages in last audit" value={latest.page_count} />
          </div>

          <section className="rounded-[18px] border bg-card p-5">
            <h2 className="mb-4 font-semibold tracking-tight">Health over time</h2>
            <HealthTrendChart audits={items} />
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Latest audit vs previous</h2>
              {!previous ? (
                <EmptyState title="Run a second audit to compare" />
              ) : (
                <AsyncState state={diff}>
                  {(d) => (
                    <div className="space-y-3">
                      <div className="flex gap-6 text-sm">
                        <span className="font-semibold text-rose-700 dark:text-rose-400">{d.issues.new_count} new</span>
                        <span className="font-semibold text-emerald-700 dark:text-emerald-400">{d.issues.fixed_count} fixed</span>
                        <span className="text-muted-foreground">{d.issues.persisting_count} unchanged</span>
                      </div>
                      <Link href={`/projects/${projectId}/audits`} className="text-sm text-primary hover:underline">See the full comparison</Link>
                    </div>
                  )}
                </AsyncState>
              )}
            </section>

            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Biggest rank moves</h2>
              {moves.length === 0 ? (
                <p className="text-sm text-muted-foreground">No rank changes yet.</p>
              ) : (
                <ul className="divide-y text-sm">
                  {moves.map((k) => (
                    <li key={k.id} className="flex items-center justify-between py-2">
                      <span className="truncate">{k.phrase}</span>
                      <span className="flex items-center gap-2 tabular-nums">
                        {k.latest?.position ?? "—"} <DeltaBadge value={k.change != null ? -k.change : null} lowerIsBetter />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </AsyncState>
  );
}
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

```bash
git add apps/frontend/components/platform/health-trend-chart.tsx "apps/frontend/app/projects/[id]/page.tsx" apps/frontend/components/__tests__/project-overview.test.tsx
git commit -m "feat: project overview -- KPIs, health trend, latest diff, rank moves"
```

---

### Task 5: Site Audit history and diff; open old reports

**Files:**
- Create: `apps/frontend/components/platform/audit-diff.tsx`, `apps/frontend/app/projects/[id]/audits/page.tsx`, `apps/frontend/lib/session-param.ts`
- Modify: `apps/frontend/app/dashboard/page.tsx` (use the session param; "View project" link)
- Test: `apps/frontend/components/__tests__/site-audit-page.test.tsx`

**Interfaces (produced):**
- `AuditDiffView({diff})`
- `useSessionParam(activeSessionId, startNewAudit)`: on mount, if `?session=` is present and differs from the active session, it calls `startNewAudit(session)`
- The page default export

- [ ] **Step 1: Write the failing tests**

`apps/frontend/components/__tests__/site-audit-page.test.tsx`:

```tsx
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

beforeEach(() => vi.restoreAllMocks());

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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx vitest run components/__tests__/site-audit-page.test.tsx`
Expected: FAIL (the modules don't exist).

- [ ] **Step 3: Implement**

`lib/session-param.ts`:

```ts
"use client";

import { useEffect } from "react";

/** /dashboard?session=<id> opens that saved audit. Read from window.location
 *  rather than useSearchParams, which would force a Suspense boundary onto the
 *  whole dashboard page in a static build. */
export function useSessionParam(activeSessionId: string | null, startNewAudit: (id: string) => void) {
  useEffect(() => {
    const session = new URLSearchParams(window.location.search).get("session");
    if (session && session !== activeSessionId) startNewAudit(session);
    // Only on mount: later session changes come from the app itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
```

`components/platform/audit-diff.tsx`:

```tsx
import type { AuditDiff, DiffIssue } from "@seo-auditor/shared";

import { getSeverityBadge } from "@/lib/utils";

const ORDER = ["critical", "warning", "info"];

function IssueGroup({ title, issues, total }: { title: string; issues: DiffIssue[]; total: number }) {
  const sorted = [...issues].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity));
  return (
    <section className="rounded-[18px] border bg-card p-5">
      <h3 className="mb-3 font-semibold tracking-tight">{title} <span className="text-muted-foreground">({total})</span></h3>
      {sorted.length === 0 ? <p className="text-sm text-muted-foreground">None.</p> : (
        <ul className="divide-y text-[13px]">
          {sorted.map((i) => {
            const badge = getSeverityBadge(i.severity);
            return (
              <li key={`${i.url}|${i.code}`} className="flex flex-wrap items-center gap-2 py-2">
                <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${badge.className}`}>{badge.label}</span>
                <span className="font-medium">{i.code}</span>
                <span className="truncate text-muted-foreground">{i.url}</span>
              </li>
            );
          })}
        </ul>
      )}
      {total > sorted.length && <p className="mt-2 text-xs text-muted-foreground">Showing {sorted.length} of {total}.</p>}
    </section>
  );
}

export function AuditDiffView({ diff }: { diff: AuditDiff }) {
  const p = diff.pages;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <IssueGroup title="New issues" issues={diff.issues.new} total={diff.issues.new_count} />
        <IssueGroup title="Fixed issues" issues={diff.issues.fixed} total={diff.issues.fixed_count} />
      </div>
      <section className="rounded-[18px] border bg-card p-5 text-[13px]">
        <h3 className="mb-3 font-semibold tracking-tight">Pages</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          <div><p className="mb-1 text-xs text-muted-foreground">Added ({p.added_count})</p>{p.added.map((u) => <p key={u} className="truncate">{u}</p>)}</div>
          <div><p className="mb-1 text-xs text-muted-foreground">Removed ({p.removed_count})</p>{p.removed.map((u) => <p key={u} className="truncate">{u}</p>)}</div>
          <div><p className="mb-1 text-xs text-muted-foreground">Status changed ({p.status_changed_count})</p>
            {p.status_changed.map((s) => <p key={s.url} className="truncate">{s.url} <span className="tabular-nums text-muted-foreground">{s.old_status ?? "—"} → {s.new_status ?? "—"}</span></p>)}</div>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{diff.issues.persisting_count} issues unchanged.</p>
      </section>
    </div>
  );
}
```

`app/projects/[id]/audits/page.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { AuditDiffView } from "@/components/platform/audit-diff";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { PageHeader } from "@/components/platform/page-header";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export default function SiteAuditPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const audits = useApi(() => Platform.listAudits(projectId, 50), [projectId]);
  const items = audits.data?.items ?? [];
  const [selected, setSelected] = useState<number | null>(null);
  const [against, setAgainst] = useState<number | null>(null);

  useEffect(() => {
    if (items.length >= 1 && selected === null) setSelected(items[0].id);
    if (items.length >= 2 && against === null) setAgainst(items[1].id);
  }, [items, selected, against]);

  const diff = useApi(selected !== null && against !== null ? () => Platform.auditDiff(selected, against) : null, [selected, against]);

  return (
    <div className="space-y-6">
      <PageHeader title="Site Audit" description="Every audit of this site, and what changed between any two." />
      <AsyncState state={audits} isEmpty={(d) => d.items.length === 0} emptyTitle="No audits yet"
                  emptyAction={<Link href="/" className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">Run an audit</Link>}>
        {() => (
          <>
            <div className="overflow-x-auto rounded-[18px] border bg-card">
              <table className="w-full min-w-[640px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="sticky left-0 bg-card px-4 py-3 font-medium">Finished</th>
                    <th className="px-4 py-3 font-medium">Trigger</th>
                    <th className="px-4 py-3 text-right font-medium">Pages</th>
                    <th className="px-4 py-3 text-right font-medium">Health</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((a, i) => {
                    const prev = items[i + 1];
                    const delta = prev && a.health_score != null && prev.health_score != null
                      ? Math.round((a.health_score - prev.health_score) * 10) / 10 : null;
                    return (
                      <tr key={a.id} className="border-b last:border-0">
                        <td className="sticky left-0 bg-card px-4 py-3">{when(a.finished_at)}</td>
                        <td className="px-4 py-3 capitalize text-muted-foreground">{a.trigger}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{a.page_count}</td>
                        <td className="px-4 py-3 text-right tabular-nums"><span className="mr-2">{a.health_score ?? "—"}</span><DeltaBadge value={delta} /></td>
                        <td className="px-4 py-3 text-right">
                          <Link href={`/dashboard?session=${a.session_id}`} className="text-primary hover:underline">Open report</Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {items.length < 2 ? (
              <EmptyState title="Run a second audit to compare" text="Each new audit of this site can be compared with any earlier one." />
            ) : (
              <section className="space-y-4">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <label className="flex items-center gap-2">Compare
                    <select aria-label="Compare audit" className="h-9 rounded-full border bg-card px-3" value={selected ?? ""}
                            onChange={(e) => setSelected(Number(e.target.value))}>
                      {items.map((a) => <option key={a.id} value={a.id}>{when(a.finished_at)}</option>)}
                    </select>
                  </label>
                  <label className="flex items-center gap-2">compare against
                    <select aria-label="Compare against" className="h-9 rounded-full border bg-card px-3" value={against ?? ""}
                            onChange={(e) => setAgainst(Number(e.target.value))}>
                      {items.filter((a) => a.id !== selected).map((a) => <option key={a.id} value={a.id}>{when(a.finished_at)}</option>)}
                    </select>
                  </label>
                </div>
                <AsyncState state={diff}>{(d) => <AuditDiffView diff={d} />}</AsyncState>
              </section>
            )}
          </>
        )}
      </AsyncState>
    </div>
  );
}
```

`app/dashboard/page.tsx`:
1. Import `useSessionParam` from `@/lib/session-param`, and add `startNewAudit` to the destructured `useAudit()` values.
2. Directly after the `useAudit()` destructuring line, call `useSessionParam(activeSessionId, startNewAudit);`.
3. Next to the `<h1 …>{start_url}</h1>` heading, add:

```tsx
{auditData.project_id && (
  <Link href={`/projects/${auditData.project_id}`} className="text-sm text-primary hover:underline">View project</Link>
)}
```

   Add `import Link from "next/link";` if it isn't imported already.

- [ ] **Step 4: Verify and commit**

Run: `cd apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

```bash
git add apps/frontend/components/platform/audit-diff.tsx "apps/frontend/app/projects/[id]/audits" apps/frontend/lib/session-param.ts apps/frontend/app/dashboard/page.tsx apps/frontend/components/__tests__/site-audit-page.test.tsx
git commit -m "feat: site audit history with diffs; open saved reports from history"
```

---

### Task 6: Rank Tracker page

**Files:**
- Create: `apps/frontend/components/platform/rank-history-chart.tsx`, `apps/frontend/app/projects/[id]/ranks/page.tsx`
- Test: `apps/frontend/components/__tests__/rank-tracker-page.test.tsx`

**Interfaces (produced):** `RankHistoryChart({history, competitors, myDomain})` (with a "Show as table" toggle), and the page default export.

- [ ] **Step 1: Write the failing tests**

`apps/frontend/components/__tests__/rank-tracker-page.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RanksPage from "@/app/projects/[id]/ranks/page";
import { RankHistoryChart } from "@/components/platform/rank-history-chart";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/ranks" }));

const kw = (id: number, phrase: string, position: number | null, change: number | null) => ({
  id, phrase, country: "US", device: "desktop", language: "en", enabled: true, change,
  latest: position === null ? null : { position, ranking_url: "https://example.com/e", status: "ranked",
                                       checked_at: "2026-10-25T09:00:00+00:00", note: null, competitor_positions: {} },
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "listProjects").mockResolvedValue({ items: [{ id: 7, domain: "example.com", name: "example.com", alert_settings: {} }] } as any);
  vi.spyOn(Platform, "listCompetitors").mockResolvedValue({ items: [{ id: 1, domain: "rival.org" }] });
});

describe("Rank Tracker page", () => {
  it("lists keywords with position and the change as a rank delta", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [kw(1, "espresso", 9, -5)] } as any);
    render(<RanksPage params={{ id: "7" }} />);
    const row = (await screen.findByText("espresso")).closest("tr")!;
    expect(within(row).getByText("9")).toBeInTheDocument();
    expect(within(row).getByLabelText("worse by 5")).toBeInTheDocument();
  });

  it("adds keywords one per line with country and device", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [] } as any);
    const add = vi.spyOn(Platform, "addKeywords").mockResolvedValue({ created: 2, skipped: 0 });
    render(<RanksPage params={{ id: "7" }} />);
    await userEvent.type(await screen.findByLabelText(/keywords to track/i), "espresso{enter}milk frother");
    await userEvent.selectOptions(screen.getByLabelText(/device/i), "mobile");
    await userEvent.click(screen.getByRole("button", { name: /add keywords/i }));
    expect(add).toHaveBeenCalledWith(7, [
      { phrase: "espresso", country: "US", device: "mobile" },
      { phrase: "milk frother", country: "US", device: "mobile" },
    ]);
  });

  it("previews a check on click only, and labels it", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [kw(1, "espresso", 4, null)] } as any);
    const preview = vi.spyOn(Platform, "previewRankCheck").mockResolvedValue({
      dry_run: true, results: [{ phrase: "espresso", position: 3, ranking_url: null, competitor_positions: {} }],
    });
    render(<RanksPage params={{ id: "7" }} />);
    await screen.findByText("espresso");
    expect(preview).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /preview check/i }));
    expect(await screen.findByRole("note")).toHaveTextContent(/made up/i);
  });

  it("invites adding keywords when none are tracked", async () => {
    vi.spyOn(Platform, "listKeywords").mockResolvedValue({ items: [] } as any);
    render(<RanksPage params={{ id: "7" }} />);
    expect(await screen.findByText(/no keywords tracked yet/i)).toBeInTheDocument();
  });
});

describe("RankHistoryChart", () => {
  it("offers the same data as a table, with competitors and gaps", async () => {
    const history = [
      { position: 4, ranking_url: null, status: "ranked", checked_at: "2026-10-20T09:00:00+00:00", note: null, competitor_positions: { "rival.org": 2 } },
      { position: null, ranking_url: null, status: "skipped", checked_at: "2026-10-21T09:00:00+00:00", note: "cap", competitor_positions: {} },
    ] as any;
    render(<RankHistoryChart history={history} competitors={["rival.org"]} myDomain="example.com" />);
    await userEvent.click(screen.getByRole("button", { name: /show as table/i }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("example.com")).toBeInTheDocument();
    expect(within(table).getByText("rival.org")).toBeInTheDocument();
    expect(within(table).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx vitest run components/__tests__/rank-tracker-page.test.tsx`
Expected: FAIL (the modules don't exist).

- [ ] **Step 3: Implement**

`components/platform/rank-history-chart.tsx`:

```tsx
"use client";

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RankCheckView } from "@seo-auditor/shared";

import { Button } from "@/components/ui/button";
import { rankSeries, SERIES_LIGHT } from "@/lib/platform-charts";

/** Position over time: #1 at the top (reversed axis), one line for the
 *  project and one per competitor in fixed slot order. A skipped check is a
 *  gap. Light-mode slots 3-5 are below 3:1 contrast, so the chart always has
 *  a legend and a table view (dataviz rule). */
export function RankHistoryChart({ history, competitors, myDomain }: {
  history: RankCheckView[]; competitors: string[]; myDomain: string;
}) {
  const [asTable, setAsTable] = useState(false);
  const { points, maxPosition } = rankSeries(history, competitors.slice(0, 5));
  const series = [{ key: "me", name: myDomain }, ...competitors.slice(0, 5).map((d) => ({ key: d, name: d }))];

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" className="rounded-full" onClick={() => setAsTable((t) => !t)}>
          {asTable ? "Show as chart" : "Show as table"}
        </Button>
      </div>
      {asTable ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-[13px]">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b"><th className="px-3 py-2 font-medium">Date</th>
                {series.map((s) => <th key={s.key} className="px-3 py-2 text-right font-medium">{s.name}</th>)}</tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="px-3 py-2">{p.label}</td>
                  {series.map((s) => <td key={s.key} className="px-3 py-2 text-right tabular-nums">{(p[s.key] as number | null) ?? "—"}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-60 w-full sm:h-80" role="img" aria-label={`Ranking history for ${myDomain} and competitors`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 24, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <YAxis reversed domain={[1, maxPosition]} allowDecimals={false}
                     tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {series.map((s, i) => (
                <Line key={s.key} dataKey={s.key} name={s.name} stroke={SERIES_LIGHT[i]} strokeWidth={2}
                      dot={{ r: 4 }} activeDot={{ r: 5 }} connectNulls={false} type="monotone" />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
```

`app/projects/[id]/ranks/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import type { RankPreview, TrackedKeyword } from "@seo-auditor/shared";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { PageHeader } from "@/components/platform/page-header";
import { RankHistoryChart } from "@/components/platform/rank-history-chart";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function RanksPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const keywords = useApi(() => Platform.listKeywords(projectId), [projectId]);
  const competitors = useApi(() => Platform.listCompetitors(projectId), [projectId]);
  const projects = useApi(() => Platform.listProjects(), []);
  const project = projects.data?.items.find((p) => p.id === projectId);

  const [text, setText] = useState("");
  const [country, setCountry] = useState("US");
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [competitorInput, setCompetitorInput] = useState("");
  const [selected, setSelected] = useState<TrackedKeyword | null>(null);
  const [preview, setPreview] = useState<RankPreview | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const history = useApi(selected ? () => Platform.keywordHistory(selected.id, 90) : null, [selected?.id]);
  const domains = (competitors.data?.items ?? []).map((c) => c.domain);

  const act = async (fn: () => Promise<unknown>, after?: () => void) => {
    setMessage(null);
    try { await fn(); after?.(); } catch (e) { setMessage(e instanceof ApiError ? e.detail : String(e)); }
  };

  const addKeywords = () => {
    const phrases = text.split("\n").map((p) => p.trim()).filter(Boolean);
    if (!phrases.length) return;
    act(() => Platform.addKeywords(projectId, phrases.map((phrase) => ({ phrase, country, device }))),
        () => { setText(""); keywords.reload(); });
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Rank Tracker" description="Daily Google positions for this site and its competitors."
        actions={<Button variant="outline" className="rounded-full active:scale-95"
                         onClick={() => act(async () => setPreview(await Platform.previewRankCheck(projectId)))}>Preview check</Button>} />
      {message && <p role="status" className="rounded-[18px] border px-4 py-3 text-sm">{message}</p>}

      <section className="grid gap-4 rounded-[18px] border bg-card p-5 lg:grid-cols-[2fr_1fr_1fr_auto] lg:items-end">
        <label className="space-y-1 text-sm">
          <span className="text-xs text-muted-foreground">Keywords to track (one per line)</span>
          <textarea aria-label="Keywords to track" value={text} onChange={(e) => setText(e.target.value)} rows={2}
                    className="w-full rounded-xl border bg-background px-3 py-2 text-sm" />
        </label>
        <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
          <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="rounded-full" />
        </label>
        <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Device</span>
          <select aria-label="Device" value={device} onChange={(e) => setDevice(e.target.value as "desktop" | "mobile")}
                  className="h-10 w-full rounded-full border bg-background px-3 text-sm">
            <option value="desktop">Desktop</option><option value="mobile">Mobile</option>
          </select>
        </label>
        <Button className="rounded-full active:scale-95" onClick={addKeywords}>Add keywords</Button>
      </section>

      <AsyncState state={keywords} isEmpty={(d) => d.items.length === 0} emptyTitle="No keywords tracked yet"
                  emptyText="Add a few keywords above. They're checked daily once a live rank provider is configured.">
        {(d) => (
          <div className="overflow-x-auto rounded-[18px] border bg-card">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="sticky left-0 bg-card px-4 py-3 font-medium">Keyword</th>
                  <th className="px-4 py-3 font-medium">Where</th>
                  <th className="px-4 py-3 text-right font-medium">Position</th>
                  <th className="px-4 py-3 font-medium">Ranking URL</th>
                  <th className="px-4 py-3 font-medium">Tracking</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {d.items.map((k) => (
                  <tr key={k.id} className={`border-b last:border-0 ${selected?.id === k.id ? "bg-muted/40" : ""}`}>
                    <td className="sticky left-0 bg-card px-4 py-3">
                      <button type="button" className="text-left font-medium hover:text-primary" onClick={() => setSelected(k)}>{k.phrase}</button>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{k.country}/{k.device}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      <span className="mr-2">{k.latest?.position ?? (k.latest ? "—" : "not checked")}</span>
                      <DeltaBadge value={k.change != null ? -k.change : null} lowerIsBetter />
                    </td>
                    <td className="max-w-[240px] truncate px-4 py-3 text-muted-foreground">{k.latest?.ranking_url ?? ""}</td>
                    <td className="px-4 py-3">
                      <input type="checkbox" aria-label={`Track ${k.phrase}`} checked={k.enabled}
                             onChange={(e) => act(() => Platform.setKeywordEnabled(k.id, e.target.checked), keywords.reload)} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button type="button" aria-label={`Delete ${k.phrase}`} className="inline-flex h-11 w-11 items-center justify-center rounded-full hover:bg-muted"
                              onClick={() => act(() => Platform.deleteKeyword(k.id), keywords.reload)}><Trash2 className="h-4 w-4" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncState>

      {selected && (
        <section className="rounded-[18px] border bg-card p-5">
          <h2 className="mb-2 font-semibold tracking-tight">“{selected.phrase}” over the last 90 days</h2>
          <AsyncState state={history} isEmpty={(h) => h.items.length === 0} emptyTitle="No checks yet">
            {(h) => <RankHistoryChart history={h.items} competitors={domains} myDomain={project?.domain ?? "this site"} />}
          </AsyncState>
        </section>
      )}

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-[18px] border bg-card p-5">
          <h2 className="mb-3 font-semibold tracking-tight">Competitors</h2>
          <div className="flex gap-2">
            <Input aria-label="Competitor domain" placeholder="rival.com" value={competitorInput}
                   onChange={(e) => setCompetitorInput(e.target.value)} className="rounded-full" />
            <Button className="rounded-full active:scale-95"
                    onClick={() => act(() => Platform.addCompetitor(projectId, competitorInput), () => { setCompetitorInput(""); competitors.reload(); })}>Add</Button>
          </div>
          <ul className="mt-3 divide-y text-sm">
            {(competitors.data?.items ?? []).map((c) => (
              <li key={c.id} className="flex items-center justify-between py-2">{c.domain}
                <button type="button" aria-label={`Remove ${c.domain}`} className="text-muted-foreground hover:text-foreground"
                        onClick={() => act(() => Platform.deleteCompetitor(projectId, c.id), competitors.reload)}><Trash2 className="h-4 w-4" /></button>
              </li>
            ))}
          </ul>
        </div>
        <AlertSettingsForm projectId={projectId} initial={project?.alert_settings ?? {}} onError={setMessage} />
      </section>

      {preview && (
        <section className="space-y-3 rounded-[18px] border bg-card p-5">
          <h2 className="font-semibold tracking-tight">Preview</h2>
          <DryRunBanner show={preview.dry_run} />
          <ul className="divide-y text-sm">
            {preview.results.map((r) => <li key={r.phrase} className="flex justify-between py-2"><span>{r.phrase}</span><span className="tabular-nums">{r.position ?? "not ranked"}</span></li>)}
          </ul>
        </section>
      )}
    </div>
  );
}

function AlertSettingsForm({ projectId, initial, onError }: {
  projectId: number; initial: { drop_threshold?: number; top10_alerts?: boolean; gain_threshold?: number | null }; onError: (m: string) => void;
}) {
  const [drop, setDrop] = useState(String(initial.drop_threshold ?? 3));
  const [top10, setTop10] = useState(initial.top10_alerts ?? true);
  const [gain, setGain] = useState(initial.gain_threshold != null ? String(initial.gain_threshold) : "");
  const [saved, setSaved] = useState(false);
  const save = async () => {
    setSaved(false);
    try {
      await Platform.updateProject(projectId, { alert_settings: {
        drop_threshold: Number(drop) || 3, top10_alerts: top10, gain_threshold: gain ? Number(gain) : null } });
      setSaved(true);
    } catch (e) { onError(e instanceof ApiError ? e.detail : String(e)); }
  };
  return (
    <div className="space-y-3 rounded-[18px] border bg-card p-5 text-sm">
      <h2 className="font-semibold tracking-tight">Alerts</h2>
      <label className="flex items-center justify-between gap-3">Alert when a keyword drops by at least
        <Input aria-label="Drop threshold" type="number" min={1} value={drop} onChange={(e) => setDrop(e.target.value)} className="w-20 rounded-full" />
      </label>
      <label className="flex items-center justify-between gap-3">Alert when a keyword leaves the top 10
        <input type="checkbox" aria-label="Top 10 alerts" checked={top10} onChange={(e) => setTop10(e.target.checked)} />
      </label>
      <label className="flex items-center justify-between gap-3">Also alert on gains of at least (blank = off)
        <Input aria-label="Gain threshold" type="number" min={1} value={gain} onChange={(e) => setGain(e.target.value)} className="w-20 rounded-full" />
      </label>
      <div className="flex items-center gap-3">
        <Button variant="outline" className="rounded-full active:scale-95" onClick={save}>Save alerts</Button>
        {saved && <span role="status" className="text-xs text-muted-foreground">Saved</span>}
      </div>
    </div>
  );
}
```

   The add-keywords test types `espresso{enter}milk frother` into the textarea. Enter inserts a newline there, so this produces the two phrases.

- [ ] **Step 4: Verify and commit**

Run: `cd apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

```bash
git add apps/frontend/components/platform/rank-history-chart.tsx "apps/frontend/app/projects/[id]/ranks" apps/frontend/components/__tests__/rank-tracker-page.test.tsx
git commit -m "feat: rank tracker page -- keywords, competitors, history chart with table view, alerts, preview"
```

---

### Task 7: Content Gap page

**Files:**
- Create: `apps/frontend/app/projects/[id]/gap/page.tsx`
- Test: `apps/frontend/components/__tests__/content-gap-page.test.tsx`

- [ ] **Step 1: Write the failing tests**

`apps/frontend/components/__tests__/content-gap-page.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx vitest run components/__tests__/content-gap-page.test.tsx`
Expected: FAIL (the module doesn't exist).

- [ ] **Step 3: Implement**

`app/projects/[id]/gap/page.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { GapResult } from "@seo-auditor/shared";

import { AsyncState, EmptyState } from "@/components/platform/async-state";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { PageHeader } from "@/components/platform/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function GapPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const competitors = useApi(() => Platform.listCompetitors(projectId), [projectId]);
  const [picked, setPicked] = useState<string[]>([]);
  const [country, setCountry] = useState("US");
  const [limit, setLimit] = useState(500);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<GapResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (competitors.data) setPicked(competitors.data.items.slice(0, 5).map((c) => c.domain));
  }, [competitors.data]);

  const run = async () => {
    setRunning(true); setError(null);
    try {
      setResult(await Platform.contentGap(projectId, { competitors: picked, country, language: "en", limit }));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Content Gap" description="Keywords your competitors rank for in the top 20 that you don't rank for at all." />
      <AsyncState state={competitors} isEmpty={(d) => d.items.length === 0} emptyTitle="Add competitors first"
                  emptyText="Content gap compares this site with its competitors."
                  emptyAction={<Link href={`/projects/${projectId}/ranks`} className="text-sm text-primary hover:underline">Add competitors in Rank Tracker</Link>}>
        {(d) => (
          <section className="flex flex-col gap-4 rounded-[18px] border bg-card p-5 lg:flex-row lg:items-end">
            <fieldset className="flex flex-wrap gap-3 text-sm">
              <legend className="mb-2 text-xs text-muted-foreground">Competitors (up to 5)</legend>
              {d.items.map((c) => (
                <label key={c.id} className="flex items-center gap-2 rounded-full border px-3 py-1.5">
                  <input type="checkbox" aria-label={c.domain} checked={picked.includes(c.domain)}
                         disabled={!picked.includes(c.domain) && picked.length >= 5}
                         onChange={(e) => setPicked((p) => (e.target.checked ? [...p, c.domain] : p.filter((x) => x !== c.domain)))} />
                  {c.domain}
                </label>
              ))}
            </fieldset>
            <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
              <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="w-20 rounded-full" />
            </label>
            <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Keywords per domain</span>
              <Input aria-label="Keywords per domain" type="number" min={10} max={1000} value={limit}
                     onChange={(e) => setLimit(Number(e.target.value) || 500)} className="w-28 rounded-full" />
            </label>
            <Button className="rounded-full active:scale-95" disabled={running || picked.length === 0} onClick={run}>
              {running ? "Running…" : "Run gap analysis"}
            </Button>
          </section>
        )}
      </AsyncState>

      {error && <div role="alert" className="rounded-[18px] border border-rose-200 bg-rose-50/60 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-400">{error}</div>}

      {result && (
        <section className="space-y-3">
          <DryRunBanner show={result.dry_run} />
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{result.total_gaps} gaps, sorted by opportunity (volume weighted by ease)</p>
            <a className="text-sm text-primary hover:underline" href={Platform.contentGapCsvUrl(projectId, result.competitors, country, "en", limit)}>
              Download CSV{result.dry_run ? " (preview)" : ""}
            </a>
          </div>
          {result.rows.length === 0 ? <EmptyState title="No gaps found" text="Every keyword these competitors win, you rank for too." /> : (
            <div className="overflow-x-auto rounded-[18px] border bg-card">
              <table className="w-full min-w-[720px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="sticky left-0 bg-card px-4 py-3 font-medium">Keyword</th>
                    <th className="px-4 py-3 text-right font-medium">Volume</th>
                    <th className="px-4 py-3 text-right font-medium">KD</th>
                    <th className="px-4 py-3 text-right font-medium">Opportunity</th>
                    {result.competitors.map((c) => <th key={c} className="px-4 py-3 text-right font-medium">{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((r) => (
                    <tr key={r.keyword} className="border-b last:border-0">
                      <td className="sticky left-0 bg-card px-4 py-3 font-medium">{r.keyword}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{r.search_volume?.toLocaleString() ?? "—"}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{r.difficulty ?? "—"}</td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">{Math.round(r.opportunity).toLocaleString()}</td>
                      {result.competitors.map((c) => <td key={c} className="px-4 py-3 text-right tabular-nums">{r.competitors[c]?.position ?? "—"}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

```bash
git add "apps/frontend/app/projects/[id]/gap" apps/frontend/components/__tests__/content-gap-page.test.tsx
git commit -m "feat: content gap page -- run on click, ranked table, CSV, preview labelling"
```

---

### Task 8: Keywords Explorer page

**Files:**
- Create: `apps/frontend/app/keywords/page.tsx`
- Test: `apps/frontend/components/__tests__/keywords-explorer-page.test.tsx`

- [ ] **Step 1: Write the failing tests**

`apps/frontend/components/__tests__/keywords-explorer-page.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx vitest run components/__tests__/keywords-explorer-page.test.tsx`
Expected: FAIL (the module doesn't exist).

- [ ] **Step 3: Implement**

`app/keywords/page.tsx`:

```tsx
"use client";

import { FormEvent, useState } from "react";
import type { ExploreResult } from "@seo-auditor/shared";

import { EmptyState } from "@/components/platform/async-state";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { PageHeader } from "@/components/platform/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, Platform } from "@/services/platform";

const SOURCE = { seed: "Seed", autocomplete: "Autocomplete", people_also_ask: "People Also Ask" } as const;
const n = (v: number | null) => (v == null ? "—" : v.toLocaleString());

export default function KeywordsPage() {
  const [seed, setSeed] = useState("");
  const [country, setCountry] = useState("US");
  const [cluster, setCluster] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ExploreResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!seed.trim()) return;
    setRunning(true); setError(null);
    try {
      setResult(await Platform.explore({ seed, country, language: "en", cluster }));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title="Keywords Explorer" description="Ideas, search volume, difficulty and a traffic estimate for any seed keyword." />
      <form onSubmit={submit} className="flex flex-col gap-4 rounded-[18px] border bg-card p-5 lg:flex-row lg:items-end">
        <label className="flex-1 space-y-1 text-sm"><span className="text-xs text-muted-foreground">Seed keyword</span>
          <Input aria-label="Seed keyword" placeholder="espresso machine" value={seed} maxLength={80}
                 onChange={(e) => setSeed(e.target.value)} className="rounded-full" />
        </label>
        <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
          <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="w-20 rounded-full" />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" aria-label="Group into clusters" checked={cluster} onChange={(e) => setCluster(e.target.checked)} />
          Group into clusters <span className="text-xs text-muted-foreground">(one search per keyword)</span>
        </label>
        <Button type="submit" className="rounded-full active:scale-95" disabled={running || !seed.trim()}>
          {running ? "Exploring…" : "Explore"}
        </Button>
      </form>

      {error && <div role="alert" className="rounded-[18px] border border-rose-200 bg-rose-50/60 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-400">{error}</div>}

      {!result && !error && <EmptyState title="Enter a seed keyword" text="You'll get related ideas from Google Autocomplete and People Also Ask, with their metrics." />}

      {result && (
        <section className="space-y-4">
          <DryRunBanner show={result.dry_run} />
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{result.keywords.length} keywords for “{result.seed}”</p>
            <a className="text-sm text-primary hover:underline" href={Platform.exploreCsvUrl(result.seed, result.country, result.language)}>
              Download CSV{result.dry_run ? " (preview)" : ""}
            </a>
          </div>
          <div className="overflow-x-auto rounded-[18px] border bg-card">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="sticky left-0 bg-card px-4 py-3 font-medium">Keyword</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 text-right font-medium">Volume</th>
                  <th className="px-4 py-3 text-right font-medium">KD</th>
                  <th className="px-4 py-3 text-right font-medium">CPC</th>
                  <th className="px-4 py-3 text-right font-medium" title="Search volume × typical click-through rate of the #1 result">Traffic (est.)</th>
                </tr>
              </thead>
              <tbody>
                {result.keywords.map((k) => (
                  <tr key={k.keyword} className="border-b last:border-0">
                    <td className="sticky left-0 bg-card px-4 py-3 font-medium">{k.keyword}</td>
                    <td className="px-4 py-3 text-muted-foreground">{SOURCE[k.source]}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{n(k.search_volume)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{k.difficulty ?? "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{k.cpc != null ? `$${k.cpc.toFixed(2)}` : "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{n(k.traffic_potential_estimate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.clusters.length > 0 && (
            <div className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Clusters</h2>
              <div className="space-y-3">
                {result.clusters.map((group) => (
                  <div key={group[0]} className="flex flex-wrap gap-2">
                    {group.map((k, i) => <span key={k} className={`rounded-full border px-3 py-1 text-xs ${i === 0 ? "font-semibold" : ""}`}>{k}</span>)}
                  </div>
                ))}
              </div>
            </div>
          )}
          {result.notes.length > 0 && <ul className="text-xs text-muted-foreground">{result.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
        </section>
      )}
    </main>
  );
}
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

```bash
git add apps/frontend/app/keywords apps/frontend/components/__tests__/keywords-explorer-page.test.tsx
git commit -m "feat: keywords explorer page -- ideas table, clusters on request, CSV, estimate labelling"
```

---

### Task 9: Build, browser check, docs

- [ ] **Step 1: Production build.** `cd <repo root> && npm run build`. Expected: compiles with no type or lint errors.
- [ ] **Step 2: Real app.** On a scratch `SESSION_DIR`, start the backend with `SERP_PROVIDER=dry_run` and every key blank, then the frontend (`npm run dev`). Seed data:
  - two CLI audits of `books.toscrape.com` (20 pages)
  - 3 keywords and 2 competitors added via the API
- [ ] **Step 3: Screenshots.** In Chrome, at 1440×900 and 390×844, screenshot:
  - `/projects`
  - `/projects/1`
  - `/projects/1/audits`
  - `/projects/1/ranks`, after Preview check
  - `/projects/1/gap`, after Run
  - `/keywords`, after exploring "espresso machine" with clusters
  - `/dashboard?session=<id>` (opened from Site Audit)

  Look at each one for: overlapping text, horizontal page scroll on mobile, unreadable charts, missing states, and dry-run banners present. Fix anything found, with a test where it's behaviour.
- [ ] **Step 4: Docs.** Add a "Platform dashboard (Phase 4)" section to `README.md` listing the pages and a **How to verify** that follows Step 2–3. Note `DESIGN.md` and its adaptations section.
- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: Phase 4 dashboard pages and verification"
```
