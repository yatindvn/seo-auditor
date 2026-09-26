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
