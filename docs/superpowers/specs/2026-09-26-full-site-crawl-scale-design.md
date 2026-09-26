# Full Site Crawl at 5000 pages — design

**Date:** 2026-09-26
**Status:** approved design, pending implementation plan

## Problem

The Full Site Crawl preset is disabled (`apps/frontend/app/page.tsx:79`, commit
551c5b9). The comment there blames quadratic near-duplicate detection, but PR #13
(commit 8d29bcd) replaced exactly that code — the docstring it quotes no longer
exists. The preset is disabled for reasons that have since moved.

What actually blocks a large crawl today:

| Blocker | Location | Effect at 5000 pages |
| --- | --- | --- |
| Per-batch synchronous barrier in the crawl loop | `app/crawler/crawler.py:281` | 10 fetches start, all 10 must finish before the next batch; one slow page idles 9 workers |
| Per-page checks run single-threaded *after* the crawl | `app/services/audit_service.py:125` | 4–8 minutes of CPU appended to the crawl, not overlapped with it |
| Every page's HTML retained for the whole audit | `app/crawler/crawler.py:60` (`PageResult.html`) | ~500 MB resident |
| Full shingle sets held for duplicate detection | `app/analysis/analysis.py:130` | 160–320 MB resident |
| Whole result assembled as one dict and returned by `/api/audit/latest` | `app/services/audit_service.py:330` | ~100 MB JSON response |
| Whole payload round-tripped through `localStorage` | `apps/frontend/lib/audit-context.tsx:56` | Hard failure: ~5 MB quota |
| One WebSocket event per internal link | `app/crawler/crawler.py:317` | Several hundred thousand messages |
| `MAX_PAGES_LIMIT = 1000` | `app/schemas/schemas.py:10` | 5000 rejected by the API |
| Architecture graph renders a node per page | `apps/frontend/components/site-architecture-graph.tsx` | ~5000 nodes / ~250k edges, unrenderable |

## Goals

- Full Site Crawl completes 5000 pages, depth 15, in about 10 minutes on the
  documented deployment shape (`VM.Standard.A1.Flex`, 2 OCPU / 12 GB).
- Resident memory stays flat as the crawl grows, rather than scaling with pages.
- The dashboard's first paint needs a payload in the hundreds of kilobytes.
- Audit history survives a redeploy.
- The duplicated engine under `apps/backend/seo_auditor/` is deleted, not mirrored.

## Non-goals

- No JavaScript rendering. The crawl stays HTTP + lxml; `POSSIBLE_CSR_ONLY`
  remains a signal, not something the crawler resolves.
- No distributed or multi-worker crawling. The single-uvicorn-worker constraint
  (`apps/backend/Dockerfile`) stands.
- No new SEO checks. This is a scale change, not a feature change.
- No change to rank-check or keyword-suggestion behaviour, including their
  quota discipline and the nominated-pages scoping.
- No touching the retired Express tree at `apps/backend/src/*.ts`, or the README
  and `docs/architecture.md` claims that the backend is Express. Both are real
  drift, both are out of scope here, and neither blocks this work.

## Decisions

Five decisions were settled before this design was written:

1. **Target scale:** 5000 pages in roughly 10 minutes.
2. **Storage:** SQLite per session, written during the crawl.
3. **Concurrency:** continuous thread pool for fetching, process pool for checks.
4. **Architecture graph:** cluster by URL path segment with click-to-expand.
5. **Duplicated CLI engine:** delete it; the CLI imports `app/`.

## Architecture

The audit becomes a three-stage pipeline where all three stages run concurrently,
rather than three phases that run in sequence.

```
                  ┌──────────────────────────────────────────┐
                  │ Stage 1: fetch (32 threads)               │
  depth-ordered   │  - GET, follow redirects, retry           │
  frontier (heap) │  - extract links -> back into frontier    │
       ▲          │  - hand (url, html, headers) to stage 2   │
       └──────────┤                                           │
                  └───────────────────┬──────────────────────┘
                                      │ html (freed after)
                  ┌───────────────────▼──────────────────────┐
                  │ Stage 2: analyse (process pool, N=cpus)  │
                  │  - ~20 checks, metadata, keyword extract │
                  │  - MinHash signature                     │
                  │  - returns compact row + issues          │
                  └───────────────────┬──────────────────────┘
                                      │ rows
                  ┌───────────────────▼──────────────────────┐
                  │ Stage 3: persist (1 writer thread)        │
                  │  - batched INSERT into sessions/<id>.db   │
                  └──────────────────────────────────────────┘

  after the frontier drains: site-wide analysis, LSH duplicate pass,
  recommendations, summary row
```

### Stage 1 — fetch

`app/crawler/crawler.py`. One long-lived `ThreadPoolExecutor` of 32 workers
(`CRAWL_CONCURRENCY`, default 32) replaces the per-batch pool. The frontier
becomes a `heapq` keyed on `(depth, sequence)`, so BFS discovery order is
preserved exactly — pages are still reached in click-depth order, workers simply
never idle waiting for a batch to drain.

In-flight work is bounded at `2 x concurrency` submissions so the frontier cannot
run ahead of memory. `max_pages` admission is checked under a lock before each
submit, since 32 concurrent fetches would otherwise overshoot the cap.

Unchanged: robots.txt handling, sitemap discovery, redirect-chain recording,
retries with backoff, URL normalization and dedup, `is_paused` / `is_stopped`,
and the `include_external_link_check` sampling.

**Event throttling.** `page_crawled`, `broken_link`, `redirect` and `timeout`
events stay per-event. `internal_link` and `external_link` events are replaced by
a counter flushed at most once per second as `link_progress`
(`{internal_total, external_total}`). The frontend's activity feed and
`link-analysis-panel` consume the aggregate. Rationale: at 5000 pages the
per-link events are several hundred thousand messages, which stalls the browser
before the crawl finishes.

### Stage 2 — analyse

New module `app/services/page_pipeline.py`, one public function:

```python
def analyze_page(payload: PagePayload) -> PageAnalysis
```

`PagePayload` carries only picklable primitives (url, final_url, status, headers
dict, html str, depth, referrers). `PageAnalysis` returns the compact row, the
issue list, the keyword-extraction result, the MinHash signature, and the
outbound link lists.

The function is pure — no config, no network, no module-level mutable state — so
it runs in a `ProcessPoolExecutor` sized to `os.cpu_count()`. It is fed as each
page lands in stage 1, so its CPU cost overlaps network waiting.

This is a move, not a rewrite: the body is the per-page half of
`_build_audit_result` (`audit_service.py:125-300`), which currently inlines
~20 check calls plus a large metadata extraction block. `audit_service` keeps
orchestration and loses the per-page work, which should take it from 375 lines to
roughly 200.

Each page's HTML is released as soon as its `PageAnalysis` returns.
`PageResult.html` becomes transient: the crawler no longer retains it after
handing it to stage 2. This is what holds memory flat.

**Stays in the main process:** rank checks and keyword suggestions. Both are
network-bound, quota-limited, and already scoped to nominated pages
(`audit_service.py:255`). They run after the frontier drains, over the nominated
subset read back from SQLite. Their behaviour, including the `event_callback`
nulling for competitor-gap fetches, is unchanged.

### Stage 3 — persist

One writer thread consumes `PageAnalysis` objects and batches inserts every 50
pages. SQLite permits a single writer; WAL mode lets the read endpoints serve
during the crawl.

## Data model

`sessions/<session_id>.db`, one file per audit, created at audit start:

```sql
CREATE TABLE pages (
  url TEXT PRIMARY KEY, final_url TEXT, depth INTEGER, status INTEGER,
  response_time_ms REAL, content_type TEXT, title TEXT, meta_description TEXT,
  h1 TEXT, canonical TEXT, word_count INTEGER, char_count INTEGER,
  internal_links_count INTEGER, external_links_count INTEGER,
  images_count INTEGER, missing_alt_count INTEGER,
  meta_robots TEXT, lang TEXT, error TEXT,
  meta_json TEXT            -- open_graph, twitter, heading_hierarchy,
);                          -- structured_data, security_headers, performance,
                            -- keyword_analysis
CREATE TABLE issues (url TEXT, severity TEXT, code TEXT, message TEXT);
CREATE TABLE links (src TEXT, dst TEXT, internal INTEGER);
CREATE TABLE signatures (url TEXT PRIMARY KEY, minhash BLOB);
CREATE TABLE summary (json TEXT);   -- single row, written at the end

CREATE INDEX idx_issues_url ON issues(url);
CREATE INDEX idx_issues_code ON issues(code);
CREATE INDEX idx_links_src ON links(src);
CREATE INDEX idx_pages_depth ON pages(depth);
```

`SessionStore` (`app/models/session_model.py`) stops holding audit results and
becomes an index over the session directory: list, get summary, delete, and
compare two summaries for the historical panel. Retention drops from 50
in-memory results to the newest 20 database files, oldest deleted on write.
History now survives a redeploy, which it does not today.

`SESSION_DIR` is a new config value (`app/config/config.py`), default
`./sessions`, and gets a named Docker volume in `deploy/oracle/docker-compose.yml`
so it outlives a container rebuild.

## Duplicate detection — MinHash + LSH above 500 pages

Two paths, selected by crawl size, with the chosen mode recorded in the summary
as `near_duplicate_mode`.

**At or below 500 pages: the current exact path.** `near_duplicate_content`
(`analysis.py:105`) already prunes with lossless size and prefix filters and is
fast at this size. Exact results are strictly better when affordable, and the
existing tests pin this behaviour.

**Above 500 pages: MinHash signatures with LSH banding.**

- Each page reduces to 128 32-bit minima over its 5-word shingles: 512 bytes,
  against roughly 50 KB for a full shingle set. This is what removes the
  160–320 MB.
- The signature is computed in stage 2, inside the process pool, from HTML the
  worker already holds — so it costs no extra parse and no extra memory in the
  parent.
- Candidate pairs come from 16 bands of 8 rows: two pages are candidates if any
  band hashes identically. Similarity is then estimated as the fraction of
  matching signature positions.
- `threshold` stays 0.85, matching the exact path.

**This path is approximate, and that is a real behaviour change.** At 128
permutations the standard error on an estimated Jaccard is about 0.04, so a pair
sitting at the threshold may fall either side of it. Two consequences, both
accepted deliberately:

- A borderline duplicate pair may be reported on a 5000-page crawl and not on a
  600-page crawl of the same site, or the reverse.
- The reported `similarity` is an estimate. The API response labels it as such
  via `near_duplicate_mode: "minhash"`, and the duplicates panel notes it.

The alternative — keeping full shingle sets and accepting the memory — does not
fit the 12 GB shape alongside 5000 pages of crawl state. The alternative of
re-fetching candidate pages to verify exactly would add thousands of HTTP
requests to confirm a number nobody acts on to three decimal places.

## PageRank

`build_link_graph_stats` (`analysis.py:47`) computes PageRank via networkx behind
a `try: import` guard. networkx was declared in `seo_auditor/requirements.txt`
but **not** in `apps/backend/requirements.txt`, which is the file the Dockerfile
installs — so in production the import failed silently and
`pagerank_available: false` shipped on every audit.

**Already fixed**, ahead of this work, on branch
`fix/pagerank-declaration-and-check-isolation` (commit `f4ea190`): the
declaration is added and guarded by a test that scans `app/` for third-party
imports and asserts each is declared. Nothing further is needed here. At 5000
nodes and ~250k edges, `nx.pagerank` runs in a few seconds and reads its graph
from the `links` table.

## API contract

| Endpoint | Change |
| --- | --- |
| `GET /api/audit/latest` | **Breaking.** Summary only: executive summary, site-wide **counts** (not full URL lists), recommendations, issue frequency, `elapsed_seconds`, `rank_targets`, `near_duplicate_mode`. Target under 300 KB at 5000 pages |
| `GET /api/pages` | **Breaking.** Gains `offset`, `limit` (default 50, max 500), `sort`, `filter`; returns `{items, total, offset, limit}` instead of a bare array |
| `GET /api/issues` | **Breaking.** Same pagination envelope; gains `severity` and `code` filters |

To leave no room for interpretation, `/api/pages` accepts exactly these:
`sort` is one of `url`, `depth`, `status`, `word_count`, `response_time_ms`,
`internal_links_count` (default `depth`), with `order` of `asc` or `desc`
(default `asc`); `filter` is a substring matched against `url` only; `status` is
an optional exact status code; `has_issues` is an optional boolean. Anything else
is a 422 from Pydantic, not a silently ignored parameter.
| `GET /api/architecture` | **Breaking.** Returns path-clustered nodes by default; `?expand=<segment>` returns one cluster's pages and their edges |
| `GET /api/duplicates` | **New.** Paginated exact and near-duplicate pairs, moved out of the main payload |
| `GET /api/internal-links` | Site-wide stats keep their shape; `broken_links` paginates |
| `GET /api/page/{id}` | Unchanged shape; reads one row by primary key instead of scanning a list |
| `GET /api/export/{fmt}` | Unchanged shape. Streams from SQLite; the dual-name import hack at `routes.py:205` disappears with the CLI tree |

Both apps deploy together, so the breaking shapes are acceptable. They are
breaking for any direct API consumer, and `docs/api.md` must say so.

`MAX_PAGES_LIMIT` (`schemas.py:10`) rises from 1000 to 5000 and becomes
configurable via `MAX_PAGES_LIMIT` env, because the 1 GB `E2.1.Micro` shape
documented as an alternative in `docs/deployment-oracle.md:51` cannot hold a
5000-page crawl. The frontend slider cap (PR #15) rises with it.

## Frontend

**`lib/audit-context.tsx`.** Stores only `{sessionId, summary}` in localStorage —
a few kilobytes — and never the page rows. Every read and write is wrapped in
try/catch, since a quota or private-mode failure must not break the dashboard.
This is the change that makes a large audit renderable at all.

**Per-panel fetching.** Panels fetch their own slice on mount rather than
receiving it through context:

- `pages-table`: server-side pagination, sorting, filtering.
- `issue-center`: paginated, filtered by severity and code.
- `duplicates-panel`: paginated, shows the estimate note when
  `near_duplicate_mode === "minhash"`.
- `orphan-pages-panel`, `dead-end-pages-panel`, `broken-links-table`: paginated.
- Panels whose data is already aggregate (health gauge, score breakdown, issue
  chart, recommendations) keep reading the summary from context.

**`site-architecture-graph`.** Default view groups pages by first path segment
into cluster nodes sized by page count, with edges aggregated between clusters.
Clicking a cluster expands it into its pages via `?expand=`; other clusters stay
collapsed.

Clustering rules, stated precisely because the edge cases are where this gets
ambiguous: the start URL is always its own node labelled `home`, never folded
into a cluster. A page whose path has no segment (`/`, or only a query string)
joins `home`. Everything else clusters on its first path segment. A cluster
holding a single page renders as that page directly rather than a cluster of one.
If clustering yields more than 60 nodes, the largest 60 render and the remainder
collapse into one `other` node. A flat site, where every page sits at the root
and clustering therefore produces one cluster, falls back to depth-limited
rendering capped at 500 nodes with a note explaining the cap.

**`lib/activity-feed.ts`.** Gains handling for the aggregated `link_progress`
event and drops the per-link `internal_link` / `external_link` cases. Its test
(`lib/__tests__/activity-feed.test.ts`) moves with it.

**`app/page.tsx`.** The `full` preset loses `disabled` and `disabledReason`, and
its now-inaccurate comment. The Enterprise Warning text — which says 5000 pages
while the cap has been 1000 since PR #15 — is corrected to match the real cap.

## Deleting the duplicated engine

`apps/backend/seo_auditor/seo_auditor/` is a second copy of the engine.
Measured divergence today: `analysis.py`, `checks.py` and `ai_suggestions.py` are
byte-identical; `crawler.py` differs by 46 lines (the CLI copy lacks the live
event callbacks and pause/stop, and has one extra frontier cap);
`report.py` differs by 121 lines (the CLI copy holds the five export writers
`/api/export/{fmt}` imports at request time); the rest differ only in import
style. `tests/test_cli_tree_parity.py` exists solely to stop these drifting.

`app/` becomes the single source:

1. The five export writers (`export_json`, `export_csv`, `export_excel`,
   `export_pdf_summary`, `export_html_report`) move from the CLI `report.py` into
   `app/utils/report.py`. `routes.py` imports them directly, deleting the
   dual-name `ModuleNotFoundError` fallback and its comment.
2. `cli.py` moves to `app/cli.py` and imports from `app.*`. The unified crawler
   takes `event_callback=None`, which is how the CLI already calls it; the CLI's
   extra `len(self.queued) < self.max_pages * 3` frontier cap becomes the
   bounded-frontier behaviour for both.
3. `apps/backend/seo_auditor/` is deleted, along with its `setup.py`,
   `requirements.txt` and `README.md`. The Dockerfile drops `COPY seo_auditor`.
4. `test_cli_tree_parity.py` is deleted, but **its assertions are kept** —
   each one encodes a real fixed bug. They move into
   `test_keyword_suggestions.py` and `test_rank_checker.py` against the single
   module, dropping only the `cli` parametrisation.
5. Invocation changes from `python -m seo_auditor.cli` to `python -m app.cli`.
   `docs/folder-structure.md`, `docs/architecture.md` and the CLI README's usage
   examples are updated.

## Error handling

- **A page whose checks raise** gets a row with `error` set and the audit
  continues. **Already fixed** for the current single-process loop on branch
  `fix/pagerank-declaration-and-check-isolation` (commit `9884352`): the page is
  recorded with a critical `AUDIT_ERROR` issue and the rest are still audited.
  Stage 2 must carry that boundary across the process-pool hand-off, where the
  exception arrives as a `future.result()` raise rather than in-line.
- **A dead process-pool worker** (`BrokenProcessPool`) is retried once for that
  page, then recorded as an error row. If the pool dies repeatedly, the audit
  falls back to in-process checks and records `degraded: true` in the summary —
  slow beats failed.
- **A SQLite write failure** fails the audit with a clear status rather than
  producing a silently partial report.
- **Memory backpressure:** if bytes of HTML in flight exceed `CRAWL_HTML_BUDGET`
  (default 256 MB), stage 1 stops submitting until stage 2 drains.
- **Stop mid-crawl** finalises whatever is in the database and writes a summary
  marked `partial: true`, so a stopped 5000-page crawl still produces a
  dashboard.

## Testing

Unit and integration, with pytest:

- **LSH recall:** on a fixture corpus with known pairs, every pair the exact path
  reports at similarity ≥ 0.90 is also reported by MinHash. Pairs between 0.85
  and 0.90 are asserted within the documented error band, not exactly.
- **Signature size:** a signature is 512 bytes, so memory claims are pinned by a
  test rather than by a comment.
- **BFS order preserved:** against a fixture link graph, the new frontier visits
  pages in the same depth order the current implementation does.
- **`max_pages` never exceeded** with 32 workers in flight — the overshoot this
  design has to prevent.
- **HTML released:** after a page's analysis returns, no reference to its HTML is
  reachable from the crawler (weakref assertion).
- **Pagination boundaries:** `offset` past the end, `limit` over the max, and a
  total that matches an unpaginated count.
- **Partial audit:** stop mid-crawl yields a readable summary with
  `partial: true`.
- **Degraded path:** with the process pool forced to fail, the audit completes
  in-process and reports `degraded: true`.
- **All 121 existing backend tests stay green** (17 files, as of commit
  `9884352`), and the parity assertions survive their move.

Separately, a manual performance harness (not in CI): a synthetic local site of
1000 pages, asserting wall-clock and peak-RSS ceilings. CI cannot be trusted to
reproduce timing, but a regression here is the whole point of the work, so the
harness is committed and documented.

## Performance budget

For 5000 pages on 2 OCPU / 12 GB, with crawl and checks overlapped:

Stages 1–3 run concurrently, so the wall clock is roughly the slowest of them
plus the final analysis — not their sum:

| Stage | Budget | Arithmetic |
| --- | --- | --- |
| Fetch, 32 threads | ~1.5–3 min | 5000 x 0.45 s / 32 = 70 s ideal; the range allows for redirect chains, retries and tail latency |
| Checks, 2 processes | ~3.5 min | 5000 x 80 ms / 2 = 200 s |
| Site-wide analysis + PageRank + LSH pass | ~1 min | runs after the frontier drains, not overlapped |
| **Total wall clock** | **~5–7 min** | max(fetch, checks) + final analysis, against a 10 min target |
| Peak RSS | under 1.5 GB | |
| `/api/audit/latest` | under 300 KB | |

The checks stage is therefore the critical path, not the network.

This is tight, and the honest risk is the CPU stage: with only 2 OCPUs the
process pool gives at best 2x, so per-page check cost matters. If the harness
shows the budget missed, the lever is reducing per-page work (the metadata
extraction block in stage 2 walks the parsed tree several times and can be
folded into one pass), not more processes.

On a 1 GB `E2.1.Micro` this configuration will not fit, which is why
`MAX_PAGES_LIMIT` is configurable and `docs/deployment-oracle.md` must state the
shape a 5000-page crawl assumes.

## Risks

- **Approximate duplicates above 500 pages.** Mitigated by keeping the exact path
  for smaller crawls and labelling the mode in the response.
- **Two behaviours for one feature** (exact and MinHash) is a maintenance cost
  accepted to avoid regressing existing exact results.
- **Breaking API shapes** for any direct consumer of `/api/pages`,
  `/api/issues`, `/api/architecture` and `/api/audit/latest`.
- **A crawl this large is now possible against a third party's site.** 32
  concurrent connections for several minutes is more load than the current 10.
  `CRAWL_CONCURRENCY` and the existing per-request `delay` stay configurable, and
  robots.txt is still honoured by default.

## Open items

None blocking. The performance budget is the number to re-check after
implementation, against the committed harness rather than by inspection.
