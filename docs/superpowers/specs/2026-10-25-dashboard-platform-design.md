# Phase 4: Dashboard Platform — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Branch:** `feat/dashboard-platform`
**Brief:** `BUILD_PROMPT.md` Phase 4

## Problem

The frontend is a single-audit tool: a start form (`/`), a live crawl view
(`/live-crawl`) and one audit dashboard (`/dashboard`). Phases 1–3 added
projects, audit history and diffs, rank tracking, keyword research and content
gap, but only as APIs. None of them has a page.

## Decisions taken

- **Project-first layout with top navigation:** a thin global nav, plus a
  frosted sticky sub-nav inside a project (project switcher + tabs).
- **Extend the existing Next.js 14 app** (Tailwind, shadcn-style `components/ui`,
  Recharts, Vitest). Nothing is rebuilt, and the existing audit dashboard stays
  as the "full report".
- **`DESIGN.md`** (from `npx getdesign@latest add apple`, run with the owner's
  OK) is followed **selectively**. It describes Apple's marketing site, so the
  overrides for a data dashboard are recorded in a new section of that file
  (§1).

## Design

### 1. Design system: `apps/frontend/DESIGN.md` + tokens

Append a section **"SEO dashboard adaptations"** to `DESIGN.md`:

| Topic | Rule |
| --- | --- |
| **Adopted** | One blue accent (`--primary`) for every interactive element. Cards are white with a 1px hairline (`--border`), **no shadow**, and an 18px radius (`rounded-[18px]`). Primary buttons are pills with `active:scale-95`. Search inputs are pills. Headlines use weight 600 with tight tracking (`tracking-tight`). |
| **Severity colors** (required by the brief; overrides "no second color") | critical = rose, warning = amber, info = slate, exactly the classes in `lib/utils.ts` `getSeverityBadge`, used **only** for severity. |
| **Charts** (overrides "no second color") | Series colors follow the dataviz skill's palette guidance, chosen when charts are built. Severity colors never appear as series colors except in severity charts. |
| **Density** (overrides 17px body and 80px sections) | Body 14px, tables 13px, card padding 20–24px, section gaps 24–32px. |
| **States** (not covered by the source) | Every data view has explicit loading (skeleton), empty (message + one primary action) and error (message + Retry) states. |
| **Dark mode** (not covered by the source) | The existing `.dark` tokens in `globals.css` stay. Severity classes already include `dark:` variants. |
| **Not adopted** | Full-bleed alternating dark/light product tiles, photography rules, 80px section padding. |

No new token system: the existing CSS variables and Tailwind config stay. The
adaptations are expressed as Tailwind classes in the components below.

### 2. Routes and navigation

| Route | Purpose | Data |
| --- | --- | --- |
| *(global nav)* | Logo · **Projects** · **Keywords Explorer** · **+ New audit** (→ `/`). 52px tall, sticky, hairline bottom border. Collapses to a menu button below 768px. | — |
| `/projects` | A grid of project cards: name/domain, latest health score with change since the previous audit, tracked-keyword count, last audit date. Empty state: "Run your first audit" → `/`. | `GET /api/projects` |
| `/projects/[id]` (Overview) | KPI tiles: health (with change), tracked keywords, average position (with change), latest audit page count. A **health over time** line chart. A **latest audit diff** card (new / fixed counts by severity, link to the Site Audit tab). **Biggest rank moves** (top 5 by absolute change). | `/projects/{id}/audits?limit=50`, `/audits/{latest}/diff` (only if ≥ 2 audits), `/projects/{id}/keywords` |
| `/projects/[id]/audits` (Site Audit) | **History table:** date, trigger, pages, health, "Open report". Selecting two rows (or default: newest vs previous) shows the **diff**: new and fixed issues grouped by severity (severity badges), pages added/removed, status changes. "Open report" → `/dashboard?session=<session_id>`. | `/projects/{id}/audits`, `/audits/{id}/diff?against=` |
| `/projects/[id]/ranks` (Rank Tracker) | **Keyword table:** phrase, country/device, position, change, ranking URL, last checked, enabled toggle, delete. An **Add keywords** form (textarea, one per line + country + device). **Competitors** list (add/remove). Selecting a keyword opens a **position history chart** (y-axis inverted so #1 is at the top; one line for the project and one per competitor; a skipped check is a gap, not zero). **Alert settings** form (drop threshold, top-10 alerts, gain threshold). **Preview check** button → dry-run preview table, labelled. | rank endpoints (Phase 2) |
| `/projects/[id]/gap` (Content Gap) | Competitor selector (from project competitors, 1–5) + country/language + limit. **Run** (never on load) → a table sorted by opportunity: keyword, volume, KD, opportunity, best competitor position, a position per competitor. **Download CSV**. | `POST /projects/{id}/content-gap`, `GET …/content-gap.csv` |
| `/keywords` (Keywords Explorer) | A seed + country + language form, and a **Cluster** checkbox (labelled "uses one search per keyword"). Results: ideas table (keyword, source, volume, KD, CPC, traffic estimate, labelled "est."), clusters as grouped chips. **Download CSV**. | `POST /keywords/explore`, `GET /keywords/explore.csv` |

**Project shell:** `app/projects/[id]/layout.tsx` renders the frosted sub-nav
(`bg-background/80 backdrop-blur`, sticky under the global nav): the project
switcher (a dropdown of `GET /api/projects`) and the tabs Overview · Site Audit
· Rank Tracker · Content Gap. Tabs scroll horizontally on phones.

**Open an old report:** `/dashboard` reads `?session=<id>` on mount. If it
differs from the active session, it calls the existing
`useAudit().startNewAudit(id)`, which polls `GET /api/audit/latest` and loads
the finished audit. No backend change.

**After an audit:** the existing dashboard header gains a "View project" link
when the audit result carries `project_id`.

### 3. Data layer

- `services/platform.ts`: typed functions for every Phase 1–3 endpoint used
  above. Same `fetch` + `API_BASE_URL` pattern as `services/api.ts`. A non-2xx
  response throws `ApiError {status, detail}` (FastAPI's `detail` string).
- `lib/use-api.ts`: `useApi<T>(fetcher, deps)` → `{data, error, isLoading,
  reload}`. It ignores stale responses when deps change, and doesn't fetch
  when `fetcher` is `null` (a conditional request).
- Types for the new payloads in `packages/shared/src/types/platform.ts`,
  re-exported from the package index.

### 4. Shared components (`components/platform/`)

- `AsyncState`: renders a skeleton, an empty state (title, text, optional
  action) or an error state (message + Retry) from a `useApi` result, else its
  children.
- `DeltaBadge({value, lowerIsBetter})`: ▲/▼ with a green/rose tone. For ranks
  `lowerIsBetter`, so position 9 → 4 is shown as improved.
- `DryRunBanner`: "Preview data — DataForSEO is not live; numbers are made up."
  Shown whenever a response has `dry_run: true`.
- `KpiTile`, `PageHeader`, `ProjectSwitcher`, `GlobalNav`, `ProjectTabs`.
- `RankHistoryChart`: Recharts line chart, reversed y-axis, `connectNulls={false}`.
- `HealthTrendChart`: Recharts line chart of health score per audit.

### 5. Cost safety in the UI

- Content Gap and clustering run **only on an explicit click**, never on mount
  or on changing a field.
- A 429 shows the backend's reason ("daily cap of N … reached") inline. A 502
  shows the provider message.
- Dry-run responses always show `DryRunBanner`. CSV downloads say "(preview)"
  in the button label when the last response was a dry run.

### 6. Responsive

- **Breakpoints:** phone < 640px, tablet 640–1023px, desktop ≥ 1024px. Content
  max-width 1280px.
- **KPI tiles:** 4 columns (desktop) → 2 (tablet) → 1 (phone).
- **Tables:** scroll horizontally inside their card, with the first column
  sticky.
- **Charts:** `ResponsiveContainer`, 240px tall on phones and 320px otherwise.
- **Touch targets:** at least 44px.

## Error handling

| Response | What the UI does |
| --- | --- |
| 503 (central DB down) | Error state: "Project data is unavailable right now", with Retry. |
| 404 project | "Project not found", with a link to `/projects`. |
| 404 diff (only one audit) | Empty state: "Run a second audit to compare". |
| 409 live rank run | "No live rank provider configured", shown inline. |
| Network failure | Error state with Retry. |

## Testing

- Vitest + Testing Library, with `services/platform.ts` mocked per test.
- **Every page:** the loading, empty, error and data states.
- **Projects list:** card content, and the empty state's call to action.
- **Overview:** KPI changes; the diff card is hidden with fewer than 2 audits.
- **Site Audit:** the default comparison is newest vs previous; picking two
  audits changes the request; severity grouping; the "Open report" link.
- **Rank Tracker:**
  - the add-keywords call shape
  - the delta direction (lower is better)
  - the chart's y-axis is reversed and skipped points become nulls
  - preview shows the banner
- **Content Gap:** no request until Run; the competitor default; CSV link
  parameters; a 429 message.
- **Explorer:** cluster off by default; the banner on dry run; the "est." label.
- **`/dashboard?session=`:** calls `startNewAudit` with that id.
- **`DeltaBadge`, `AsyncState`, `useApi`:** unit tests, including the stale
  response being ignored.
- **Browser check:** before finishing, run the real app (backend in dry run +
  frontend) and screenshot every page at 1440px and 390px wide.

## Done when

All five pages work against the real backend with explicit
loading/empty/error states, at desktop and phone widths. Existing pages and
tests are unaffected. The `DESIGN.md` adaptations section is committed.

## Out of scope

- Authentication and multi-user.
- Restyling the existing audit dashboard panels.
- Saving explorer or gap runs.
- Notifications UI (alerts are configured here; they're delivered by Slack/email).
