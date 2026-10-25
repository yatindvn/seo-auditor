# Full Site Crawl Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut per-page analysis CPU by at least 25% with byte-identical output, then make fetching adapt its concurrency to how the site responds.

**Architecture:** Step 1 removes redundant work inside `analyze_page`: per-n-gram stop-word checks, two of three HTML parses, and possibly a per-shingle `blake2b`. Each change is measured with a new benchmark, and the Part B golden snapshot guards the output. Step 2 adds a pure `AdaptiveLimit` controller (AIMD: grow by 4 after a healthy window, halve on throttling or slowdown), wires it in as the crawl loop's admission bound, sizes the HTTP connection pool to match, retries 429/503 honouring `Retry-After`, and obeys robots.txt `Crawl-delay`.

**Tech Stack:** Python 3.14, BeautifulSoup 4.14 + lxml, requests/urllib3, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-crawl-speed-design.md`

## Global Constraints

- Branch `feat/crawl-dedup`. Backend baseline: 311 passed.
- `tests/fixtures/analyze_page_golden.json` must keep passing unchanged. Step 1 must not change any analysis output.
- Every Step 1 change records benchmark numbers (before and after) in its commit message. A change that does not help is reverted, and the plan notes that.
- `CRAWL_CONCURRENCY` (initial) stays 32. `CRAWL_MAX_CONCURRENCY` defaults to 64. `AdaptiveLimit` minimum is 4 and window is 50. Growth is +4. A cut halves the limit.
- When the crawler is built without `max_concurrency` (CLI, tests, harness default), maximum equals initial, so an explicit concurrency is never exceeded.
- Robots `Crawl-delay` (when respecting robots) forces initial = maximum = 1 and `delay >= Crawl-delay`.
- `Retry-After` honoured in seconds form only, capped at 60s.
- Run backend tests with `cd apps/backend && python -m pytest -q`.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

---

### Task 1: Analysis benchmark, then cheaper keyword n-grams

**Files:**
- Create: `apps/backend/perf/analysis_bench.py`
- Modify: `apps/backend/app/seo/keyword_extraction.py` (`_phrases_from_text`)
- Test: `apps/backend/tests/test_keyword_ngrams.py` (create)

**Interfaces:**
- Produces: `python perf/analysis_bench.py [--pages 200] [--repeats 5]`, which prints `analyze_page median: X.XX ms/page` and `signature median: X.XX ms/page`. Later tasks quote these.
- `_phrases_from_text(text) -> List[str]`: same multiset of phrases as before; order may differ.

- [ ] **Step 1: Write the benchmark**

Create `apps/backend/perf/analysis_bench.py`:

```python
"""Time page analysis on the harness's synthetic pages.

    cd apps/backend
    python perf/analysis_bench.py

Wall-clock medians on one machine: compare before/after on the same machine,
never across machines.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawl_harness import _page_html  # noqa: E402
from app.analysis import minhash  # noqa: E402
from app.services import page_pipeline  # noqa: E402


def _payloads(count: int):
    return [
        page_pipeline.PagePayload(
            url=f"http://127.0.0.1/page{i}.html", final_url=f"http://127.0.0.1/page{i}.html",
            status_code=200, headers={"Content-Type": "text/html"},
            html=_page_html(i, count).decode("utf-8"), response_time_ms=5.0,
            content_type="text/html", compute_signature=True,
        )
        for i in range(count)
    ]


def _median_ms_per_item(fn, items, repeats: int) -> float:
    runs = []
    for _ in range(repeats):
        started = time.perf_counter()
        for item in items:
            fn(item)
        runs.append((time.perf_counter() - started) / len(items) * 1000)
    return statistics.median(runs)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args(argv)

    payloads = _payloads(args.pages)
    texts = [page_pipeline.analyze_page(p).dupe_row["text"] for p in payloads]

    print(f"analyze_page median: {_median_ms_per_item(page_pipeline.analyze_page, payloads, args.repeats):.2f} ms/page")
    print(f"signature median:    {_median_ms_per_item(minhash.signature, texts, args.repeats):.2f} ms/page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Record the baseline**

Run: `cd apps/backend && python perf/analysis_bench.py`
Expected: two lines of numbers. Write them down as **baseline**. Every later task compares against them.

- [ ] **Step 3: Write the failing equivalence test**

Create `apps/backend/tests/test_keyword_ngrams.py`:

```python
"""_phrases_from_text must produce the same phrases, however it gets there."""

from collections import Counter

import pytest

from app.seo import keyword_extraction
from app.seo.keyword_extraction import _is_content_word, _tokenize


def _reference(text):
    """The original implementation, kept verbatim as the oracle."""
    tokens = _tokenize(text)
    phrases = []
    for n in (1, 2, 3):
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if all(_is_content_word(t) for t in gram):
                phrases.append(" ".join(gram))
    return phrases


CASES = [
    "",
    "the",
    "espresso",
    "the espresso machine",
    "best espresso machine reviews and buying guide for the home",
    "a an the and or but",
    "grinder grinder grinder grinder",
    "it's the barista's choice, isn't it",
    "on top of the best burr grinders of 2026 and beyond the hype",
    "x yy zzz long words only here",
]


@pytest.mark.parametrize("text", CASES)
def test_same_phrases_as_the_original(text):
    assert Counter(keyword_extraction._phrases_from_text(text)) == Counter(_reference(text))


def test_each_word_is_checked_once(monkeypatch):
    """The point of the change: one stop-word check per token, not one per
    token per n-gram it belongs to."""
    calls = []
    original = keyword_extraction._is_content_word
    monkeypatch.setattr(keyword_extraction, "_is_content_word",
                        lambda t: calls.append(t) or original(t))

    keyword_extraction._phrases_from_text("best espresso machine reviews guide")

    assert len(calls) == 5
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_keyword_ngrams.py -q`
Expected: the equivalence cases PASS (they test today's code). `test_each_word_is_checked_once` FAILS with 12 calls instead of 5.

- [ ] **Step 5: Implement**

In `apps/backend/app/seo/keyword_extraction.py`, replace `_phrases_from_text`:

```python
def _phrases_from_text(text: str) -> List[str]:
    """Every 1-, 2- and 3-gram made only of content words.

    Such an n-gram always lies inside one run of consecutive content words, so
    each token is classified once and n-grams are taken run by run -- instead of
    re-testing every token for each of the three n-gram sizes it appears in.
    """
    phrases: List[str] = []
    run: List[str] = []
    for token in _tokenize(text) + [""]:  # sentinel flushes the last run
        if token and _is_content_word(token):
            run.append(token)
            continue
        for n in (1, 2, 3):
            for i in range(len(run) - n + 1):
                phrases.append(" ".join(run[i:i + n]))
        run = []
    return phrases
```

`_is_content_word("")` is never called for the sentinel, because the `token and` guard short-circuits. That keeps the "checked once" count exact.

- [ ] **Step 6: Verify, measure, commit**

Run: `cd apps/backend && python -m pytest tests/test_keyword_ngrams.py tests/test_analysis_split.py tests/test_keyword_extraction.py -q && python -m pytest -q && python perf/analysis_bench.py`
Expected: all PASS, with the golden snapshot unchanged. Record the new `analyze_page` median.

```bash
git add apps/backend/perf/analysis_bench.py apps/backend/app/seo/keyword_extraction.py apps/backend/tests/test_keyword_ngrams.py
git commit -m "perf: classify each token once when building keyword n-grams

analyze_page median: <baseline> -> <new> ms/page (perf/analysis_bench.py)"
```

---

### Task 2: One HTML parse per page

**Files:**
- Modify: `apps/backend/app/utils/performance.py` (`html_weight`)
- Modify: `apps/backend/app/auditor/checks.py` (`check_content`; add `_visible_text`)
- Test: `apps/backend/tests/test_single_parse.py` (create)

**Interfaces:**
- Produces: `checks._visible_text(soup) -> str`. It equals `soup.get_text(" ", strip=True)` after script, style and noscript have been decomposed, without mutating the tree.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_single_parse.py`:

```python
"""Each page is parsed once; the content text is unchanged by not mutating."""

from bs4 import BeautifulSoup

from app.auditor import checks
from app.services import page_pipeline
from app.services.page_pipeline import PagePayload

TRICKY = (
    "<!DOCTYPE html><html><head><title>T</title>"
    "<script>var x = 'not text';</script><style>p { color: red }</style></head>"
    "<body><!-- a comment --><p>Hello <b>bold</b><i>italic</i> world</p>"
    "<noscript><p>enable <em>JS</em></p></noscript>"
    "<template><p>templated</p></template>"
    "<svg><![CDATA[ cdata text ]]></svg>"
    "<div>  spaced\n\n   out  </div><script type='application/ld+json'>{\"a\":1}</script>"
    "<p>tail</p></body></html>"
)


def _old_text(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def test_visible_text_matches_decompose_then_get_text():
    soup = BeautifulSoup(TRICKY, "lxml")
    assert checks._visible_text(soup) == _old_text(TRICKY)


def test_visible_text_leaves_the_tree_intact():
    soup = BeautifulSoup(TRICKY, "lxml")
    checks._visible_text(soup)
    assert len(soup.find_all("script")) == 2
    assert soup.find("noscript") is not None


def test_a_page_is_parsed_once(monkeypatch):
    checks._parse.cache_clear()
    parses = []
    original = checks.BeautifulSoup

    def counting(*args, **kwargs):
        parses.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(checks, "BeautifulSoup", counting)
    import app.utils.performance as performance
    monkeypatch.setattr(performance, "BeautifulSoup", counting)

    page_pipeline.analyze_page(PagePayload(
        url="https://example.com/", final_url="https://example.com/", status_code=200,
        headers={}, html=TRICKY + "<!-- unique 1 -->", content_type="text/html",
    ))

    assert len(parses) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_single_parse.py -q`
Expected: FAIL. `_visible_text` doesn't exist, and the page is parsed 3 times.

- [ ] **Step 3: Implement**

1. In `apps/backend/app/auditor/checks.py`, add above `check_content`:

```python
_NON_CONTENT_TAGS = frozenset({"script", "style", "noscript"})


def _visible_text(soup) -> str:
    """The text get_text(" ", strip=True) returns once script, style and
    noscript are removed -- read from the shared tree instead of a private copy.

    get_text is `separator.join(self._all_strings(strip, types=default))`. This
    walks the same strings unstripped (so each still knows its parents), skips
    any inside a non-content tag, and applies the same strip-and-drop-empty rule,
    so the output is identical and the cached tree is never mutated. bs4 already
    leaves script and style text out of these strings; noscript is the one this
    filter actually removes.
    """
    parts = []
    for string in soup._all_strings(False, types=soup.default):
        if any(parent.name in _NON_CONTENT_TAGS for parent in string.parents):
            continue
        stripped = string.strip()
        if stripped:
            parts.append(stripped)
    return " ".join(parts)
```

2. In `check_content`, replace:

```python
    soup = _soup(page.html, mutable=True)
    stats = {"word_count": 0, "text": ""}
    if not soup:
        return out, stats
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
```

with:

```python
    # The shared parse: _visible_text skips script/style/noscript without
    # removing them, so later checks that count <script> tags still see them.
    soup = _soup(page.html)
    stats = {"word_count": 0, "text": ""}
    if not soup:
        return out, stats
    text = _visible_text(soup)
```

3. In `apps/backend/app/utils/performance.py`, `html_weight`, replace the `soup = None / try: BeautifulSoup(...)` block with:

```python
    # The checks' shared parse of this same HTML: read-only here.
    soup = checks._soup(page.html)
```

   and add `from app.auditor import checks` to the imports. (`performance` already imports `issue` from `app.auditor.checks`, so there is no new cycle.)

- [ ] **Step 4: Verify, measure, commit**

Run: `cd apps/backend && python -m pytest tests/test_single_parse.py tests/test_analysis_split.py tests/test_soup_caching.py -q && python -m pytest -q && python perf/analysis_bench.py`
Expected: all PASS, including the unchanged golden snapshot. Record the new median.

If the golden or `test_visible_text_matches...` can't be made to pass, revert the `check_content` change, keep only the `html_weight` change (2 parses), adjust `test_a_page_is_parsed_once` to expect 2, and say so in the commit message. The spec allows dropping this item.

```bash
git add apps/backend/app/auditor/checks.py apps/backend/app/utils/performance.py apps/backend/tests/test_single_parse.py
git commit -m "perf: parse each page once -- shared tree for page weight and content text

analyze_page median: <before> -> <after> ms/page (perf/analysis_bench.py)"
```

---

### Task 3: Cheaper MinHash shingle hashing (kept only if it measures)

**Files:**
- Modify: `apps/backend/app/analysis/minhash.py` (`_shingle_hashes`)
- Test: existing `apps/backend/tests/test_minhash.py` and `tests/test_near_duplicate_content.py`

- [ ] **Step 1: Measure the candidate before committing to it**

Run: `cd apps/backend && python perf/analysis_bench.py` and note `signature median`.

In `_shingle_hashes`, replace

```python
        seen.add(int.from_bytes(
            hashlib.blake2b(shingle.encode("utf-8"), digest_size=4).digest(), "big"
        ))
```

with

```python
        # crc32: C-implemented and stable across processes and runs, which
        # signatures compared between workers and audits require.
        seen.add(zlib.crc32(shingle.encode("utf-8")))
```

and add `import zlib` to the imports.

Run the benchmark again.

- [ ] **Step 2: Decide**

- If `signature median` dropped by **at least 10%**: run `python -m pytest tests/test_minhash.py tests/test_near_duplicate_content.py -q && python -m pytest -q`. They must all pass. A test that pins exact signature bytes is expected to change: update its expected bytes and say so in the commit. Then commit:

```bash
git add apps/backend/app/analysis/minhash.py
git commit -m "perf: hash MinHash shingles with crc32 instead of blake2b

signature median: <before> -> <after> ms/page. Signatures change; the Part B
cache fingerprint covers minhash.py, so cached signatures are invalidated."
```

- Otherwise: `git checkout apps/backend/app/analysis/minhash.py`. Record "crc32 not adopted: <before> -> <after>" in the final report and commit nothing.

---

### Task 4: The adaptive concurrency controller

**Files:**
- Create: `apps/backend/app/crawler/throttle.py`
- Test: `apps/backend/tests/test_throttle.py` (create)

**Interfaces:**
- Produces `AdaptiveLimit(initial: int, maximum: int, minimum: int = 4, window: int = 50, growth: int = 4)` with:
  - `.limit: int`, the current in-flight bound, always within `[min(minimum, initial), maximum]`.
  - `.paused_until: float`, a monotonic time; admission waits while `now < paused_until`.
  - `.record(response_ms: Optional[float], failed: bool, retry_after: Optional[float], now: float) -> None`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_throttle.py`:

```python
"""AIMD admission control: grow while the site is healthy, halve when it is not."""

from app.crawler.throttle import AdaptiveLimit


def _feed(limit, count, ms=100.0, failed=False, retry_after=None, now=0.0):
    for _ in range(count):
        limit.record(ms, failed, retry_after, now)


def test_starts_at_the_initial_limit():
    assert AdaptiveLimit(initial=32, maximum=64).limit == 32


def test_grows_by_four_after_each_healthy_window():
    limit = AdaptiveLimit(initial=32, maximum=64, window=50)
    _feed(limit, 50)          # first window sets the baseline
    assert limit.limit == 32
    _feed(limit, 50)
    assert limit.limit == 36
    _feed(limit, 50)
    assert limit.limit == 40


def test_never_exceeds_the_maximum():
    limit = AdaptiveLimit(initial=32, maximum=34, window=10)
    _feed(limit, 100)
    assert limit.limit == 34


def test_initial_equal_to_maximum_never_grows():
    limit = AdaptiveLimit(initial=8, maximum=8, window=10)
    _feed(limit, 100)
    assert limit.limit == 8


def test_a_failure_halves_at_once():
    limit = AdaptiveLimit(initial=32, maximum=64)
    limit.record(100.0, True, None, 0.0)
    assert limit.limit == 16


def test_failures_already_in_flight_do_not_halve_again():
    """Requests sent before a cut report their 429s after it; counting them
    would collapse the limit to the minimum on a single burst."""
    limit = AdaptiveLimit(initial=32, maximum=64)
    _feed(limit, 20, failed=True)   # all from the same burst of 32
    assert limit.limit == 16
    _feed(limit, 16)                # the cut has now been "seen" by 16 requests
    limit.record(100.0, True, None, 0.0)
    assert limit.limit == 8


def test_never_below_the_minimum():
    limit = AdaptiveLimit(initial=8, maximum=64, minimum=4)
    for _ in range(10):
        limit.record(100.0, True, None, 0.0)
        _feed(limit, limit.limit)
    assert limit.limit == 4


def test_a_slow_window_halves():
    limit = AdaptiveLimit(initial=32, maximum=64, window=10)
    _feed(limit, 10, ms=100.0)      # baseline 100
    _feed(limit, 10, ms=250.0)      # median 2.5x baseline
    assert limit.limit == 16


def test_a_moderately_slower_window_holds_steady():
    limit = AdaptiveLimit(initial=32, maximum=64, window=10)
    _feed(limit, 10, ms=100.0)
    _feed(limit, 10, ms=180.0)      # 1.8x: not healthy enough to grow, not slow enough to cut
    assert limit.limit == 32


def test_retry_after_pauses_admission_and_is_capped():
    limit = AdaptiveLimit(initial=32, maximum=64)
    limit.record(None, True, 5.0, now=100.0)
    assert limit.paused_until == 105.0
    limit.record(None, True, 600.0, now=200.0)
    assert limit.paused_until == 260.0


def test_responses_without_timing_still_count_as_healthy():
    """Test fakes and some error paths carry no response time."""
    limit = AdaptiveLimit(initial=32, maximum=64, window=10)
    _feed(limit, 20, ms=None)
    assert limit.limit == 36
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_throttle.py -q`
Expected: FAIL with `ModuleNotFoundError: app.crawler.throttle`.

- [ ] **Step 3: Implement**

Create `apps/backend/app/crawler/throttle.py`:

```python
"""Adaptive admission control for the crawl loop (AIMD).

The crawl used to allow a fixed number of fetches in flight. A fast site could
take more; a struggling one was hit just as hard while it slowed or started
answering 429. This grows the in-flight limit additively while responses stay
healthy, and halves it the moment the site pushes back -- the same rule TCP
uses, for the same reason: probe gently, retreat fast.

Pure and deterministic: time is passed in, so it is tested without sleeping.
"""

from __future__ import annotations

import statistics
from typing import List, Optional

RETRY_AFTER_CAP_SECONDS = 60.0
HEALTHY_RATIO = 1.5
SLOW_RATIO = 2.0


class AdaptiveLimit:
    def __init__(self, initial: int, maximum: int, minimum: int = 4,
                 window: int = 50, growth: int = 4) -> None:
        self.maximum = max(maximum, 1)
        self.minimum = max(min(minimum, initial), 1)
        self.limit = min(max(initial, self.minimum), self.maximum)
        self.window = window
        self.growth = growth
        self.paused_until = 0.0
        self._baseline: Optional[float] = None
        self._times: List[float] = []
        self._count = 0
        self._failed_in_window = False
        # Responses seen since the last cut. Until as many responses as the
        # post-cut limit have come back, failures still belong to requests
        # sent before the cut and must not cut again.
        self._since_cut: Optional[int] = None

    def record(self, response_ms: Optional[float], failed: bool,
               retry_after: Optional[float], now: float) -> None:
        if retry_after is not None:
            self.paused_until = max(self.paused_until, now + min(retry_after, RETRY_AFTER_CAP_SECONDS))

        if self._since_cut is not None:
            self._since_cut += 1

        if failed:
            self._failed_in_window = True
            if self._since_cut is None or self._since_cut > self.limit:
                self._cut()
                return

        if response_ms is not None:
            self._times.append(response_ms)
        self._count += 1
        if self._count >= self.window:
            self._close_window()

    def _close_window(self) -> None:
        median = statistics.median(self._times) if self._times else None
        if self._baseline is None:
            self._baseline = median
        elif median is not None and self._baseline and median > SLOW_RATIO * self._baseline:
            self._cut()
            return
        elif not self._failed_in_window and (
            median is None or not self._baseline or median <= HEALTHY_RATIO * self._baseline
        ):
            self.limit = min(self.limit + self.growth, self.maximum)
        self._reset_window()

    def _cut(self) -> None:
        self.limit = max(self.limit // 2, self.minimum)
        self._since_cut = 0
        self._reset_window()

    def _reset_window(self) -> None:
        self._times = []
        self._count = 0
        self._failed_in_window = False
```

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_throttle.py -v`
Expected: all PASS. If `test_responses_without_timing_still_count_as_healthy` fails because the first all-`None` window leaves `_baseline` as `None`, that's handled: `_close_window` grows when `median is None`. Check that the first window (which sets the baseline) does not also grow. 20 responses means one baseline window plus one growth window, giving 36.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/crawler/throttle.py apps/backend/tests/test_throttle.py
git commit -m "feat: AIMD admission controller for crawl concurrency"
```

---

### Task 5: Wire adaptive concurrency into the crawler

**Files:**
- Modify: `apps/backend/app/crawler/crawler.py` (`PageResult`, `Crawler.__init__`, `_load_robots`, `_fetch`, `crawl`)
- Modify: `apps/backend/app/config/config.py` (`CRAWL_MAX_CONCURRENCY`)
- Modify: `apps/backend/app/services/audit_service.py` (`run_full_audit`)
- Test: `apps/backend/tests/test_crawler_adaptive.py` (create)

**Interfaces:**
- Consumes: `AdaptiveLimit` (Task 4); `tests/fake_http.FakeSite` (Part B).
- Produces:
  - `Crawler(..., max_concurrency: Optional[int] = None)`. `None` means `max_concurrency = concurrency`.
  - `Crawler.limit: AdaptiveLimit`, created at the start of `crawl()`.
  - `PageResult.throttled: bool = False` and `PageResult.retry_after: Optional[float] = None`.
  - `config.CRAWL_MAX_CONCURRENCY = int(os.getenv("CRAWL_MAX_CONCURRENCY", "64"))`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_crawler_adaptive.py`:

```python
"""The crawl loop admits no more fetches than the adaptive limit allows."""

import threading
import time

from requests.structures import CaseInsensitiveDict

from app.crawler.crawler import Crawler, PageResult
from tests.fake_http import FakeResponse

HOME = "https://example.com/"


def _wide_site(width):
    children = [f"https://example.com/c{i}" for i in range(width)]
    return children, {HOME: "".join(f"<a href='{c}'>c</a>" for c in children)}


def test_in_flight_fetches_never_exceed_the_limit():
    children, pages = _wide_site(60)
    crawler = Crawler(HOME, max_pages=100, max_depth=2, respect_robots=False,
                      concurrency=6, max_concurrency=6)
    crawler.sitemap_urls = set()
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def fetch(url):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.01)
        with lock:
            state["now"] -= 1
        return PageResult(url=url, final_url=url, status_code=200,
                          html=pages.get(url, f"<p>{url}</p>"), headers={})

    crawler._fetch = fetch
    crawler.crawl()

    assert 1 < state["peak"] <= 6


def test_a_crawler_without_max_concurrency_never_exceeds_its_concurrency():
    crawler = Crawler(HOME, max_pages=5, respect_robots=False, concurrency=8)
    assert crawler.max_concurrency == 8


def test_throttling_halves_the_limit_during_a_crawl():
    children, pages = _wide_site(40)
    crawler = Crawler(HOME, max_pages=100, max_depth=2, respect_robots=False,
                      concurrency=16, max_concurrency=16)
    crawler.sitemap_urls = set()

    def fetch(url):
        throttled = url.endswith("c3")
        return PageResult(url=url, final_url=url, status_code=200,
                          html=pages.get(url, f"<p>{url}</p>"), headers={},
                          throttled=throttled, retry_after=None)

    crawler._fetch = fetch
    crawler.crawl()

    assert crawler.limit.limit == 8


def test_a_429_is_retried_after_retry_after_and_marks_the_result_throttled():
    crawler = Crawler(HOME, max_pages=1, respect_robots=False, retries=1)
    responses = [FakeResponse(429, {"Retry-After": "0"}),
                 FakeResponse(200, {"Content-Type": "text/html"}, "<p>ok</p>")]

    class Session:
        def get(self, url, **kwargs):
            return responses.pop(0)

    crawler.session = Session()
    result = crawler._fetch(HOME)

    assert result.status_code == 200
    assert result.throttled is True
    assert result.retry_after == 0.0


def test_crawl_delay_forces_one_request_at_a_time(monkeypatch):
    robots = "User-agent: *\nCrawl-delay: 2\n"

    class Session:
        headers = CaseInsensitiveDict()

        def get(self, url, **kwargs):
            if url.endswith("/robots.txt"):
                return FakeResponse(200, {"Content-Type": "text/plain"}, robots)
            return FakeResponse(404, {})

        def mount(self, *args):
            pass

    monkeypatch.setattr("app.crawler.crawler.requests.Session", lambda: Session())
    crawler = Crawler(HOME, respect_robots=True, concurrency=32, max_concurrency=64)

    assert crawler.concurrency == 1
    assert crawler.max_concurrency == 1
    assert crawler.delay >= 2


def test_the_connection_pool_matches_the_maximum_concurrency():
    crawler = Crawler(HOME, respect_robots=False, concurrency=32, max_concurrency=64)
    adapter = crawler.session.get_adapter("https://example.com/")
    assert adapter._pool_maxsize == 64
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_crawler_adaptive.py -q`
Expected: FAIL. There's no `max_concurrency` argument and no `throttled`/`retry_after` fields.

- [ ] **Step 3: Implement**

In `apps/backend/app/crawler/crawler.py`:

1. Add the imports `from requests.adapters import HTTPAdapter` and `from app.crawler.throttle import AdaptiveLimit`.

2. `PageResult`: add after `body_hash`:

```python
    # True when the site answered 429/503 at any point while fetching this
    # page (even if a retry then succeeded) -- the signal the limit cuts on.
    throttled: bool = False
    retry_after: Optional[float] = None
```

3. Add a module helper above `class Crawler`:

```python
THROTTLE_CODES = {429, 503}


def _retry_after_seconds(response) -> Optional[float]:
    """Retry-After in its seconds form; the HTTP-date form is ignored."""
    value = response.headers.get("Retry-After") if response is not None else None
    try:
        return max(float(value), 0.0) if value is not None else None
    except (TypeError, ValueError):
        return None
```

4. `Crawler.__init__`: add the parameter `max_concurrency: Optional[int] = None` after `concurrency`, and directly after `self.concurrency = concurrency`:

```python
        # Never above an explicit concurrency unless a ceiling was given: the
        # CLI's --concurrency and tests mean exactly that number.
        self.max_concurrency = max(max_concurrency or concurrency, concurrency)
```

   After `self.session.headers.update(self.headers)`:

```python
        # requests' default pool keeps 10 connections per host; with more
        # workers than that, every surplus request opened (and TLS-shook) a
        # new connection and threw it away.
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=self.max_concurrency)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
```

5. `_load_robots`: after `self.robots_parser = rp`, add:

```python
                # The site's stated rate wins over adaptivity.
                if self.respect_robots:
                    crawl_delay = rp.crawl_delay(self.headers["User-Agent"])
                    if crawl_delay:
                        self.delay = max(self.delay, float(crawl_delay))
                        self.concurrency = 1
                        self.max_concurrency = 1
```

6. `_fetch`: inside the `while attempt <= self.retries:` loop, directly after the 304 block and before `current_url = url`, add:

```python
                if resp.status_code in THROTTLE_CODES:
                    throttled = True
                    retry_after = _retry_after_seconds(resp)
                    if attempt < self.retries:
                        attempt += 1
                        time.sleep(min(retry_after if retry_after is not None else 0.5 * attempt, 60.0))
                        continue
```

   Initialise `throttled = False` and `retry_after = None` next to `redirect_chain = []` at the top of `_fetch`. Pass `throttled=throttled, retry_after=retry_after` in the successful `PageResult(...)` return.

7. `crawl`: replace

```python
        # Bounded so the frontier cannot run far ahead of the work, which is
        # what keeps un-analysed HTML from accumulating.
        max_in_flight = max(self.concurrency * 2, 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as pool:
```

   with

```python
        # The in-flight bound adapts to the site (see throttle.py). It also
        # keeps the frontier from running far ahead of the work, which is what
        # keeps un-analysed HTML from accumulating.
        self.limit = AdaptiveLimit(initial=self.concurrency, maximum=self.max_concurrency)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
```

   Change the admission loop header from `while frontier and len(in_flight) < max_in_flight:` to:

```python
                while (frontier and len(in_flight) < self.limit.limit
                       and time.monotonic() >= self.limit.paused_until):
```

   Replace the `if not in_flight: break` block with:

```python
                if not in_flight:
                    wait = self.limit.paused_until - time.monotonic()
                    if frontier and wait > 0:
                        # Paused by Retry-After with nothing outstanding: wait
                        # out the pause rather than ending the crawl.
                        time.sleep(min(wait, 1.0))
                        continue
                    # Nothing outstanding and nothing admissible: the crawl is
                    # done, whether the frontier emptied or the cap was reached.
                    break
```

   In the `for future in done:` loop, before `self._handle_result(...)`:

```python
                    fetched = future.result()
                    self.limit.record(
                        fetched.response_time_ms,
                        fetched.throttled or fetched.status_code is None
                        or fetched.status_code in THROTTLE_CODES,
                        fetched.retry_after,
                        time.monotonic(),
                    )
```

8. `apps/backend/app/config/config.py`, next to `CRAWL_CONCURRENCY`:

```python
# Ceiling for adaptive concurrency: the crawl starts at CRAWL_CONCURRENCY and
# grows toward this while the site responds well (app/crawler/throttle.py).
CRAWL_MAX_CONCURRENCY = int(os.getenv("CRAWL_MAX_CONCURRENCY", "64"))
```

9. `apps/backend/app/services/audit_service.py`, `run_full_audit`'s `Crawler(...)`: add `max_concurrency=config.CRAWL_MAX_CONCURRENCY,` after `concurrency=config.CRAWL_CONCURRENCY,`.

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_crawler_adaptive.py -v && python -m pytest -q`
Expected: all PASS. `test_slow_pages_do_not_stall_the_other_workers` in `test_crawler_concurrency.py` must still pass. It crawls 30 pages, fewer than one 50-response window, so the limit never moves.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/crawler/crawler.py apps/backend/app/config/config.py apps/backend/app/services/audit_service.py apps/backend/tests/test_crawler_adaptive.py
git commit -m "feat: adaptive crawl concurrency with 429 backoff, Crawl-delay, and a pool to match"
```

---

### Task 6: Measure Step 2 with simulated latency and throttling

**Files:**
- Modify: `apps/backend/perf/crawl_harness.py`

- [ ] **Step 1: Add the options**

In `_SiteHandler`, add class attributes `latency_ms = 0`, `throttle_at = 0`, `_active = 0`, `_lock = threading.Lock()`, `throttled_count = 0`. At the start of `do_GET`:

```python
        cls = type(self)
        with cls._lock:
            cls._active += 1
            over = cls.throttle_at and cls._active > cls.throttle_at
            if over:
                cls.throttled_count += 1
        try:
            if over:
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if cls.latency_ms:
                time.sleep(cls.latency_ms / 1000)
            self._serve()
        finally:
            with cls._lock:
                cls._active -= 1
```

and rename the existing body of `do_GET` to `def _serve(self):`.

In `main`, add the arguments:

```python
    parser.add_argument("--latency-ms", type=int, default=0,
                        help="simulated server response time per request")
    parser.add_argument("--throttle-at", type=int, default=0,
                        help="answer 429 above this many concurrent requests (0 = never)")
    parser.add_argument("--fixed", action="store_true",
                        help="disable adaptive concurrency (max = initial)")
```

set `_SiteHandler.latency_ms = args.latency_ms` and `_SiteHandler.throttle_at = args.throttle_at`, build the crawler the way the API does:

```python
    crawler = Crawler(
        start_url=start_url,
        max_pages=args.pages,
        max_depth=args.depth,
        respect_robots=False,
        concurrency=config.CRAWL_CONCURRENCY,
        max_concurrency=None if args.fixed else config.CRAWL_MAX_CONCURRENCY,
        timeout=10,
        retries=3,
    )
```

(with `from app.config import config`), and after the existing prints:

```python
    print(f"final concurrency   {crawler.limit.limit} (max {crawler.max_concurrency})")
    print(f"429s served         {_SiteHandler.throttled_count}")
```

- [ ] **Step 2: Measure**

Run each and record the numbers in the commit message:

```
python perf/crawl_harness.py --pages 1000 --latency-ms 150 --fixed
python perf/crawl_harness.py --pages 1000 --latency-ms 150
python perf/crawl_harness.py --pages 1000 --latency-ms 150 --throttle-at 16
python perf/crawl_harness.py --pages 1000
```

Expected:
- Adaptive is faster than `--fixed` at 150ms latency.
- With `--throttle-at 16`, all 1,000 pages are crawled and the final concurrency is ≤ 16.
- The plain run stays within its budget.

If adaptive is not faster, report that honestly. Don't tune constants to fit this one harness.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/perf/crawl_harness.py
git commit -m "perf: harness options for simulated latency and throttling

<the four runs' wall clock, final concurrency and 429 counts>"
```
