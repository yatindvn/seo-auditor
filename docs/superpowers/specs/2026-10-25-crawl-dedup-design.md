# Crawl Dedup & Crawl Improvements (Part A) — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Follow-up:** Part B, reusing unchanged pages across audits via conditional
requests, gets its own spec. It depends on the stable page identity built here.

## Problem

Within one audit the crawler already never fetches the *same URL string* twice
(`visited` / `queued` in `crawler.py`). But the same page reached through a
different spelling is crawled, analysed, and stored again:

| Case | Example | Today |
| --- | --- | --- |
| Tracking / reordered params | `/shoes` vs `/shoes?utm_source=fb` | 2 fetches, 2 analyses |
| Redirect target also linked | `/old` → `/new`, and `/new` linked directly | `/new` fetched twice |
| Scheme / host variants | `http://site.com/x` vs `https://www.site.com/x` | each crawled, redirects re-followed |
| Same body, different path | `/about` vs `/about/`, both 200 | 2 analyses |

Each repeat costs a fetch, takes a slot from the 5000-page cap, and inflates the
duplicate-content report with pairs that are one page.

Two further defects found while reading the crawler:

1. `sitemap_urls` is populated by `_load_sitemaps` and never read. Pages listed
   only in the sitemap — often exactly the orphans an SEO audit exists to find —
   are never crawled.
2. The politeness `delay` sleeps inside `_handle_result`, which runs on the main
   loop, so it stalls admission for every worker rather than pacing one.

## Requirements

1. A page is fetched-and-analysed at most once per audit, whichever spelling
   reached it.
2. Never merge two pages that can actually differ. Every rule is either lossless
   (cannot change what the server serves) or proven by the server (a redirect)
   or by the bytes (identical body).
3. Skipped URLs remain visible in the results with the reason, because
   "this URL is a duplicate of that one" is itself an SEO finding.
4. `max_pages` counts unique pages: a 5000-page crawl covers 5000 different
   pages.
5. Pages listed only in the sitemap are crawled.

## Design

Three layers, cheapest first.

### Layer 1 — safe normalisation (before queueing)

`normalize_url` in `crawler.py` additionally:

- drops known tracking params: `utm_*`, `gclid`, `fbclid`, `msclkid`, `dclid`,
  `yclid`, `mc_cid`, `mc_eid`, `_ga`, `_gl`, `ref_src`;
- sorts the remaining query params (stable, preserving repeated keys);
- drops default ports (`:80` on http, `:443` on https);
- keeps its existing behaviour: lowercase scheme and host, strip fragment,
  collapse `//`, empty path → `/`.

It does **not** touch trailing slashes, path case, `index.html`, `www`, or the
scheme — those can serve different content and are left to layers 2 and 3.

`page_pipeline._extract_links` already calls `normalize_url`, so link edges
stored in the session DB use the same keys automatically.

### Layer 2 — redirect aliases (after fetch)

The crawler gains `aliases: Dict[str, str]` mapping a URL to the URL whose
result represents it, and `claimed: Dict[str, str]` mapping each normalised
*final* URL to the requested URL that first reached it.

In `_handle_result` (main thread, so no lock is needed):

- Normalise `result.final_url`. If it is already in `claimed` by another URL,
  this result is an alias: set `result.alias_of = claimed[final]`, record
  `aliases[url] = claimed[final]`, and do not hand it to `on_page` for analysis.
- Otherwise claim it: `claimed[final] = url`, and if `final != url`, add `final`
  to `queued` and `aliases[final] = url` so a later link to the target is never
  fetched.
- Before pushing a discovered link, resolve it through `aliases`; already
  known targets are skipped.

Two concurrent fetches that land on the same final URL resolve deterministically:
whichever completes first claims it, the other becomes its alias.

### Layer 3 — identical-content dedup (after fetch)

For 200 `text/html` responses the crawler computes `body_hash =
sha256(html bytes)` and keeps `body_owner: Dict[str, str]`. If the hash is
already owned, set `result.duplicate_of = body_owner[hash]` and skip analysis.

Exact bytes only. Pages differing in a CSRF token or timestamp are analysed
separately — that is the safe failure direction, and near-duplicate detection
(exact Jaccard / MinHash) still reports them.

### Cap accounting

`admitted` is incremented when a fetch is submitted, as today. When a result
turns out to be an alias or duplicate, `admitted` is decremented (under the
existing lock), so the slot goes to another unique page. A per-audit ceiling of
`2 × max_pages` total fetches stops a site made entirely of duplicates (e.g.
infinite calendar params) from running forever.

### Sitemap seeding

After the start URL, each same-domain, robots-allowed sitemap URL is pushed onto
the frontier with priority `max_depth + 1`, so link-discovered pages are always
crawled first and sitemap-only pages fill whatever cap remains.

If a link later discovers a sitemap-seeded URL, it is pushed again at its real
depth. The heap tolerates the stale entry: on pop, URLs already in `visited` (or
in flight) are skipped. The `queued` check for discovered links therefore
compares depths for sitemap-seeded URLs instead of rejecting them outright.

A page crawled from the sitemap entry gets `depth = None` and `found_via =
"sitemap"`. Depth statistics (`_depth_distribution`, `max_crawl_depth`) ignore
`None`. A sitemap-only page is analysed, but its outgoing links are not followed:
the sitemap adds the pages it lists, not a second crawl rooted at each of them.

### Delay

`time.sleep(self.delay)` moves from `_handle_result` into `_fetch`, before the
request, so each worker paces itself.

## Data flow and storage

- `PageResult` gains `alias_of`, `duplicate_of`, `found_via` (default `"link"`).
- Alias and duplicate results skip `on_page`. `audit_service` writes them
  directly as rows with no issues: status, final URL, and the new field set.
- `session_db` `pages` table gains `alias_of TEXT`, `duplicate_of TEXT`,
  `found_via TEXT`. New sessions get them from `SCHEMA`; opening an older
  session DB runs `ALTER TABLE ... ADD COLUMN` for any missing column so
  existing audit history still loads.
- Site-wide analysis: link edges whose target is an alias are resolved to the
  canonical URL before PageRank, orphan, and dead-end computation, so
  linking to `/old` counts as inbound to the page `/old` redirected to.
- `find_duplicates`' `duplicate_content` groups include each `duplicate_of`
  page with its owner, so the SEO finding is not lost.
- Summary gains `dedup: {aliases: N, duplicates: N, sitemap_only: N}`.

## Frontend

- Pages table: a badge on alias / duplicate rows ("Redirects to X",
  "Duplicate of X") and on sitemap-only rows.
- Summary: one line, "N duplicate URLs skipped".
- Shared types in `packages/shared` gain the three optional page fields and the
  `dedup` summary block.

## Error handling

- A fetch that errors (no final URL, no body) is never an alias or duplicate;
  it is recorded as today.
- Non-HTML and non-200 responses skip layer 3 (no body hash).
- Redirect loops keep today's 10-hop cap; the final URL of a looping chain is
  still claimed so the loop is fetched once.

## Testing (pytest, using the existing fake-site fixtures in `tests/`)

- `normalize_url` table: tracking params stripped, param order canonical,
  default ports dropped, trailing slash and path case preserved.
- Redirect alias, target linked later: `/a` → `/b` crawled first, then a direct
  link to `/b` — `/b` is never requested on its own and only one analysis runs.
- Redirect alias, target crawled first: `/b` crawled, then `/a` → `/b` — `/a`
  is recorded with `alias_of == "/b"` and not analysed.
- Concurrent landing: two URLs redirecting to one target produce one analysis.
- Identical body: `/x` and `/x/` both 200 with the same HTML give one analysis;
  the second has `duplicate_of`.
- Different body by one byte: both analysed.
- Cap: a site with 10 unique pages and 10 duplicate spellings, `max_pages=10`,
  crawls all 10 unique pages.
- Ceiling: a site of endless duplicates stops at `2 × max_pages` fetches.
- Sitemap-only page is crawled with `found_via == "sitemap"`; a sitemap URL also
  reachable by link gets its link depth.
- Delay: with `delay > 0`, admissions are not serialised (timing test in the
  style of `test_slow_pages_do_not_stall_the_other_workers`).
- Session DB: an old DB without the new columns opens and lists pages.
- Existing crawler, pipeline, and persistence tests keep passing.

## Out of scope

- Reuse across audits (Part B).
- Treating `rel=canonical` as a dedup signal: it is a hint the audit checks,
  not proof two URLs serve the same page.
- Trailing-slash or `www` normalisation without server evidence.
