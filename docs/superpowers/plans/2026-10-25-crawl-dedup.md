# Crawl Dedup & Crawl Improvements (Part A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch and analyse each page at most once per audit, whichever URL spelling reached it, and crawl sitemap-only pages.

**Architecture:** Three dedup layers in `crawler.py`: safe URL normalisation before queueing, redirect aliases after fetch, and exact-body hashing after fetch. Skipped results go to a new `crawler.skipped` dict instead of `crawler.results`, so every downstream consumer of `results` keeps working unchanged. `audit_service` writes skipped URLs as rows (with `alias_of` / `duplicate_of`) and reports a `dedup` summary. Sitemap URLs are seeded at lowest heap priority.

**Tech Stack:** Python 3 (requests, BeautifulSoup, sqlite3, pytest), Next.js 14 + TypeScript (vitest, Testing Library).

**Spec:** `docs/superpowers/specs/2026-10-25-crawl-dedup-design.md`

## Global Constraints

- Never merge two URLs without proof: lossless normalisation, a server redirect, or byte-identical HTML.
- Layer 3 (body hash) applies only to `status_code == 200` responses whose `content_type` contains `text/html`.
- `max_pages` counts unique pages; total fetches are capped at `2 × max_pages`.
- Sitemap-only pages get `depth = max_depth + 1` and `found_via = "sitemap"` (depth stays an integer everywhere).
- Tracking params stripped: names starting `utm_`, plus `gclid`, `fbclid`, `msclkid`, `dclid`, `yclid`, `mc_cid`, `mc_eid`, `_ga`, `_gl`, `ref_src` (case-insensitive).
- Trailing slash, path case, `www`, and scheme are never normalised.
- Backend tests run from `apps/backend`: `python -m pytest -q`. Baseline before this plan: 233 passed.
- Frontend tests run from `apps/frontend`: `npx vitest run`.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

---

### Task 1: Safe URL normalisation

**Files:**
- Modify: `apps/backend/app/crawler/crawler.py:39-47` (`normalize_url`)
- Test: `apps/backend/tests/test_normalize_url.py` (create)

**Interfaces:**
- Produces: `normalize_url(url: str) -> str` (same signature, stricter rules). Used by the crawler and by `page_pipeline._extract_links`, so stored link edges use the same keys.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_normalize_url.py`:

```python
"""normalize_url merges only spellings that cannot change what the server serves.

Anything that *can* serve different content -- trailing slash, path case, www,
scheme -- is left alone; redirects and identical bodies decide those instead.
"""

import pytest

from app.crawler.crawler import normalize_url


@pytest.mark.parametrize("raw, expected", [
    # tracking params dropped
    ("https://example.com/shoes?utm_source=fb", "https://example.com/shoes"),
    ("https://example.com/shoes?UTM_Medium=x&gclid=1&fbclid=2", "https://example.com/shoes"),
    ("https://example.com/s?msclkid=a&dclid=b&yclid=c&mc_cid=d&mc_eid=e&_ga=f&_gl=g&ref_src=h",
     "https://example.com/s"),
    # real params kept and sorted by name, repeated keys keep their order
    ("https://example.com/s?b=2&a=1", "https://example.com/s?a=1&b=2"),
    ("https://example.com/s?tag=z&tag=a", "https://example.com/s?tag=z&tag=a"),
    ("https://example.com/s?q=1&utm_campaign=x", "https://example.com/s?q=1"),
    # valueless params are not rewritten to "name="
    ("https://example.com/s?print", "https://example.com/s?print"),
    # default ports dropped, others kept
    ("https://example.com:443/a", "https://example.com/a"),
    ("http://example.com:80/a", "http://example.com/a"),
    ("https://example.com:8443/a", "https://example.com:8443/a"),
    # existing behaviour preserved
    ("HTTPS://Example.COM/a#frag", "https://example.com/a"),
    ("https://example.com", "https://example.com/"),
    ("https://example.com//a//b", "https://example.com/a/b"),
])
def test_lossless_spellings_are_merged(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "https://example.com/about/",
    "https://example.com/About",
    "https://www.example.com/a",
    "http://example.com/a",
    "https://example.com/index.html",
])
def test_spellings_that_can_serve_different_content_are_kept(raw):
    assert normalize_url(raw) == raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_normalize_url.py -v`
Expected: FAIL on the tracking-param, sorting, and default-port cases.

- [ ] **Step 3: Implement**

Replace `normalize_url` in `apps/backend/app/crawler/crawler.py` (and add the two constants above it):

```python
# Query params that only identify where a click came from. They never change
# which page the server returns, so two URLs differing only in these are one page.
TRACKING_PARAMS = frozenset({
    "gclid", "fbclid", "msclkid", "dclid", "yclid",
    "mc_cid", "mc_eid", "_ga", "_gl", "ref_src",
})
DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_tracking_param(segment: str) -> bool:
    name = up.unquote(segment.split("=", 1)[0]).lower()
    return name.startswith("utm_") or name in TRACKING_PARAMS


def normalize_url(url: str) -> str:
    """Canonical spelling of a URL for dedup.

    Only lossless rewrites: fragment, host case, default port, tracking params,
    and param order. Query segments are filtered and sorted as raw text rather
    than parsed and re-encoded, so `?print` stays `?print` and percent-escapes
    are untouched. The sort is stable and keyed on the name alone, so repeated
    keys keep their relative order.
    """
    parts = up.urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None and DEFAULT_PORTS.get(scheme) == port:
        netloc = netloc.rsplit(":", 1)[0]

    path = parts.path or "/"
    # collapse duplicate slashes
    while "//" in path:
        path = path.replace("//", "/")

    segments = [s for s in parts.query.split("&") if s and not _is_tracking_param(s)]
    segments.sort(key=lambda s: s.split("=", 1)[0])
    query = "&".join(segments)

    return up.urlunsplit((scheme, netloc, path, query, ""))
```

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_normalize_url.py -v && python -m pytest -q`
Expected: new tests PASS; full suite 233 + new tests passing.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/crawler/crawler.py apps/backend/tests/test_normalize_url.py
git commit -m "feat: strip tracking params and default ports when normalising URLs"
```

---

### Task 2: Redirect aliases, body-hash duplicates, and unique-page cap

**Files:**
- Modify: `apps/backend/app/crawler/crawler.py` (`PageResult`, `Crawler.__init__`, `crawl`, `_handle_result`; add `_owner_of`)
- Test: `apps/backend/tests/test_crawler_dedup.py` (create)

**Interfaces:**
- Consumes: `normalize_url` (Task 1).
- Produces:
  - `PageResult.alias_of: Optional[str] = None`, `PageResult.duplicate_of: Optional[str] = None`, `PageResult.found_via: str = "link"`.
  - `Crawler.skipped: Dict[str, PageResult]`: alias and duplicate results, keyed by requested URL. They are **not** in `Crawler.results` and are **not** passed to `on_page`.
  - `Crawler.aliases: Dict[str, str]`: URL to the requested URL that represents it.
  - `Crawler.fetch_ceiling: int`, equal to `2 * max_pages`.
  - `crawl()` frontier entries become 5-tuples `(priority, seq, url, referrer, via)`; `_handle_result(self, future, url, depth, referrer, via, frontier, sequence, progress_callback, on_page)`.
  - `progress_callback(done, max_pages, url)` now reports `len(self.results)` (unique pages), not `len(self.visited)`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_crawler_dedup.py`:

```python
"""One page, one fetch-and-analysis, whichever spelling reached it.

Fixtures set content_type="text/html" explicitly: the body-hash layer applies
only to real HTML responses, which is what the live fetcher always reports.
"""

import threading
import time

from app.crawler.crawler import Crawler, PageResult

HOME = "https://example.com/"


def _page(url, html, final_url=None, status=200, content_type="text/html"):
    return PageResult(url=url, final_url=final_url or url, status_code=status,
                      html=html, headers={}, content_type=content_type)


def _crawler(site, redirects=None, max_pages=50, max_depth=5):
    """`site` maps URL -> HTML; `redirects` maps URL -> final URL."""
    redirects = redirects or {}
    fetched = []
    lock = threading.Lock()

    def fetch(url):
        with lock:
            fetched.append(url)
        final = redirects.get(url, url)
        return _page(url, site.get(final, ""), final_url=final)

    crawler = Crawler(HOME, max_pages=max_pages, max_depth=max_depth, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler._fetch = fetch
    return crawler, fetched


def _unique(n):
    return f"<html><body>page {n}</body></html>"


def test_target_linked_after_its_redirect_is_never_fetched_on_its_own():
    site = {
        HOME: "<a href='/a'>a</a>",
        "https://example.com/a-target": "<a href='/a-target'>self</a>" + _unique(1),
    }
    crawler, fetched = _crawler(site, redirects={"https://example.com/a": "https://example.com/a-target"})
    analysed = []

    crawler.crawl(on_page=lambda r: analysed.append(r.url))

    assert "https://example.com/a-target" not in fetched
    assert analysed == [HOME, "https://example.com/a"]


def test_redirect_landing_on_an_already_crawled_page_is_an_alias():
    site = {
        HOME: "<a href='/b'>b</a><a href='/old'>old</a>",
        "https://example.com/b": _unique(1),
    }
    crawler, _ = _crawler(site, redirects={"https://example.com/old": "https://example.com/b"},
                          max_depth=1)
    # /b and /old are siblings; make /b complete first so /old is the alias.
    original = crawler._fetch

    def ordered(url):
        if url == "https://example.com/old":
            time.sleep(0.05)
        return original(url)

    crawler._fetch = ordered
    analysed = []

    results = crawler.crawl(on_page=lambda r: analysed.append(r.url))

    assert "https://example.com/old" not in results
    assert crawler.skipped["https://example.com/old"].alias_of == "https://example.com/b"
    assert crawler.aliases["https://example.com/old"] == "https://example.com/b"
    assert "https://example.com/old" not in analysed


def test_two_redirects_to_one_target_produce_one_analysis():
    site = {
        HOME: "<a href='/x'>x</a><a href='/y'>y</a>",
        "https://example.com/t": _unique(1),
    }
    crawler, _ = _crawler(site, redirects={
        "https://example.com/x": "https://example.com/t",
        "https://example.com/y": "https://example.com/t",
    })
    analysed = []

    crawler.crawl(on_page=lambda r: analysed.append(r.url))

    assert len([u for u in analysed if u != HOME]) == 1
    assert len(crawler.skipped) == 1


def test_identical_html_under_two_paths_is_analysed_once():
    body = _unique(7)
    site = {HOME: "<a href='/x'>1</a><a href='/x/'>2</a>",
            "https://example.com/x": body, "https://example.com/x/": body}
    crawler, _ = _crawler(site)
    analysed = []

    crawler.crawl(on_page=lambda r: analysed.append(r.url))

    skipped = list(crawler.skipped.values())
    assert len(skipped) == 1
    assert skipped[0].duplicate_of in {"https://example.com/x", "https://example.com/x/"}
    assert skipped[0].url not in analysed


def test_html_differing_by_one_byte_is_analysed_twice():
    site = {HOME: "<a href='/x'>1</a><a href='/y'>2</a>",
            "https://example.com/x": "<p>a</p>", "https://example.com/y": "<p>b</p>"}
    crawler, _ = _crawler(site)

    crawler.crawl()

    assert crawler.skipped == {}
    assert len(crawler.results) == 3


def test_non_html_responses_are_never_hashed():
    crawler = Crawler(HOME, max_pages=10, max_depth=2, respect_robots=False)
    crawler.sitemap_urls = set()
    links = "<a href='/a.txt'>a</a><a href='/b.txt'>b</a>"
    crawler._fetch = lambda url: (
        _page(url, links) if url == HOME else _page(url, "same", content_type="text/plain")
    )

    crawler.crawl()

    assert crawler.skipped == {}


def test_cap_counts_unique_pages_so_duplicates_do_not_use_it_up():
    """10 unique pages, each also served byte-identically under a trailing slash."""
    links = "".join(f"<a href='/p{i}'>p</a><a href='/p{i}/'>d</a>" for i in range(10))
    site = {HOME: links}
    for i in range(10):
        site[f"https://example.com/p{i}"] = _unique(i)
        site[f"https://example.com/p{i}/"] = _unique(i)
    crawler, _ = _crawler(site, max_pages=11)

    results = crawler.crawl()

    assert len(results) == 11  # home + all 10 unique pages
    for i in range(10):
        spellings = {f"https://example.com/p{i}", f"https://example.com/p{i}/"}
        assert len(spellings & set(results)) == 1


def test_a_site_of_endless_aliases_stops_at_the_fetch_ceiling():
    """100 links that all redirect to one page: every one after the first is an
    alias and hands its slot back, so only the ceiling ends the crawl."""
    target = "https://example.com/target"
    links = "".join(f"<a href='/r{i}'>r</a>" for i in range(100))
    redirects = {f"https://example.com/r{i}": target for i in range(100)}
    crawler, fetched = _crawler({HOME: links, target: _unique(1)}, redirects=redirects,
                                max_pages=5)

    crawler.crawl()

    assert crawler.fetch_ceiling == 10
    assert len(fetched) == 10
    assert len(crawler.results) == 2  # home + the one URL that claimed the target


def test_links_to_a_known_alias_resolve_to_the_page_it_represents():
    """/old redirects to /b and is crawled first, so /old represents /b. A page
    found later linking straight to /b gets an edge to /old, and /b is never
    fetched on its own."""
    site = {
        HOME: "<a href='/old'>old</a>",
        "https://example.com/b": "<a href='/c'>c</a>" + _unique(1),
        "https://example.com/c": "<a href='/b'>back</a>" + _unique(2),
    }
    crawler, fetched = _crawler(site, redirects={"https://example.com/old": "https://example.com/b"})

    crawler.crawl()

    assert crawler.link_graph["https://example.com/c"] == {"https://example.com/old"}
    assert "https://example.com/b" not in fetched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_crawler_dedup.py -v`
Expected: FAIL with `AttributeError` on `skipped`, `aliases`, or `fetch_ceiling`.

- [ ] **Step 3: Implement**

In `apps/backend/app/crawler/crawler.py`:

1. Add `import hashlib` to the imports.

2. Add these fields to `PageResult`, after `error`:

```python
    # Set when this URL turned out to be a page already represented by another:
    # alias_of after a redirect landed on a claimed URL, duplicate_of after the
    # body matched one already seen byte for byte.
    alias_of: Optional[str] = None
    duplicate_of: Optional[str] = None
    found_via: str = "link"
```

3. In `Crawler.__init__`, after `self.sitemaps_found: List[str] = []`, add:

```python
        # Dedup state. All three are touched only from the crawl loop's own
        # thread (_handle_result), never from a fetch worker, so need no lock.
        self.aliases: Dict[str, str] = {}      # url -> url whose result represents it
        self.claimed: Dict[str, str] = {}      # normalised final url -> first url to reach it
        self.body_owner: Dict[str, str] = {}   # sha256 of html -> first url serving it
        self.skipped: Dict[str, PageResult] = {}
        # A site that is all duplicates (endless calendar params, say) frees
        # every slot it takes; this bounds the fetches regardless.
        self.fetch_ceiling = max_pages * 2
        self._sitemap_pending: Set[str] = set()
        self._admitted = 0
        self._fetched = 0
```

4. Replace the body of `crawl` from `self.event_callback = event_callback` through the end of the `with` block (keep the docstring; add one paragraph to it: "A URL whose result turns out to be an alias or duplicate gives its admission back, so `max_pages` counts unique pages; `fetch_ceiling` bounds the total."):

```python
        self.event_callback = event_callback
        sequence = itertools.count()
        frontier = [(0, next(sequence), self.start_url, None, "link")]
        self.queued.add(self.start_url)

        in_flight = {}
        in_flight_urls: Set[str] = set()
        self._admitted = 0
        self._fetched = 0
        # Admission is counted under a lock rather than from len(self.visited):
        # with many fetches outstanding, each could pass a `visited < max_pages`
        # check before any of them has recorded a result, and the crawl would
        # overshoot the cap.
        lock = threading.Lock()
        # Bounded so the frontier cannot run far ahead of the work, which is
        # what keeps un-analysed HTML from accumulating.
        max_in_flight = max(self.concurrency * 2, 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            while frontier or in_flight:
                if self.is_stopped:
                    break
                if self.is_paused:
                    time.sleep(0.5)
                    continue

                while frontier and len(in_flight) < max_in_flight:
                    with lock:
                        # Checked before popping: an in-flight result may yet
                        # turn out to be a duplicate and hand its slot back, so
                        # the frontier must survive reaching the cap.
                        if self._admitted >= self.max_pages or self._fetched >= self.fetch_ceiling:
                            break
                    priority, _, url, referrer, via = heapq.heappop(frontier)
                    # A URL can sit in the heap twice (a sitemap entry and a
                    # later link entry); whichever pops second is stale.
                    if url in self.visited or url in in_flight_urls or not self._allowed(url):
                        continue
                    self._sitemap_pending.discard(url)
                    with lock:
                        self._admitted += 1
                        self._fetched += 1
                    # The heap priority is the depth: links are pushed at
                    # depth + 1, sitemap entries (Task 3) at max_depth + 1.
                    in_flight[pool.submit(self._fetch_paced, url)] = (url, priority, referrer, via)
                    in_flight_urls.add(url)

                if not in_flight:
                    # Nothing outstanding and nothing admissible: the crawl is
                    # done, whether the frontier emptied or the cap was reached.
                    break

                done, _ = concurrent.futures.wait(
                    in_flight, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    url, depth, referrer, via = in_flight.pop(future)
                    in_flight_urls.discard(url)
                    self._handle_result(
                        future, url, depth, referrer, via, frontier, sequence,
                        progress_callback, on_page,
                    )
```

5. Add `_fetch_paced` directly below `_fetch` (Task 3 adds the delay; for now it only delegates). Tests replace `_fetch`, so the pool must call through this wrapper:

```python
    def _fetch_paced(self, url: str) -> PageResult:
        """The worker's entry point. Calls self._fetch at call time, so a test
        that replaces _fetch on the instance is still honoured."""
        return self._fetch(url)
```

6. Add `_owner_of` above `_handle_result`:

```python
    def _owner_of(self, result: PageResult, url: str) -> Optional[str]:
        """The URL already representing this result, or None if it is a new page.

        Records this result's own claims when it is new. Redirect evidence is
        checked first: it is proof from the server. The body hash is checked
        second, and only for 200 HTML, so an error page or a binary file is
        never declared a duplicate of another.
        """
        if result.error or result.status_code is None:
            return None

        final = normalize_url(result.final_url or url)
        claimant = self.claimed.get(final)
        if claimant is not None and claimant != url:
            result.alias_of = claimant
            self.aliases[url] = claimant
            return claimant

        if (
            result.html
            and result.status_code == 200
            and "text/html" in (result.content_type or "")
        ):
            digest = hashlib.sha256(result.html.encode("utf-8", errors="ignore")).hexdigest()
            first = self.body_owner.get(digest)
            if first is not None:
                result.duplicate_of = first
                self.aliases[url] = first
                self.claimed[final] = first
                return first
            self.body_owner[digest] = url

        self.claimed[final] = url
        if final != url:
            # The redirect target is now represented by this result: a later
            # link straight to it must not fetch it again.
            self.aliases[final] = url
            self.queued.add(final)
        return None
```

7. Replace `_handle_result` with:

```python
    def _handle_result(self, future, url, depth, referrer, via, frontier, sequence,
                       progress_callback, on_page):
        """Record one fetched page and push whatever it links to."""
        result = future.result()
        result.depth = depth
        result.found_via = via
        if referrer:
            result.referrers.add(referrer)
            self.inbound_links.setdefault(url, set()).add(referrer)
        self.visited.add(url)

        owner = self._owner_of(result, url)
        if owner is not None:
            # Already represented: give the cap slot back, credit the inbound
            # link to the page that represents it, and stop -- no analysis,
            # no link expansion.
            self._admitted -= 1
            self.skipped[url] = result
            moved = self.inbound_links.pop(url, set())
            if moved:
                self.inbound_links.setdefault(owner, set()).update(moved)
            result.html = ""
            if self.event_callback:
                self.event_callback("page_crawled", {
                    "url": result.url,
                    "status": result.status_code,
                    "depth": result.depth,
                    "response_time": result.response_time_ms,
                    "timestamp": time.time() * 1000,
                    "alias_of": result.alias_of,
                    "duplicate_of": result.duplicate_of,
                })
            return

        self.results[url] = result

        if progress_callback:
            progress_callback(len(self.results), self.max_pages, url)
        if self.event_callback:
            self.event_callback("page_crawled", {
                "url": result.url,
                "status": result.status_code,
                "depth": result.depth,
                "response_time": result.response_time_ms,
                "timestamp": time.time() * 1000,
            })

        internal_links, external_links = [], []
        if result.html:
            for link in self._extract_links(result.final_url, result.html):
                normalized = normalize_url(link)
                if same_registrable_domain(normalized, self.root_netloc):
                    # Resolved through known aliases, so the graph points at the
                    # page that represents the URL rather than at a skipped one.
                    internal_links.append(self.aliases.get(normalized, normalized))
                else:
                    external_links.append(normalized)

        # Links are read before the observer runs, because stage 2 releases the
        # page's markup as soon as it has handed it to a worker -- extracting
        # afterwards would find an empty string and the crawl would stop at the
        # start URL. on_page runs for every page, including at the depth limit
        # and for an empty one: it is how stage 2 receives the page at all.
        if on_page is not None:
            on_page(result)

        self.link_graph[url] = set(internal_links)
        for target in external_links:
            self.external_links.add(target)

        self._link_counts["internal"] += len(internal_links)
        self._link_counts["external"] += len(external_links)
        self._flush_link_progress()

        # A sitemap-only page is analysed, but the sitemap adds the pages it
        # lists, not a second crawl rooted at each of them.
        if depth >= self.max_depth or via == "sitemap":
            return
        for target in internal_links:
            if target in self._sitemap_pending:
                # Found by a link after all: queue it again at its real depth.
                # The sitemap entry is skipped when it pops.
                self._sitemap_pending.discard(target)
                heapq.heappush(frontier, (depth + 1, next(sequence), target, url, "link"))
            elif target not in self.queued and target not in self.visited:
                self.queued.add(target)
                heapq.heappush(frontier, (depth + 1, next(sequence), target, url, "link"))
```

Note that the `time.sleep(self.delay)` that used to sit in `_handle_result` is gone. Task 3 moves it into `_fetch_paced`.

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_crawler_dedup.py -v && python -m pytest -q`
Expected: new tests PASS; full suite green. Existing fixtures leave `content_type` empty, so layer 3 never fires for them, and `final_url == url`, so layer 2 never fires.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/crawler/crawler.py apps/backend/tests/test_crawler_dedup.py
git commit -m "feat: fetch and analyse each page once, via redirect aliases and body hashes"
```

---

### Task 3: Sitemap seeding and per-worker delay

**Files:**
- Modify: `apps/backend/app/crawler/crawler.py` (`crawl`: call `_seed_sitemap`; add `_seed_sitemap`; `_fetch_paced` sleeps)
- Test: `apps/backend/tests/test_crawler_sitemap.py` (create)

**Interfaces:**
- Consumes: frontier 5-tuples, `_sitemap_pending`, `_fetch_paced` (Task 2).
- Produces: `Crawler._seed_sitemap(frontier, sequence) -> None`. Sitemap-only results have `found_via == "sitemap"` and `depth == max_depth + 1`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_crawler_sitemap.py`:

```python
"""Sitemap-listed pages are crawled, after everything links reach."""

import time

from app.crawler.crawler import Crawler, PageResult

HOME = "https://example.com/"


def _crawler(site, sitemap, max_pages=50, max_depth=3, delay=0.0, concurrency=8):
    crawler = Crawler(HOME, max_pages=max_pages, max_depth=max_depth,
                      respect_robots=False, delay=delay, concurrency=concurrency)
    crawler.sitemap_urls = set(sitemap)
    crawler._fetch = lambda url: PageResult(
        url=url, final_url=url, status_code=200, html=site.get(url, f"<p>{url}</p>"), headers={},
    )
    return crawler


def test_a_page_only_in_the_sitemap_is_crawled_and_marked():
    orphan = "https://example.com/orphan"
    crawler = _crawler({HOME: "<p>no links</p>"}, sitemap=[orphan])

    results = crawler.crawl()

    assert orphan in results
    assert results[orphan].found_via == "sitemap"
    assert results[orphan].depth == crawler.max_depth + 1


def test_a_sitemap_page_also_reachable_by_link_gets_its_link_depth():
    linked = "https://example.com/linked"
    crawler = _crawler({HOME: f"<a href='{linked}'>l</a>"}, sitemap=[linked])

    results = crawler.crawl()

    assert results[linked].depth == 1
    assert results[linked].found_via == "link"


def test_link_reachable_pages_are_crawled_before_sitemap_only_ones():
    children = [f"https://example.com/c{i}" for i in range(5)]
    orphan = "https://example.com/orphan"
    crawler = _crawler({HOME: "".join(f"<a href='{c}'>c</a>" for c in children)},
                       sitemap=[orphan], max_pages=6)

    results = crawler.crawl()

    assert orphan not in results  # cap filled by link-reachable pages first
    assert set(children) <= set(results)


def test_off_domain_sitemap_entries_are_ignored():
    crawler = _crawler({HOME: "<p>x</p>"}, sitemap=["https://other.com/x"])

    results = crawler.crawl()

    assert "https://other.com/x" not in results


def test_sitemap_only_pages_are_not_expanded():
    orphan = "https://example.com/orphan"
    beyond = "https://example.com/beyond"
    crawler = _crawler({HOME: "<p>x</p>", orphan: f"<a href='{beyond}'>b</a>"}, sitemap=[orphan])

    results = crawler.crawl()

    assert beyond not in results


def test_delay_paces_each_worker_not_the_whole_crawl():
    """8 pages, 8 workers, 0.2s delay: paced per worker this takes ~0.2s plus
    the home page; paced on the main loop it took 8 x 0.2s."""
    children = [f"https://example.com/c{i}" for i in range(8)]
    crawler = _crawler({HOME: "".join(f"<a href='{c}'>c</a>" for c in children)},
                       sitemap=[], delay=0.2, concurrency=8)

    started = time.monotonic()
    crawler.crawl()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_crawler_sitemap.py -v`
Expected: FAIL. The orphan isn't crawled, and the delay test fails because `_fetch_paced` doesn't sleep yet while the old main-loop sleep was removed in Task 2 (so it may pass by accident; the sitemap tests must fail).

- [ ] **Step 3: Implement**

In `apps/backend/app/crawler/crawler.py`:

1. Add below `_owner_of`:

```python
    def _seed_sitemap(self, frontier, sequence) -> None:
        """Queue sitemap-listed pages behind every link-discovered page.

        Priority max_depth + 1 sorts them after anything a link can reach, so
        sitemap-only pages -- often the orphans an audit exists to find -- fill
        whatever cap remains instead of displacing linked pages.
        """
        for url in sorted(self.sitemap_urls):
            if url in self.queued or not same_registrable_domain(url, self.root_netloc):
                continue
            self.queued.add(url)
            self._sitemap_pending.add(url)
            heapq.heappush(frontier, (self.max_depth + 1, next(sequence), url, None, "sitemap"))
```

2. In `crawl`, directly after `self.queued.add(self.start_url)`, add:

```python
        self._seed_sitemap(frontier, sequence)
```

3. Replace `_fetch_paced` with:

```python
    def _fetch_paced(self, url: str) -> PageResult:
        """The worker's entry point: this worker's politeness delay, then the fetch.

        The delay used to sleep on the crawl loop's own thread, which paused
        admission for every worker. Calls self._fetch at call time, so a test
        that replaces _fetch on the instance is still honoured.
        """
        if self.delay:
            time.sleep(self.delay)
        return self._fetch(url)
```

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_crawler_sitemap.py -v && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/crawler/crawler.py apps/backend/tests/test_crawler_sitemap.py
git commit -m "feat: crawl sitemap-only pages and pace the delay per worker"
```

---

### Task 4: Persist skipped URLs and report dedup

**Files:**
- Modify: `apps/backend/app/models/session_db.py` (`SCHEMA`, `PAGE_COLUMNS`, `SessionDB.__init__`)
- Modify: `apps/backend/app/analysis/analysis.py` (`redirect_report`; add `add_skipped_duplicates`)
- Modify: `apps/backend/app/services/audit_service.py` (`_record` row, skipped rows, `dedup` summary, duplicate groups)
- Modify: `apps/backend/app/api/routes.py:29-34` (`SUMMARY_FIELDS` gains `"dedup"`)
- Test: `apps/backend/tests/test_dedup_persistence.py` (create)

**Interfaces:**
- Consumes: `Crawler.skipped`, `PageResult.alias_of/duplicate_of/found_via` (Tasks 2–3).
- Produces:
  - DB `pages` columns `alias_of TEXT`, `duplicate_of TEXT`, `found_via TEXT`, returned by `get_pages` / `get_page`.
  - `analysis.add_skipped_duplicates(duplicates: Dict, page_data: List[Dict], duplicate_of: Dict[str, str]) -> None` (mutates `duplicates["duplicate_content"]`).
  - Audit result and summary key `dedup: {"aliases": int, "duplicates": int, "sitemap_only": int}`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_dedup_persistence.py`:

```python
"""Skipped URLs are stored and reported, not silently dropped."""

import sqlite3

from app.crawler.crawler import Crawler, PageResult
from app.models.session_db import SessionDB
from app.services import audit_service

HOME = "https://example.com/"


def _page(url, html, final_url=None):
    return PageResult(url=url, final_url=final_url or url, status_code=200,
                      html=html, headers={}, content_type="text/html")


def _crawler():
    body = "<html><head><title>X</title></head><body><h1>X</h1><p>same words</p></body></html>"
    site = {
        HOME: "<html><head><title>Home</title></head><body>"
              "<a href='/x'>1</a><a href='/x/'>2</a><a href='/old'>3</a></body></html>",
        "https://example.com/x": body,
        "https://example.com/x/": body,
    }
    redirects = {"https://example.com/old": HOME}
    crawler = Crawler(HOME, max_pages=10, max_depth=2, respect_robots=False)
    crawler.sitemap_urls = {"https://example.com/orphan"}

    def fetch(url):
        final = redirects.get(url, url)
        page = _page(url, site.get(final, "<p>orphan page</p>"), final_url=final)
        if final != url:
            page.redirect_chain = [{"from": url, "to": final, "status": 301}]
        return page

    crawler._fetch = fetch
    return crawler


def _run(crawler, session_id):
    return audit_service._build_audit_result(
        HOME, crawler, progress_callback=None, event_callback=None, session_id=session_id,
    )


def test_skipped_urls_are_written_as_rows_with_their_reason(isolated_session_dir):
    _run(_crawler(), "sess_dedup")

    db = isolated_session_dir.open_session("sess_dedup")
    rows, total = db.get_pages(limit=50)
    by_url = {row["url"]: row for row in rows}

    assert by_url["https://example.com/old"]["alias_of"] == HOME
    dup = [r for r in rows if r["duplicate_of"]]
    assert len(dup) == 1
    assert by_url["https://example.com/orphan"]["found_via"] == "sitemap"
    assert total == 5


def test_summary_reports_the_dedup_counts():
    result = _run(_crawler(), "sess_counts")

    assert result["dedup"] == {"aliases": 1, "duplicates": 1, "sitemap_only": 1}


def test_an_exact_duplicate_still_appears_in_the_duplicate_content_report():
    result = _run(_crawler(), "sess_groups")

    groups = list(result["duplicates"]["duplicate_content"].values())
    assert any({"https://example.com/x", "https://example.com/x/"} <= set(g) for g in groups)


def test_an_alias_redirect_still_appears_in_the_redirect_report():
    result = _run(_crawler(), "sess_redirects")

    assert result["redirects"]["total_redirecting_urls"] == 1


def test_an_older_session_db_without_the_new_columns_still_opens(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE pages (
          url TEXT PRIMARY KEY, final_url TEXT, depth INTEGER, status INTEGER,
          response_time_ms REAL, content_type TEXT, title TEXT, meta_description TEXT,
          h1 TEXT, canonical TEXT, word_count INTEGER, char_count INTEGER,
          internal_links_count INTEGER, external_links_count INTEGER,
          images_count INTEGER, missing_alt_count INTEGER,
          meta_robots TEXT, lang TEXT, error TEXT, issue_count INTEGER DEFAULT 0,
          meta_json TEXT
        );
        INSERT INTO pages (url, depth, status, issue_count, meta_json)
        VALUES ('https://example.com/', 0, 200, 0, '{}');
    """)
    conn.commit()
    conn.close()

    db = SessionDB(path)
    rows, total = db.get_pages()

    assert total == 1
    assert rows[0]["alias_of"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_dedup_persistence.py -v`
Expected: FAIL. `KeyError: 'alias_of'` / `'dedup'`, and the migration test fails on the missing column.

- [ ] **Step 3: Implement**

1. `apps/backend/app/models/session_db.py`. In `SCHEMA`, change the end of the `pages` table to:

```sql
  meta_robots TEXT, lang TEXT, error TEXT, issue_count INTEGER DEFAULT 0,
  meta_json TEXT, alias_of TEXT, duplicate_of TEXT, found_via TEXT
);
```

Set `PAGE_COLUMNS` to (new columns before `issue_count`, which must stay last because `_CALLER_COLUMNS = PAGE_COLUMNS[:-1]`):

```python
PAGE_COLUMNS = [
    "url", "final_url", "depth", "status", "response_time_ms", "content_type",
    "title", "meta_description", "h1", "canonical", "word_count", "char_count",
    "internal_links_count", "external_links_count", "images_count",
    "missing_alt_count", "meta_robots", "lang", "error",
    "alias_of", "duplicate_of", "found_via", "issue_count",
]
```

In `SessionDB.__init__`, after `self._conn.executescript(SCHEMA)`:

```python
        # Sessions saved before dedup lack these columns; CREATE TABLE IF NOT
        # EXISTS leaves an existing table alone, so add them here or the
        # history panel cannot reopen an older audit.
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(pages)")}
        for column in ("alias_of", "duplicate_of", "found_via"):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE pages ADD COLUMN {column} TEXT")
```

2. `apps/backend/app/analysis/analysis.py`. Change `redirect_report` so it reads skipped results too. Replace both `crawler.results.items()` / `crawler.results.values()` uses inside it with a local `everything`:

```python
def redirect_report(crawler) -> Dict:
    # Skipped aliases are exactly the URLs that redirected onto a page already
    # crawled; leaving them out would hide most of the site's redirects.
    everything = {**crawler.results, **getattr(crawler, "skipped", {})}
    chains = []
    loops = []
    for url, result in everything.items():
        if result.redirect_chain:
            entry = {"start_url": url, "hops": result.redirect_chain, "final_status": result.status_code}
            if len(result.redirect_chain) > 1:
                chains.append(entry)
            seen = set()
            for hop in result.redirect_chain:
                if hop["from"] in seen:
                    loops.append(entry)
                    break
                seen.add(hop["from"])
    return {"redirect_chains": chains, "redirect_loops": loops, "total_redirecting_urls": len(
        [r for r in everything.values() if r.redirect_chain]
    )}
```

Add below `find_duplicates`:

```python
def add_skipped_duplicates(duplicates: Dict, page_data: List[Dict], duplicate_of: Dict[str, str]) -> None:
    """Fold byte-identical pages the crawl skipped into the duplicate-content report.

    They were never analysed, so they have no content hash of their own; they
    join their owner's group. Without this, skipping them would make a real
    duplicate-content problem disappear from the report.
    """
    hash_of = {p["url"]: p.get("content_hash") for p in page_data}
    groups = duplicates.setdefault("duplicate_content", {})
    for duplicate, owner in duplicate_of.items():
        digest = hash_of.get(owner)
        if not digest:
            continue
        group = groups.setdefault(digest, [owner])
        if duplicate not in group:
            group.append(duplicate)
```

3. `apps/backend/app/services/audit_service.py`:

   a. In `_record`, add to the row dict after `"error": ...`:

```python
            "found_via": result.found_via,
```

   b. After `for url, outcome in list(pending.items()): _resolve(url, outcome)` and `pending.clear()`, but **before** `_flush_rows(force=True)`, add:

```python
        # URLs the crawl recognised as a page it already had. They get a row
        # saying which page represents them -- that is an SEO finding -- but
        # no analysis, which would only repeat the owner's.
        for skipped_url, skipped in getattr(crawler, "skipped", {}).items():
            row_buffer.append({
                "url": skipped_url,
                "final_url": skipped.final_url,
                "depth": skipped.depth,
                "status": skipped.status_code,
                "response_time_ms": skipped.response_time_ms,
                "content_type": skipped.content_type,
                "error": skipped.error,
                "alias_of": skipped.alias_of,
                "duplicate_of": skipped.duplicate_of,
                "found_via": skipped.found_via,
                "meta": {},
                "issues": [],
            })
            _flush_rows()
```

   c. After `duplicates = analysis.find_duplicates(page_data_for_dupes)`, add:

```python
    skipped_results = getattr(crawler, "skipped", {})
    analysis.add_skipped_duplicates(
        duplicates,
        page_data_for_dupes,
        {u: r.duplicate_of for u, r in skipped_results.items() if r.duplicate_of},
    )
```

   d. In `result_data`, after `"partial": partial,`, add:

```python
        "dedup": {
            "aliases": sum(1 for r in skipped_results.values() if r.alias_of),
            "duplicates": sum(1 for r in skipped_results.values() if r.duplicate_of),
            "sitemap_only": sum(
                1 for r in crawler.results.values() if getattr(r, "found_via", "link") == "sitemap"
            ),
        },
```

4. `apps/backend/app/api/routes.py`. Add `"dedup"` to `SUMMARY_FIELDS` after `"partial"`.

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_dedup_persistence.py -v && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/models/session_db.py apps/backend/app/analysis/analysis.py apps/backend/app/services/audit_service.py apps/backend/app/api/routes.py apps/backend/tests/test_dedup_persistence.py
git commit -m "feat: store skipped URLs with their reason and report dedup counts"
```

---

### Task 5: Dashboard badges and count

**Files:**
- Modify: `packages/shared/src/types/index.ts` (`PageItem`, `AuditResponse`; add `DedupSummary`)
- Modify: `apps/frontend/components/pages-table.tsx` (badges next to `CANON`)
- Modify: `apps/frontend/app/dashboard/page.tsx:260` (count in the "All Crawled Pages" title)
- Test: `apps/frontend/components/__tests__/pages-table.test.tsx` (add cases)

**Interfaces:**
- Consumes: page rows with `alias_of`, `duplicate_of`, `found_via`; summary `dedup` (Task 4).
- Produces: `DedupSummary { aliases: number; duplicates: number; sitemap_only: number }`.

- [ ] **Step 1: Write the failing tests**

Add inside the `describe("PagesTable", ...)` block in `apps/frontend/components/__tests__/pages-table.test.tsx`:

```tsx
  it("marks a URL that redirects onto another crawled page", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0, { alias_of: "https://example.com/p9" })], 1),
    );

    render(<PagesTable sessionId="sess_1" />);

    const badge = await screen.findByText("ALIAS");
    expect(badge).toHaveAttribute("title", "Redirects to https://example.com/p9");
  });

  it("marks a URL whose HTML duplicates another page", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0, { duplicate_of: "https://example.com/p9" })], 1),
    );

    render(<PagesTable sessionId="sess_1" />);

    const badge = await screen.findByText("DUPLICATE");
    expect(badge).toHaveAttribute("title", "Duplicate of https://example.com/p9");
  });

  it("marks a page found only through the sitemap", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0, { found_via: "sitemap" })], 1),
    );

    render(<PagesTable sessionId="sess_1" />);

    expect(await screen.findByText("SITEMAP")).toBeInTheDocument();
  });

  it("shows no dedup badge on an ordinary page", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(envelope([row(0)], 1));

    render(<PagesTable sessionId="sess_1" />);

    await screen.findByText("https://example.com/p0");
    expect(screen.queryByText("ALIAS")).toBeNull();
    expect(screen.queryByText("DUPLICATE")).toBeNull();
    expect(screen.queryByText("SITEMAP")).toBeNull();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/frontend && npx vitest run components/__tests__/pages-table.test.tsx`
Expected: the three badge tests FAIL (text not found); the "no badge" test passes.

- [ ] **Step 3: Implement**

1. `packages/shared/src/types/index.ts`. Add to `PageItem` after `keyword_analysis?: KeywordAnalysis;`:

```ts
  // Set when the crawl recognised this URL as a page it already had.
  alias_of?: string | null;
  duplicate_of?: string | null;
  found_via?: "link" | "sitemap" | null;
```

Add above `AuditResponse`:

```ts
export interface DedupSummary {
  aliases: number;
  duplicates: number;
  sitemap_only: number;
}
```

Add to `AuditResponse` after `rank_targets?: RankTarget[];`:

```ts
  dedup?: DedupSummary;
```

2. `apps/frontend/components/pages-table.tsx`. Directly after the `{page.canonical && (...)}` block, add:

```tsx
                        {page.alias_of && (
                          <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 text-[9px] font-semibold border border-amber-500/20" title={`Redirects to ${page.alias_of}`}>
                            ALIAS
                          </span>
                        )}
                        {page.duplicate_of && (
                          <span className="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-500 text-[9px] font-semibold border border-rose-500/20" title={`Duplicate of ${page.duplicate_of}`}>
                            DUPLICATE
                          </span>
                        )}
                        {page.found_via === "sitemap" && (
                          <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 text-[9px] font-semibold border border-emerald-500/20" title="Found only in the sitemap, not by following links">
                            SITEMAP
                          </span>
                        )}
```

3. `apps/frontend/app/dashboard/page.tsx`. Above the panel map (next to the destructuring at line ~166), add:

```tsx
  const skippedUrls = (auditData.dedup?.aliases ?? 0) + (auditData.dedup?.duplicates ?? 0);
```

and change the `"pages-table"` entry's title from `All Crawled Pages` to:

```tsx
<CardTitle className="text-base">All Crawled Pages{skippedUrls > 0 && <span className="ml-2 text-xs font-normal text-muted-foreground">{skippedUrls} duplicate URLs skipped</span>}</CardTitle>
```

- [ ] **Step 4: Run tests and typecheck**

Run: `cd packages/shared && npm run build && cd ../../apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all vitest PASS; no type errors.

- [ ] **Step 5: Commit**

```bash
git add packages/shared/src/types/index.ts apps/frontend/components/pages-table.tsx apps/frontend/app/dashboard/page.tsx apps/frontend/components/__tests__/pages-table.test.tsx
git commit -m "feat: badge alias, duplicate and sitemap-only pages in the dashboard"
```

---

### Task 6: End-to-end check against a real site

**Files:** none (verification only)

- [ ] **Step 1:** From the repo root run `npm run dev`. Wait for `Ready` (frontend) and `Application startup complete` (backend).
- [ ] **Step 2:** Open `http://localhost:3000`, run a **Quick Audit** on a site with a sitemap and some tracking-param links. Confirm the audit completes, the "All Crawled Pages" table shows any ALIAS / DUPLICATE / SITEMAP badges, and the title shows the skipped count when it is non-zero.
- [ ] **Step 3:** Open an audit from before this change in the history panel. Confirm it still loads (exercises the column migration).
- [ ] **Step 4:** Stop the dev servers.
