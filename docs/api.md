# REST API Documentation

## Endpoints

### 1. Execute SEO Audit
- **URL**: `/api/audit`
- **Method**: `POST`
- **Content-Type**: `application/json`

#### Request Body
```json
{
  "url": "https://example.com",
  "max_pages": 8,
  "max_depth": 1,
  "ignore_robots": false,
  "enable_keyword_analysis": true,
  "enable_keyword_suggestions": false,
  "enable_rank_check": false,
  "enable_competitor_gap": false,
  "target_keywords": null,
  "rank_targets": [{ "url": "https://example.com/services", "keywords": ["espresso machine", "espresso reviews"] }]
}
```

- `enable_keyword_analysis` (default `true`): extracts on-page keywords per page. Pure local computation, no external calls. This flag gates extraction only — it does **not** gate keyword suggestions (see `enable_keyword_suggestions` below).
- `enable_keyword_suggestions` (default `false`): generates suggested keywords via the Google Autocomplete endpoint (an unofficial, undocumented endpoint) — up to 3 external network calls per page. Off by default because it costs real network calls with no quota protection, unlike `enable_keyword_analysis`. When `enable_competitor_gap` is also set, this step additionally fetches competitor pages. **Interaction with `rank_targets`**: if `rank_targets` is non-empty, suggestions are generated *only* for the pages that matched a rank target — every other crawled page gets none, even with this flag on. This prevents up to 3 synchronous Autocomplete calls per un-nominated page (hundreds of requests on a large crawl) and keeps suggestions grounded in an actual rank result. If `rank_targets` is omitted or empty, this flag keeps its original standalone behavior: suggestions on every page. This makes `enable_keyword_suggestions` safe to use on its own via the API without ever supplying `rank_targets`.
- `enable_rank_check` (default `false`): checks live Google rank via the Google Custom Search API, but **only for pages nominated in `rank_targets`** — it checks nothing on its own. Each (keyword, page) pair the user nominates costs exactly one query; the Google CSE free tier is 100 queries/day, and one query per keyword per page adds up fast on a large crawl, so rank checks never run automatically against extracted or unlisted pages. Requires `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_CX`; without them, results carry a "not configured" note instead of an error. See `docs/env.md`.
- `enable_competitor_gap` (default `false`): fetches the top-ranking competitor pages for each page's top keyword and diffs their keywords against the current page's. Only takes effect when `enable_keyword_suggestions` is also set — competitor-gap is a sub-step of the suggestions pipeline, so it is subject to the same `rank_targets` scoping described above. Costs extra page fetches and, if `enable_rank_check` is off, may also cost CSE quota.
- `target_keywords` (default `null`): when provided, overrides automatic keyword extraction — ranking/suggestions are computed for these keywords instead.
- `rank_targets` (default `null`): the pages to rank-check, each as `{ "url": string, "keywords": string[] }`. `enable_rank_check` checks rank only for the keywords nominated against a page whose (normalized) URL was actually crawled; pages not listed here are never rank-checked no matter how `enable_rank_check` is set. A page is matched by comparing normalized URLs (scheme, `www.`, query string, fragment, and trailing slash all stripped), so `"example.com/services"` matches a crawled `"https://www.example.com/services/?utm=x"`.

> Note: the dashboard's Advanced Overrides section exposes rank tracking (`rank_targets`, which in turn implies `enable_rank_check` and `enable_keyword_suggestions`) directly in the UI. `enable_competitor_gap` remains settable only via direct API calls.

#### Success Response (202-style)
`POST /api/audit` returns `{ "status": "started", "session_id": "sess_..." }`
immediately; the audit runs in the background and progress arrives over the
WebSocket. Read the finished audit with the endpoints below, using that
`session_id`.

Historically this section described the full `AuditResponse` returned by
`GET /api/audit/latest`. That response is now a summary — see **Breaking
changes** below. The audit still contains `executive_summary`, `pages`, `recommendations`, `duplicates`, `broken_links`, `site_wide_analysis`, `elapsed_seconds`, `note`, and `rank_targets` (an echo of the request's `rank_targets`, `[]` if none were supplied). Each item in `pages` now optionally carries a `keyword_analysis` object:
```json
{
  "top_keywords": [{ "phrase": "espresso machine", "score": 5.0, "found_in": ["title", "h1"] }],
  "rankings": [{ "keyword": "espresso machine", "position": 3, "status": "ranked", "note": null, "checked_at": "2026-08-11T00:00:00+00:00" }],
  "suggested_keywords": [{ "phrase": "espresso machine reviews", "reason": "related search", "competitor_examples": null, "replaces": "espresso machine" }]
}
```
`rankings` is empty unless `enable_rank_check` was set **and** the page was nominated in `rank_targets`. Each ranking's `status` is one of `"ranked"`, `"not_ranked"`, or `"skipped"` — `"skipped"` means the check never ran (no credentials, daily quota exhausted, or a request error) and must never be read as the page ranking badly. `suggested_keywords` is empty unless `enable_keyword_suggestions` was set, subject to the `rank_targets` scoping described above (competitor-gap entries only appear if `enable_competitor_gap` was also set); a suggestion's `replaces` names the underperforming (`"not_ranked"`) keyword it was seeded from, or is absent/`null` when suggestions were seeded from extracted keywords instead (no rank data for that page).

---

### 2. Service Health Check
- **URL**: `/api/health`
- **Method**: `GET`

#### Success Response (200 OK)
```json
{
  "status": "ok",
  "service": "seo-auditor-backend",
  "timestamp": "2026-07-23T19:30:00.000Z"
}
```

---

## Breaking changes (5000-page release)

The read endpoints previously returned an entire audit in one response and kept
it in a process-local dict. At 5000 pages that response is tens of megabytes,
more than the dashboard can store or parse, and a restart lost every session.
Audits are now stored per session in SQLite and read a page at a time.

| Endpoint | Before | Now |
| --- | --- | --- |
| `GET /api/audit/latest` | The whole audit | Summary only; no `pages`, `page_issues_detail` or `architecture`. Adds `page_count` |
| `GET /api/pages` | Bare array of every row | `{items, total, offset, limit}` |
| `GET /api/issues` | Bare array of site-wide recommendations | `{items, total, offset, limit}` of **per-page** issues. Site-wide recommendations stay on `/api/audit/latest` |
| `GET /api/architecture` | A node per page | Path-clustered nodes; `?expand=` for one cluster's pages |
| `GET /api/internal-links` | `broken_links` as a bare array | `broken_links` as a paginated envelope |
| `GET /api/duplicates` | — | New |

Any direct API consumer must update. Both apps in this repository deploy
together, so the dashboard changes with them.

---

### 3. Audit Summary
- **URL**: `/api/audit/latest?session_id=...`
- **Method**: `GET`

Returns `executive_summary`, `site_wide_analysis`, `recommendations`,
`issue_frequency`, `duplicates`, `redirects`, `rank_targets`, `psi_metrics`,
`elapsed_seconds`, `page_count`, and three flags worth reading:

- `near_duplicate_mode` — `"exact"` or `"minhash"`. Above 500 pages, duplicate
  similarity is a **MinHash estimate** rather than an exact Jaccard, so a pair
  sitting on the 0.85 threshold may fall either side of it. This field says
  which produced the numbers you are looking at.
- `degraded` — the process pool could not run and the checks fell back to
  running in-process. The audit is complete; it merely took longer.
- `partial` — the crawl was stopped before it finished. The summary covers only
  the pages reached.

**404** while the crawl is still running, which is what the dashboard polls for.

---

### 4. Pages
- **URL**: `/api/pages?session_id=...`
- **Method**: `GET`

| Parameter | Default | Notes |
| --- | --- | --- |
| `offset` | `0` | |
| `limit` | `50` | Max `500`; above that is a 422 |
| `sort` | `depth` | One of `url`, `depth`, `status`, `word_count`, `response_time_ms`, `internal_links_count`, `issue_count`. Anything else is a 422, not silently ignored |
| `order` | `asc` | `asc` or `desc` |
| `filter` | — | Substring matched against the URL only |
| `status` | — | Exact HTTP status code |
| `has_issues` | — | `true` or `false` |

`total` counts every row matching the filter, not the returned page, so a client
can size its pagination.

---

### 5. Issues
- **URL**: `/api/issues?session_id=...`
- **Method**: `GET`
- Same envelope. `severity` (`critical`/`warning`/`info`) and `code` filter it.

---

### 6. Duplicates
- **URL**: `/api/duplicates?session_id=...`
- **Method**: `GET`
- Paginated near-duplicate pairs, plus `mode` — the same `exact`/`minhash`
  distinction described above, carried alongside the numbers it qualifies.

---

### 7. Site Architecture
- **URL**: `/api/architecture?session_id=...`
- **Method**: `GET`

Returns `{clustered: true, nodes, links}`: pages grouped by first path segment,
sized by page count, with edges aggregated between clusters. A node per page is
~5000 nodes and a few hundred thousand edges at the Full Site Crawl preset,
which no browser draws interactively.

`?expand=/blog` returns `{clustered: false, expanded, nodes, links}` — that one
cluster's pages and the edges among them. Edges leaving the cluster are omitted,
since the other clusters are still collapsed and have no node to land on.

Clustering rules: the start URL is always its own `home` node; a URL with no
path segment joins it; a cluster standing for a single page is returned as that
page (`is_page: true`); beyond 60 clusters the tail collapses into one `other`.

---

## Projects & audit history (central database)

Every finished audit is stored in the central database under a project, one
project per domain (`www.` and ports ignored). Audit results carry `audit_id`,
`project_id` and `persisted` (`false` if the database was unavailable; the
audit itself still succeeds). Endpoints below answer **503** when the central
database is unavailable.

### `GET /api/projects`

```json
{"items": [{"id": 1, "name": "example.com", "domain": "example.com",
            "audit_schedule": "weekly", "audit_options": {"max_pages": 50},
            "audit_count": 2,
            "latest_audit": {"id": 7, "finished_at": "2026-10-25T10:00:00+00:00", "health_score": 72.5}}]}
```

### `POST /api/projects` → 201, or 409 if the domain already has a project

```json
{"domain": "https://www.example.com/", "name": "My site",
 "audit_schedule": "daily", "audit_options": {"max_pages": 100, "max_depth": 3, "ignore_robots": false}}
```

`audit_schedule` is `null`, `"daily"` or `"weekly"` (anything else is 422).

### `PATCH /api/projects/{id}`

Any of `name`, `audit_schedule`, `audit_options`.

### `GET /api/projects/{id}/audits?offset=0&limit=20`

Newest first: `{"items": [{"id", "session_id", "status", "trigger", "start_url",
"started_at", "finished_at", "page_count", "health_score"}], "total", "offset", "limit"}`.
`trigger` is `manual`, `scheduled` or `import`.

### `GET /api/audits/{id}/diff?against={old_id}&limit=500`

`against` defaults to the previous audit of the same project (404 if none).
Audits of different projects → 400.

```json
{"old_audit_id": 6, "new_audit_id": 7, "health_score_change": -4.5,
 "issues": {"new": [{"url": "/b", "code": "STATUS_404", "severity": "warning", "message": "..."}],
            "fixed": [], "new_count": 1, "fixed_count": 0, "persisting_count": 12},
 "pages": {"added": ["/fresh"], "removed": ["/gone"],
           "status_changed": [{"url": "/b", "old_status": 200, "new_status": 404}],
           "added_count": 1, "removed_count": 1, "status_changed_count": 1}}
```

Lists are truncated at `limit`; the `*_count` fields are always exact.

### `POST /api/cron/run`

Runs audits for projects whose schedule is due. Requires
`Authorization: Bearer <CRON_SECRET>`; **404** when `CRON_SECRET` is unset,
**401** on a wrong token, otherwise **202** `{"status": "accepted"}` with the
audits running in the background. A project is claimed before its audit starts,
so this and the in-process scheduler never start the same audit twice.

---

## Rank tracking

Keywords belong to a project and are checked daily (once a project has a
keyword, its `rank_schedule` becomes `daily`). Each check stores my position
(the best result on the project's domain or a subdomain), the URL that ranks,
each competitor's position, and the top results. Endpoints answer **503**
when the central database is unavailable.

### `POST /api/projects/{id}/keywords`

```json
{"keywords": [{"phrase": "espresso machine"},
              {"phrase": "espresso machine", "country": "GB", "device": "mobile", "language": "en"}]}
```

→ `{"created": 2, "skipped": 0}`. Phrases are lowercased and whitespace-collapsed;
an existing (phrase, country, device) is skipped. `country` defaults to `US`,
`device` to `desktop` (`desktop` | `mobile`).

### `GET /api/projects/{id}/keywords`

```json
{"items": [{"id": 1, "phrase": "espresso machine", "country": "US", "device": "desktop",
            "language": "en", "enabled": true, "change": -5,
            "latest": {"position": 9, "ranking_url": "https://example.com/e", "status": "ranked",
                       "checked_at": "2026-10-25T10:00:00+00:00", "note": null,
                       "competitor_positions": {"rival.org": 3}}}]}
```

`change` is previous minus latest position: positive means it improved.

### `PATCH /api/keywords/{id}` `{"enabled": false}` · `DELETE /api/keywords/{id}` → 204

### `GET /api/keywords/{id}/history?days=90`

Checks oldest first, each shaped like `latest` above.

### Competitors

- `GET /api/projects/{id}/competitors`
- `POST /api/projects/{id}/competitors` `{"domain": "rival.org"}` → 201, or 409 if already added
- `DELETE /api/projects/{id}/competitors/{competitor_id}` → 204

### `POST /api/projects/{id}/rank-checks/run?dry_run=true`

`dry_run` defaults to **true**: returns a preview from made-up results, which is
never stored and never alerts:
`{"dry_run": true, "results": [{"phrase", "position", "ranking_url", "competitor_positions"}]}`.
`dry_run=false` runs the project now with the live provider in the background
(`{"dry_run": false, "status": "accepted"}`), or **409** if no live provider is
configured.

### Alert settings

Via `PATCH /api/projects/{id}`:
`{"rank_schedule": "daily", "alert_settings": {"drop_threshold": 3, "top10_alerts": true, "gain_threshold": null}}`.
Alerts fire for a drop of at least `drop_threshold` positions, leaving the top 10,
no longer ranking, and (if set) gains of at least `gain_threshold`. One digest per
project run goes to each configured channel (Slack, email); the same change is
never sent twice.

`POST /api/cron/run` now runs due audits **and** due rank checks.

---

## Keywords Explorer & Content Gap

Metrics come from DataForSEO (Google Ads search volume, Labs keyword
difficulty, Labs ranked keywords) once live; until then every response is a
**dry run** of made-up data, flagged by `"dry_run": true` (and a first CSV line
`# DRY RUN — made-up data`). Answers are cached (metrics and difficulty for 30
days, ranked keywords for 7), so repeats cost nothing. Hitting
`DATAFORSEO_LABS_DAILY_CAP` returns **429**; a DataForSEO error returns **502**
with DataForSEO's own status message.

### `POST /api/keywords/explore`

```json
{"seed": "espresso machine", "country": "US", "language": "en", "cluster": false}
```

```json
{"seed": "espresso machine", "country": "US", "language": "en", "dry_run": false,
 "keywords": [{"keyword": "espresso machine", "source": "seed", "search_volume": 74000,
               "cpc": 1.2, "competition": "HIGH", "difficulty": 62,
               "traffic_potential_estimate": 20720}],
 "clusters": [["espresso machine", "best espresso machine"]], "notes": []}
```

- Ideas: Google Autocomplete plus People Also Ask from one SERP call, up to 50.
  `source` is `seed`, `autocomplete` or `people_also_ask`.
- `traffic_potential_estimate` = search volume × 0.28, the typical click-through
  rate of the #1 result. **An estimate, not measured traffic.**
- `cluster: true` groups up to 20 keywords whose top-10 results share at least
  3 URLs. It costs one SERP call per keyword, under `SERP_DAILY_CAP`.

### `GET /api/keywords/explore.csv?seed=…&country=US&language=en`

Columns: `keyword, source, search_volume, cpc, competition, difficulty, traffic_potential_estimate`.

### `POST /api/projects/{id}/content-gap`

```json
{"competitors": ["rival.org", "other.net"], "country": "US", "language": "en", "limit": 500}
```

`competitors` defaults to the project's competitor list (1–5, else 400).
A keyword is a gap when a competitor ranks it in the **top 20** and the project
domain does not rank it in the **top 100**.

```json
{"my_domain": "example.com", "competitors": ["rival.org"], "dry_run": false, "total_gaps": 1,
 "rows": [{"keyword": "milk frother", "search_volume": 4000, "difficulty": 20, "opportunity": 3200.0,
           "best_competitor_position": 4,
           "competitors": {"rival.org": {"position": 4, "url": "https://rival.org/m"}}}]}
```

- `opportunity` = volume × (100 − difficulty) / 100, with unknown difficulty
  counted as 50. Rows are sorted by it.
- `limit` is keywords fetched per domain (max 1000). If you rank for more
  keywords than `limit`, some of your positions are not seen and a gap can be
  over-reported. Raise `limit` to tighten it.

### `GET /api/projects/{id}/content-gap.csv?competitor=rival.org&competitor=other.net`

Columns: `keyword, search_volume, difficulty, opportunity, best_competitor_position`,
then `<competitor> position` and `<competitor> url` per competitor.

---

## Core Web Vitals

Each audit measures the start URL plus the top pages by internal PageRank (up
to `PSI_MAX_PAGES`, mobile). It uses PageSpeed Insights when `PSI_API_KEY` is
set, and local Lighthouse when `LIGHTHOUSE_ENABLED=true`. Page-level field data
(real Chrome users) is used for the rating when Google has it, otherwise lab
data. Lab data has no INP, so TBT stands in for it. Poor values add
`CWV_*_POOR` warnings, and values that need improvement add
`CWV_*_NEEDS_IMPROVEMENT` info issues, so they count in the health score.

The audit result (and `GET /api/audit/latest`) carries:
- `web_vitals`: one object per measured page
- `web_vitals_status`: `measured`, `not_configured` or `disabled`
- `psi_metrics`: PSI-measured pages only, for older readers

`POST /api/audit` accepts `"enable_web_vitals": false` to skip measuring.

### `GET /api/audits/{id}/vitals`

```json
{"audit_id": 12, "status": "measured", "items": [{"url": "https://a.com/", "strategy": "mobile",
 "source": "psi", "data_kind": "field", "performance_score": 71, "lcp_ms": 2300, "inp_ms": 180,
 "cls": 0.05, "fcp_ms": 1200, "ttfb_ms": 600, "tbt_ms": 350, "rating": "good", "error": null,
 "measured_at": "2026-10-25T18:00:00+00:00",
 "metric_ratings": {"lcp_ms": "good", "inp_ms": "good", "cls": "good", "tbt_ms": "needs_improvement"}}]}
```

A page that couldn't be measured has `source: "not_measured"` and the reason
in `error`, e.g. `"psi: daily cap of 50 psi calls reached"`.

### `GET /api/projects/{id}/vitals/trend?limit=30`

The homepage per audit, oldest first. Audits whose homepage wasn't measured
are skipped.

```json
{"url": "https://a.com/", "points": [{"audit_id": 12, "finished_at": "2026-10-25T18:00:00+00:00",
 "url": "https://a.com/", "source": "psi", "data_kind": "lab", "performance_score": 71,
 "lcp_ms": 4800, "inp_ms": null, "cls": 0.05, "tbt_ms": 350, "rating": "poor",
 "metric_ratings": {"lcp_ms": "poor", "inp_ms": null, "cls": "good", "tbt_ms": "needs_improvement"}}]}
```
