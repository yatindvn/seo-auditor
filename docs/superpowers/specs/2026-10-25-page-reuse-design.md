# Reuse Unchanged Pages Across Audits (Part B) — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Builds on:** `2026-10-25-crawl-dedup-design.md` (Part A, branch `feat/crawl-dedup`)

## Problem

Re-auditing a site re-downloads and re-analyses every page, even when almost
none changed since the last audit. HTML analysis (parsing plus ~20 checks) is
the dominant CPU cost of a 5000-page crawl, and downloading every body is the
dominant bandwidth cost.

Nothing from a past audit can answer "has this page changed?": session files
store neither `ETag` / `Last-Modified` nor a body hash, and only the last 20
audits are retained.

## Requirements

1. On a re-audit, a page the server reports unchanged (304), or whose HTML
   hashes the same as last time, is not re-analysed.
2. Results derived from the **response** — status, redirects, security headers,
   `X-Robots-Tag`, compression, cache headers, TTFB — are always fresh. Only
   results derived from the **HTML** are reused.
3. Reused results are never wrong because the analysis code or the audit
   options changed.
4. A "Re-check every page" option bypasses reuse; entries older than 30 days
   are re-analysed regardless.
5. The cache can never fail an audit.
6. The dashboard says how many pages were reused.

## Design

### 1. Page cache — `app/models/page_cache.py` (new)

One SQLite file per site at `SESSION_DIR/page_cache/<host>.db`, where `<host>`
is the start URL's lowercased netloc with `:` replaced by `_`. It shares the
sessions volume (`/data/sessions` in `deploy/oracle/docker-compose.yml`) so it
survives redeploys, but sits in a subdirectory, outside `SessionStore`'s
`*.db` glob and its 20-audit retention.

Table `pages`, keyed by URL:

| Column | Content |
| --- | --- |
| `url` | normalised URL (Part A `normalize_url`) — primary key |
| `etag`, `last_modified` | validators from the last full 200 response |
| `body_hash` | sha256 of the HTML (same digest as Part A's layer 3) |
| `headers_json` | that response's headers |
| `html_json` | the HTML-derived analysis (below), zlib-compressed JSON |
| `signature` | MinHash signature blob, or NULL |
| `fingerprint` | analyzer fingerprint at analysis time |
| `analysed_at` | unix seconds |

`PageCache` API:

- `PageCache.open(start_url, fingerprint) -> PageCache | None` — returns None
  (and logs) on any error opening or reading the file.
- `validators() -> Dict[url, Validators]` — `etag`, `last_modified`,
  `body_hash`, `headers`, for **usable** entries only, loaded once.
- `get_html_part(url) -> HtmlAnalysis | None`
- `put(url, validators, html_part, signature)` — upsert.
- `close()`.

An entry is **usable** when `fingerprint` matches and `analysed_at` is within
`PAGE_CACHE_MAX_AGE_DAYS` (config, default 30). With `fresh=True` the audit
still opens the cache, but passes no validators to the crawler and reads no
entries; it only writes the fresh results back.

**Analyzer fingerprint** = sha256 over the source bytes of
`app/auditor/checks.py`, `app/services/page_pipeline.py`,
`app/utils/performance.py`, `app/seo/keyword_extraction.py`,
`app/analysis/minhash.py`, plus the options that change an analysis:
`enable_keyword_analysis`, sorted `target_keywords`, `compute_signature`.
Editing any check invalidates every entry automatically.

### 2. Split analysis — `app/services/page_pipeline.py`

`analyze_page(payload)` becomes `analyze_response(payload, analyze_html(payload))`,
with unchanged output, so every existing caller and test is unaffected.

- `analyze_html(payload) -> HtmlAnalysis` — the parse and every HTML-only
  check: mixed content, canonical, meta-robots half of indexability, title,
  meta description, headings, images, links, structured data, OG/Twitter, URL
  structure, content, mobile, accessibility, hreflang, media, JS-rendering
  signal; plus meta fields, links, keyword data, dupe row, signature, and
  `html_size_bytes`. JSON-serialisable (signature stored separately).
- `analyze_response(payload, html_part) -> PageAnalysis` — no HTML parse:
  `check_status_and_https`, the `X-Robots-Tag` half of indexability,
  `check_security_headers`, page weight (from `html_part.html_size_bytes`,
  response headers, TTFB), `check_performance_proxies`, and
  `meta.security_headers` / `meta.performance`. Merges with `html_part` into
  the `PageAnalysis` shape callers already use.

`check_indexability` is split into `meta_robots_content(page)` (HTML; stored in
the HTML half) and `robots_issues(robots_header, meta_robots)` (run by the
response half on the fresh header plus the stored meta content). Splitting it
into two independent checks instead would report NOINDEX twice when both the
header and the meta tag say noindex.

Page weight splits the same way: `html_weight(page)` (size, DOM, script and
stylesheet counts) is cached; `analyze_page_weight(page, html_part_weight)`
adds TTFB and `Content-Length` from the response.

### 3. Conditional requests — `app/crawler/crawler.py`

`Crawler` takes an optional `validators: Dict[url, Validators]`.

- `_fetch` sends `If-None-Match` (etag) and/or `If-Modified-Since`
  (last_modified) for URLs present in `validators`, on the first request only
  (not redirect hops).
- **304:** returns a `PageResult` with `status_code` 200, empty `html`,
  `cache_status = "not_modified"`, `body_hash` from the validators, and
  headers = stored headers updated by the 304's headers (RFC 9111 §4.3.4).
  A 304 omits most headers, so checking it as-is would report every security
  header missing.
- **200 for a URL in `validators`:** if the body hashes to the stored
  `body_hash`, `cache_status = "same_hash"`.
- `fetch_unconditional(url) -> PageResult` — public; a plain `_fetch` with no
  conditional headers. Used by the audit's fallback below.

`PageResult` gains `cache_status: Optional[str]` and `body_hash: Optional[str]`.
`_owner_of` (Part A layer 3) uses `result.body_hash` when set instead of
hashing, so a 304 duplicate is still detected.

Link expansion: a `not_modified` result has no HTML, so `_handle_result` takes
its internal links from `cached_links: Callable[[url], List[str]]` (supplied by
the audit, reading `html_part.internal_links`). Everything else in
`_handle_result` is unchanged.

### 4. Audit flow — `app/services/audit_service.py`

- `run_full_audit` / `_build_audit_result` gain `fresh: bool = False`.
- Before the crawl: compute the fingerprint, `PageCache.open(...)`. If it
  returns a cache and not `fresh`, pass `cache.validators()` and
  `cached_links` to the crawler.
- `on_page`: if `result.cache_status` is set and `get_html_part(url)` returns
  an entry, build the analysis with `analyze_response(payload, html_part)`
  in-process — no pool, no parse — and resolve immediately. Otherwise submit
  to the pool as today.
- After a fresh analysis of a 200 HTML page, `cache.put(...)` with the
  response's validators. Writes happen in `_resolve` on the audit's main
  thread; workers never touch the cache.
- Pages table row gains `cache_status`.
- Summary gains `reuse: {"not_modified": n, "same_hash": n, "analysed": n}`.

`AuditRequestParams` gains `fresh: Optional[bool] = False`; the route passes it
through. `"reuse"` joins `SUMMARY_FIELDS`.

### 5. Frontend

- Start form, Advanced Overrides: checkbox "Re-check every page" → `fresh`.
- Pages table: `UNCHANGED` badge when `cache_status` is set (title says
  "Not modified since last audit" or "Same HTML as last audit").
- Dashboard: "N pages unchanged since the last audit" beside the Part A count,
  when non-zero.
- Shared types: `PageItem.cache_status`, `AuditResponse.reuse`,
  `AuditRequestParams.fresh`.

## Error handling

- Any exception opening, reading, or writing the cache: log once, continue the
  audit without it (writes are dropped, reads become misses).
- A 304 whose cache entry cannot be read — the one case with no body to fall
  back on: the crawler's `_handle_result` finds no cached links for it and calls
  `fetch_unconditional(url)` before extracting links, so both its links and its
  analysis come from a full response.
- Pages that errored, were non-HTML, or were Part A aliases/duplicates are
  never written to the cache.

## Testing

- Fingerprint: changes when a listed source file or option changes; an entry
  with an old fingerprint is not in `validators()`.
- Age: an entry 31 days old is not usable; 29 days is.
- `analyze_page` output is identical before and after the split (existing
  page-pipeline tests, plus one asserting `analyze_response(p, analyze_html(p))
  == analyze_page(p)` on a fixture page).
- 304 path: conditional headers are sent; the result reuses the cached issues
  and meta; TTFB, status, and security-header issues come from the new
  response; a 304 carrying only `ETag` does not produce
  `MISSING_HEADER_CONTENT_SECURITY_POLICY` when the stored headers had CSP.
- 304 links still drive the crawl: a cached page's links are crawled.
- Same-hash path skips analysis; a changed body is re-analysed and re-cached.
- `fresh=True` sends no conditional headers and re-analyses everything.
- Corrupt cache file: the audit completes and reports `reuse.analysed == pages`.
- Part A interplay: a 304 page whose stored body hash equals another page's is
  recorded as `duplicate_of`.
- Session DB from before Part B opens (new `cache_status` column added).

## Out of scope

- Skipping the request entirely for recently checked pages ("skip for N
  days") — rejected in favour of always asking the server.
- Reusing keyword rank checks or PSI results: they are quota'd external calls
  with their own cache (`rank_checker.py`).
- Cache eviction beyond the 30-day usability window: stale rows are
  overwritten on the next audit of that page; a site no longer audited keeps
  its file until deleted by hand.
