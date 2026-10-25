# Full Site Crawl Speed — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Branch:** `feat/crawl-dedup` (after Parts A and B)

## Measurements this design is based on

| Scenario | Result |
| --- | --- |
| `perf/crawl_harness.py --pages 1000` (localhost, 2 analysis workers = deployed shape) | 13.3 s, 13.3 ms/page; the crawl loop spends most of its time blocked waiting on the analysis pool |
| One `analyze_page` on a harness page (this machine) | ~6.3 ms; keyword extraction ~40 %, MinHash ~20 %, three full HTML parses per page |
| Real site, books.toscrape.com, 80 pages, 32 workers | 56 ms/page — bound by the site's response time, not CPU |
| Same, connection pool sized to 32 instead of the default 10 | 22 connections discarded and re-opened per 80 pages before; 0 after; no measurable wall-clock gain at this size |

So CPU per page bounds throughput on the 2-OCPU server (and under concurrent
audits); fetch concurrency bounds a first crawl of a typical real site.

## Requirements

1. Analysis output is byte-identical before and after Step 1 (the Part B golden
   snapshot, `tests/fixtures/analyze_page_golden.json`, must keep passing).
2. Step 1 reduces `analyze_page` CPU per page by at least 25 % on the benchmark.
3. Step 2 shortens a crawl of a responsive site and backs off from a struggling
   one; it never exceeds `CRAWL_MAX_CONCURRENCY`, and honours `Crawl-delay`.
4. Breadth-first order, page caps, Part A dedup and Part B reuse are unchanged.

## Step 1 — Less CPU per page

**Benchmark** — new `perf/analysis_bench.py`: builds 200 pages with the
harness's `_page_html`, runs `analyze_page` over them 5 times, prints the median
ms/page. Run before and after each change; the plan records the numbers.

1. **Keyword n-grams** (`app/seo/keyword_extraction.py`): `_phrases_from_text`
   tests every token of every 1/2/3-gram with `_is_content_word`. Instead,
   tokenise once, split into maximal runs of content words, and emit each run's
   n-grams. Every n-gram made only of content words lies inside one run, and
   nothing else is emitted, so the phrase multiset is identical. The list order
   changes, which no caller observes: `extract_keywords` counts with `Counter`
   and ranks by `(-score, phrase)`.

2. **Page weight uses the shared parse** (`app/utils/performance.py`):
   `html_weight` builds its own `BeautifulSoup`; it calls `checks._soup(page.html)`
   instead. It only reads the tree.

3. **Content text without a private parse** (`app/auditor/checks.py`):
   `check_content` parses a mutable copy only to `decompose()` script, style and
   noscript before `get_text(" ", strip=True)`. It will instead read the cached
   tree and skip strings inside those tags, producing the same text. Guarded by
   the golden snapshot plus a new fixture containing script, style, noscript,
   comments, CDATA, `<template>` and nested inline tags; if exact equality cannot
   be achieved, this item is dropped and recorded as such.

4. **MinHash shingle hashing** (`app/analysis/minhash.py`): replace the per-
   shingle `blake2b(…, digest_size=4)` with `zlib.crc32` (C-implemented, stable
   across processes and runs, 32-bit). Kept only if the benchmark shows ≥ 10 %
   gain on `signature()`; signatures change, which the Part B fingerprint
   (covering `minhash.py`) turns into cache misses automatically. Duplicate
   detection accuracy is unchanged in kind: both are 32-bit hashes of the same
   shingles feeding the same permutations.

## Step 2 — Faster, polite fetching

1. **Connection pool** (`crawler.py`, `Crawler.__init__`): mount an
   `HTTPAdapter(pool_connections=4, pool_maxsize=max_concurrency)` for http and
   https on `self.session`.

2. **Adaptive concurrency** — new `app/crawler/throttle.py`, class
   `AdaptiveLimit(initial, maximum, minimum=4, window=50)`:
   - `limit` (int): how many fetches may be in flight now.
   - `record(response_ms: float | None, status: int | None, retry_after: float | None)`
     — called once per completed fetch from the crawl loop's thread.
   - Baseline = median response time of the first `window` responses.
   - After each further `window` responses: if none was a 429/503/timeout and
     the window median ≤ 1.5 × baseline, `limit = min(limit + 4, maximum)`.
   - Immediately on a 429/503 or timeout (status None), or when a window median
     > 2 × baseline: `limit = max(limit // 2, minimum)`, and the window restarts.
   - `paused_until` (monotonic seconds): set from `Retry-After` on a 429 (seconds
     form only; capped at 60 s). Admission waits while `now < paused_until`.
   - Pure and deterministic: time is passed in, so it is unit-tested without
     sleeping.

   `Crawler.crawl` sizes its `ThreadPoolExecutor` to `maximum`, and replaces the
   fixed `max_in_flight = concurrency * 2` admission bound with
   `self.limit.limit`. Response time and status come from each `PageResult`;
   `Retry-After` is captured into a new `PageResult.retry_after` by `_fetch`.

   Config: `CRAWL_CONCURRENCY` (initial, default 32, unchanged) and new
   `CRAWL_MAX_CONCURRENCY` (default 64). The CLI's `--concurrency` sets both
   initial and maximum, so a CLI user's explicit number is never exceeded.

3. **`Crawl-delay`**: when `respect_robots` and robots.txt declares a
   `Crawl-delay` for our user agent (`robotparser.crawl_delay`), the crawler sets
   `delay` to it and `maximum = initial = 1`. The site's stated rate wins over
   adaptivity.

## Measuring Step 2

`perf/crawl_harness.py` gains:
- `--latency-ms N`: the handler sleeps N ms per request (simulated real site).
- `--throttle-at N`: the handler answers 429 with `Retry-After: 1` while more
  than N requests are in progress.

Acceptance, recorded in the plan:
- `--pages 1000 --latency-ms 150`: wall clock lower than with the fixed 32.
- `--pages 1000 --latency-ms 150 --throttle-at 16`: the crawl completes, every
  page is crawled, and the final limit is ≤ 16.

## Testing

- Golden snapshot (existing) + new content-extraction fixture: identical output.
- `_phrases_from_text`: same multiset as the old implementation over a table of
  inputs (stop words at edges, single tokens, all-stop-word text, apostrophes).
- `AdaptiveLimit`: rises after a healthy window; never exceeds maximum; halves
  on 429, 503, timeout and slow window; never below minimum; honours and caps
  Retry-After; baseline taken from the first window.
- Crawler: never more fetches in flight than `limit` (instrumented fake fetch);
  Crawl-delay forces concurrency 1 and the delay; existing concurrency tests
  pass unchanged.

## Out of scope

- Showing the live concurrency in the dashboard.
- Per-host limits for multi-host crawls (the crawler stays on one site).
- HTTP/2 or async I/O rewrites of the fetcher.
