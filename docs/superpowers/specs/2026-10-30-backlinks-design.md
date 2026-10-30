# Phase 6: Backlinks (Site Explorer) — Design

**Date:** 2026-10-30
**Status:** Approved, pending implementation plan
**Branch:** `feat/backlinks`
**Brief:** `BUILD_PROMPT.md` Phase 6: "BacklinkProvider via DataForSEO:
referring domains, backlinks, new/lost links, broken backlinks, an authority
score (clearly labeled as provider-derived). Store snapshots to chart growth
over time."

## Problem

The platform has no view of who links to a site: no referring domains, no
new or lost links, no broken backlinks worth redirecting, and no growth
history. `backlink_snapshots` exists (Phase 1) but is unused.

## Decisions taken

- **Scope:** the site's profile, growth over time, a competitor link gap,
  and broken backlinks joined into audits.
- **Schedule:** a weekly refresh, **opt-in per project** (off by default),
  plus "Refresh now". A hard daily cap applies to every request.
- **Cost (DataForSEO Backlinks API):** pay-as-you-go, about $0.024 per
  request plus $0.000036 per row. A snapshot is 5 requests (about $0.25), the
  first one adds a history request, and the link gap is about $0.05–0.10.
  There's no live call without credentials, `SERP_PROVIDER=dataforseo` and
  `SERP_DRY_RUN=false`. The owner OKs the first live call. No DataForSEO
  credentials are configured today.

## Design

### 1. Provider: `app/backlinks/provider.py`

```python
@dataclass(frozen=True)
class BacklinkSummary:  authority: Optional[int]; backlinks: int; referring_domains: int; broken_backlinks: int
@dataclass(frozen=True)
class RefDomain:        domain: str; rank: Optional[int]; backlinks: int; first_seen: Optional[str]
@dataclass(frozen=True)
class Backlink:         url_from: str; url_to: str; anchor: str; domain_from_rank: Optional[int]; dofollow: bool
                        first_seen: Optional[str]; last_seen: Optional[str]; target_status: Optional[int]
@dataclass(frozen=True)
class HistoryPoint:     month: date; authority: Optional[int]; backlinks: int; referring_domains: int
@dataclass(frozen=True)
class GapDomain:        domain: str; rank: Optional[int]; linked_competitors: Dict[str, int]   # competitor -> backlinks

class BacklinkProvider(Protocol):
    name: str; dry_run: bool
    def summary(self, target) -> BacklinkSummary
    def referring_domains(self, target, limit=100) -> List[RefDomain]
    def backlinks(self, target, kind: Literal["new","lost","broken"], since: date, limit=100) -> List[Backlink]
    def history(self, target, months=12) -> List[HistoryPoint]
    def intersection(self, competitors: List[str], exclude: str, limit=100) -> List[GapDomain]
```

- **`DataForSeoBacklinks(login, password, cap)`** uses the existing
  `post_task` helper. Each request first calls
  `spend.reserve("dataforseo_backlinks", DATAFORSEO_BACKLINKS_DAILY_CAP)`
  (default 20). Endpoints (`POST https://api.dataforseo.com/v3/…`, one task
  each):

  | Method | Path | Task |
  | --- | --- | --- |
  | summary | `backlinks/summary/live` | `{target, include_subdomains: true}` → `rank, backlinks, referring_domains, broken_backlinks` |
  | referring_domains | `backlinks/referring_domains/live` | `{target, limit, order_by: ["rank,desc"]}` → items `domain, rank, backlinks, first_seen` |
  | backlinks `new` | `backlinks/backlinks/live` | `{target, mode: "as_is", limit, order_by: ["domain_from_rank,desc"], filters: ["first_seen", ">=", since]}` |
  | backlinks `lost` | same | `{…, filters: [["is_lost", "=", true], "and", ["last_seen", ">=", since]]}` |
  | backlinks `broken` | same | `{…, filters: ["is_broken", "=", true]}` |
  | history | `backlinks/history/live` | `{target, date_from: today−months}` → items `date, rank, backlinks, referring_domains` |
  | intersection | `backlinks/domain_intersection/live` | `{targets: {"1": c1, …}, exclude_targets: [mine], limit, order_by: ["1.rank,desc"]}` → items keyed per target with `domain`, `rank`, `backlinks` |

  - Backlink items map `url_from, url_to, anchor, domain_from_rank,
    dofollow, first_seen, last_seen, url_to_status_code`.
  - A non-20000 status from DataForSEO raises `ProviderError(message)`. A cap
    hit raises `ProviderSkipped`. Both surface as a refresh status.
  - The field names follow DataForSEO's v3 docs. The live check validates the
    parser against DataForSEO's free **sandbox** once credentials exist; until
    then it runs on recorded sample responses in the tests.
- **`DryRunBacklinks`:** deterministic data seeded by the target. It has the
  plausible counts and lists for every method, with `dry_run=True`.
- **`get_backlink_provider(cfg)`:** live only when `SERP_PROVIDER ==
  "dataforseo"`, `not SERP_DRY_RUN`, and both credentials are set (the same
  rule as `get_keyword_provider`). Otherwise `DryRunBacklinks`.

### 2. Storage (migration `0009_backlinks`)

- **`backlink_snapshots` gains:** `authority` (int, nullable),
  `backlinks` (int), `referring_domains` (int), `broken_backlinks` (int),
  `source` (`snapshot`|`history`), `period` (Date, nullable, the month for
  history rows), `dry_run` (bool). The FK gets `ON DELETE CASCADE` through a
  batch alter. `metrics_json` and `provider` stay.
- **`backlink_ref_domains`:** `id, snapshot_id (FK cascade, indexed),
  domain, rank, backlinks, first_seen`.
- **`backlink_links`:** `id, snapshot_id (FK cascade, indexed), kind
  (new|lost|broken), url_from, url_to, anchor, domain_from_rank, dofollow,
  first_seen, last_seen, target_status`.
- **`projects` gains:** `backlink_schedule` (string 16, nullable; `weekly` or
  null) and `last_backlink_refresh_at`.

### 3. Snapshots: `app/backlinks/snapshot.py`

`refresh_project(project_id, provider, today=None) -> dict`:

- The target is the project's `domain`.
- **The first snapshot** (no `source="snapshot"` rows yet) also fetches
  `history(12)`. Each month becomes a `source="history"` row with `period`,
  skipping months that already exist.
- **The calls**, all before one write transaction:
  - summary
  - referring_domains(100)
  - backlinks `new`, `lost` and `broken` with `since = today − 30 days`
    (limit 100 each)
- **Writes:** a `source="snapshot"` row with `taken_at=now` and the
  summary, its ref domains and links, plus `last_backlink_refresh_at`.
- **Returns** `{status: "refreshed", snapshot_id, dry_run, history_months}`.
- **Failures:** `ProviderSkipped` gives `{status: "capped", message}`, and
  `ProviderError` gives `{status: "error", message}`. Nothing is written.
- **Scheduler:** `run_due_backlink_refreshes(now)`, every 6 h. It covers
  projects with `backlink_schedule == "weekly"` whose last refresh is older
  than 7 days (or never), uses `claim()` for the column, and isolates errors.
  It **skips dry-run providers** (made-up history must not be scheduled), so
  dry-run snapshots only come from Refresh now.

### 4. Link gap: `app/backlinks/gap.py`

`link_gap(project, competitors, provider) -> {my_domain, competitors,
dry_run, rows}`:

- `competitors` defaults to the project's `Competitor` domains. 1–5 are
  required (400 otherwise). The project's own domain is excluded.
- **Rows:** `{domain, rank, linked_count, backlinks_by_competitor}`, sorted
  by `linked_count` desc, then `rank` desc, up to 100. Not stored.

### 5. Broken backlinks in audits

- In `_build_audit_result`, after the Search Console step, it loads the
  project's (by `project_domain(url)`) latest `source="snapshot"` broken
  links. There's no API call, and with no snapshot it does nothing.
- It groups them by `normalize_url(url_to)` → `(count, distinct
  domains_from)`.
- **The issue:** for each crawled page with status ≥ 400 whose normalised
  URL matches, `BACKLINK_TO_BROKEN_PAGE` (warning): "{n} backlinks from {d}
  domains point to this broken page. Redirect it to keep their value."
- `IMPACT_WEIGHTS` = 8, plus a `RECOMMENDATION_TEXT` entry.
- Never fatal: an error is logged and the step is skipped.

### 6. API: `app/api/backlinks.py`

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/projects/{id}/backlinks` | `{dry_run_provider, schedule, last_refresh_at, latest: {taken_at, authority, backlinks, referring_domains, broken_backlinks, dry_run} \| null, previous: {…} \| null, history: [{date, authority, backlinks, referring_domains, source}]}`. History merges the `history` and `snapshot` rows by date, oldest first |
| GET | `/api/projects/{id}/backlinks/referring-domains?limit=50&offset=0` | `{total, items}` from the latest snapshot |
| GET | `/api/projects/{id}/backlinks/links?kind=new\|lost\|broken&limit&offset` | `{total, items}` from the latest snapshot. Broken items add `crawled_status` from the latest audit when the URL was crawled |
| POST | `/api/projects/{id}/backlinks/refresh` | the refresh result (`refreshed` / `capped` / `error`) |
| POST | `/api/projects/{id}/backlinks/gap` | `{competitors?: [...]}` → the link gap. 400 if not 1–5 |

`PATCH /api/projects/{id}` accepts `backlink_schedule: "weekly" | null`.

### 7. UI: the "Backlinks" tab (`/projects/[id]/backlinks`)

- **Controls:** a dry-run banner when `latest.dry_run` or the provider is
  dry run. **Refresh now** ("about $0.25 per refresh", showing the result).
  A **Weekly refresh** switch (`role="switch"`).
- **KPI tiles:**
  - Authority, with the subtitle "DataForSEO rank, 0–1000"
  - referring domains, backlinks, broken backlinks (lower is better)
  - each with the change vs the previous snapshot
- **Growth:** three line charts (referring domains, backlinks, authority),
  one measure each, each with a table toggle. History rows are marked "from
  DataForSEO history" in the table.
- **Tables:** top referring domains (domain, DataForSEO rank, backlinks,
  first seen), new links, lost links (from → to, anchor, rank, follow), and
  broken backlinks (to URL, status, from, "Redirect this URL to a live
  page"). Paginated by 50.
- **Link gap:** the competitor checkboxes (default all, up to 5), **Run**
  ("about $0.05–0.10"), the result table (domain, rank, links to N of M
  competitors, per-competitor backlinks) and a dry-run banner.
- **Empty state:** "No backlink data yet. Press Refresh now."
- Audits show `BACKLINK_TO_BROKEN_PAGE` in the usual issue lists.

## Error handling

| Case | Result |
| --- | --- |
| Cap reached | refresh/gap `status="capped"` with the message; nothing written |
| DataForSEO error | `status="error"` with DataForSEO's message; nothing written |
| No snapshot yet | tab empty state; the audit step does nothing |
| Gap with 0 or more than 5 competitors | 400 |
| Scheduled refresh on dry run | skipped (logged) |

## Testing

- **Provider:** with HTTP mocked: each request body (filters, order,
  limits, intersection targets/exclude), parsing from recorded sample
  responses, a non-20000 status → `ProviderError`, the cap, dry-run
  determinism, `get_backlink_provider` modes.
- **Snapshot:** writes, history only on the first run without duplicating
  months, the since date, a failure writing nothing, and `last_refresh`.
- **Scheduler:** weekly opt-in only, older than 7 days, dry run skipped,
  errors isolated.
- **Gap:** default competitors, 1–5 validation, sorting.
- **Audit issue:** matching by normalised URL, counts, no snapshot → nothing.
- **API:** every endpoint, the change vs previous, the merged history,
  pagination, kind filter, `crawled_status`, the PATCH schedule.
- **Frontend:** empty, dry run, KPIs and deltas (broken lower-is-better),
  chart table views, switch, Refresh now, the gap (checkbox defaults, run,
  results), and tables.
- **Live check:** dry run end to end (refresh, audit with a 404 that has
  backlinks, UI at 1440 and 390 px). The sandbox parser check and the first
  paid call wait for credentials and the owner's go-ahead.

## Done when

A project shows its backlink profile, growth, new/lost/broken links and a
competitor link gap, refreshed on demand or weekly by opt-in. Broken pages
with backlinks are flagged in audits. Every call is capped, dry-run safe,
and labelled as DataForSEO's data. Docs, env and tests are updated.

## Out of scope

- Anchor-text analysis, link-velocity alerts, disavow files, per-page
  backlink drill-down beyond the stored top 100 lists, and storing link-gap
  runs.
