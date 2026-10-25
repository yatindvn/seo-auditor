# Reuse Unchanged Pages Across Audits (Part B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a re-audit, skip re-analysing pages whose HTML is unchanged (server 304, or identical body hash), while always re-running response-based checks fresh.

**Architecture:** Split `analyze_page` into a cacheable `analyze_html` and an always-fresh `analyze_response`. A per-site SQLite `PageCache` stores HTML analyses keyed by URL, guarded by an analyzer fingerprint and a 30-day age limit. The crawler sends conditional requests from cached validators, turns a 304 into a body-less result with merged headers, and reads a 304 page's links from the cache. The audit reuses cached HTML analyses and writes new ones back.

**Tech Stack:** Python 3 (requests, sqlite3, zlib, pytest), Next.js 14 + TypeScript (vitest).

**Spec:** `docs/superpowers/specs/2026-10-25-page-reuse-design.md`

## Global Constraints

- Branch: `feat/crawl-dedup` (Part B builds on Part A). Backend baseline: 271 passed. Frontend baseline: 50 passed.
- Response-derived results are never reused: status/redirects, `X-Robots-Tag`, security headers, compression, cache headers, TTFB, `Content-Length`.
- A 304's headers are merged over the stored headers case-insensitively (RFC 9111 §4.3.4) before any check reads them.
- Cache entries are usable only when `fingerprint` matches and `analysed_at` is within `PAGE_CACHE_MAX_AGE_DAYS` (default 30).
- `fresh=True`: no validators sent, no cache reads; fresh results are still written.
- The cache never fails an audit: every cache error is logged once and treated as a miss.
- Only the audit's main thread touches the cache; fetch workers read the in-memory `validators` dict only.
- Errored, non-HTML, and Part A alias/duplicate pages are never written to the cache.
- Backend tests: `cd apps/backend && python -m pytest -q`. Frontend: `cd apps/frontend && npx vitest run && npx tsc --noEmit`.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

---

### Task 1: Split the analysis into HTML and response halves

**Files:**
- Modify: `apps/backend/app/auditor/checks.py:138-154` (`check_indexability`)
- Modify: `apps/backend/app/utils/performance.py:28-54` (`analyze_page_weight`)
- Modify: `apps/backend/app/services/page_pipeline.py` (`PageAnalysis`, `analyze_page`; add `HtmlAnalysis`, `analyze_html`, `analyze_response`)
- Test: `apps/backend/tests/test_analysis_split.py` (create), `apps/backend/tests/fixtures/analyze_page_golden.json` (generated)

**Interfaces:**
- Produces:
  - `checks.meta_robots_content(page) -> str` and `checks.robots_issues(robots_header: str, meta_robots: str) -> List[Dict]`. `check_indexability(page)` is unchanged in behaviour.
  - `performance.html_weight(page) -> Dict` with keys `html_size_bytes, dom_node_count, script_tag_count, stylesheet_count, render_blocking_css_count, render_blocking_js_count`.
  - `performance.analyze_page_weight(page, html_part_weight: Optional[Dict] = None) -> Dict`, with the same keys as today.
  - `page_pipeline.HtmlAnalysis` dataclass: `issues, meta, weight, meta_robots_content, dupe_row, keyword_data, internal_links, external_links, signature`, plus `to_json() -> Dict` (no signature) and `HtmlAnalysis.from_json(data, signature=None)`.
  - `page_pipeline.analyze_html(payload) -> HtmlAnalysis`
  - `page_pipeline.analyze_response(payload, html_part) -> PageAnalysis`. It never parses HTML, so it works with `payload.html == ""`.
  - `PageAnalysis.html_part: Optional[HtmlAnalysis] = None`
  - `analyze_page(payload) == analyze_response(payload, analyze_html(payload))`

- [ ] **Step 1: Write the characterisation test (before touching code)**

Create `apps/backend/tests/test_analysis_split.py`:

```python
"""analyze_page splits into a cacheable HTML half and an always-fresh response half.

The golden file was generated from analyze_page *before* the split, so these
tests prove the split changed nothing a caller can see except issue order, which
was never part of the contract and is compared sorted.
"""

import json
from pathlib import Path

import pytest

from app.auditor import checks
from app.services import page_pipeline
from app.services.page_pipeline import PagePayload

GOLDEN = Path(__file__).parent / "fixtures" / "analyze_page_golden.json"

HTML = (
    "<html lang='en'><head><title>Espresso Machines</title>"
    "<meta name='description' content='Reviews of espresso machines'>"
    "<meta name='ROBOTS' content='NoIndex'>"
    "<meta property='og:title' content='Espresso'>"
    "<script src='/a.js'></script><link rel='stylesheet' href='/s.css'></head>"
    "<body><h1>Best Espresso Machines</h1><h2>Reviews</h2>"
    "<p>espresso machine reviews and buying guide with plenty of words to "
    "satisfy the word count checks in this pipeline test fixture.</p>"
    "<img src='/a.png'><img src='/b.png' alt='b'>"
    "<a href='/grinders'>Grinders</a><a href='https://other.example/x'>Off</a>"
    "<a href='http://example.com/insecure'>Insecure</a>"
    "</body></html>"
)

CASES = {
    "plain": dict(headers={}, response_time_ms=10.0),
    "headers_and_slow": dict(
        headers={"X-Robots-Tag": "noindex, nofollow", "Content-Security-Policy": "default-src 'self'",
                 "Strict-Transport-Security": "max-age=1", "Content-Encoding": "gzip",
                 "Cache-Control": "max-age=60", "Content-Length": "1234"},
        response_time_ms=1500.0,
    ),
    "redirected": dict(
        headers={}, response_time_ms=20.0,
        redirect_chain=[{"from": "https://example.com/old", "to": "https://example.com/", "status": 302}],
    ),
    "empty_body": dict(headers={}, html="", response_time_ms=5.0),
}


def _payload(case):
    base = dict(
        url="https://example.com/", final_url="https://example.com/", status_code=200,
        headers={}, html=HTML, depth=0, redirect_chain=[], response_time_ms=10.0,
        content_type="text/html", error=None, compute_signature=True,
    )
    base.update(CASES[case])
    return PagePayload(**base)


def _normalise(analysis):
    data = {
        "issues": sorted(analysis.issues, key=lambda i: (i["code"], i["severity"], i["message"])),
        "meta": analysis.meta,
        "dupe_row": analysis.dupe_row,
        "keyword_data": analysis.keyword_data,
        "internal_links": analysis.internal_links,
        "external_links": analysis.external_links,
        "signature": analysis.signature.hex() if analysis.signature else None,
    }
    return json.loads(json.dumps(data, sort_keys=True, default=str))


def write_golden():
    """Run once, before the split, to capture today's behaviour."""
    GOLDEN.parent.mkdir(exist_ok=True)
    golden = {case: _normalise(page_pipeline.analyze_page(_payload(case))) for case in CASES}
    GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("case", list(CASES))
def test_analyze_page_output_is_unchanged_by_the_split(case):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _normalise(page_pipeline.analyze_page(_payload(case))) == golden[case]


@pytest.mark.parametrize("case", list(CASES))
def test_composing_the_halves_equals_analyze_page(case):
    payload = _payload(case)
    composed = page_pipeline.analyze_response(payload, page_pipeline.analyze_html(payload))
    assert _normalise(composed) == _normalise(page_pipeline.analyze_page(payload))


def test_the_html_half_survives_a_json_round_trip():
    payload = _payload("headers_and_slow")
    part = page_pipeline.analyze_html(payload)
    restored = page_pipeline.HtmlAnalysis.from_json(json.loads(json.dumps(part.to_json())), signature=part.signature)
    assert _normalise(page_pipeline.analyze_response(payload, restored)) == _normalise(
        page_pipeline.analyze_page(payload)
    )


def test_the_response_half_needs_no_html_and_never_parses(monkeypatch):
    """A 304 brings no body. analyze_response must give the full result from the
    cached half plus the new response alone. The expected value is computed
    before parsing is disabled."""
    full = _payload("headers_and_slow")
    expected = _normalise(page_pipeline.analyze_page(full))
    part = page_pipeline.analyze_html(full)

    def no_parsing(*args, **kwargs):
        raise AssertionError("analyze_response parsed HTML")

    monkeypatch.setattr(checks, "_soup", no_parsing)
    monkeypatch.setattr(checks, "_parse", no_parsing)
    bodyless = _payload("headers_and_slow")
    bodyless.html = ""

    assert _normalise(page_pipeline.analyze_response(bodyless, part)) == expected


def test_both_robots_sources_saying_noindex_report_it_once():
    payload = _payload("headers_and_slow")
    analysis = page_pipeline.analyze_page(payload)
    assert [i["code"] for i in analysis.issues].count("NOINDEX") == 1
```

`HtmlAnalysis` and the new functions are referenced through `page_pipeline.` at call time, so this module imports cleanly before the split exists. That is what lets Step 2 capture the golden output from today's code.

- [ ] **Step 2: Generate the golden file from the current code**

Run: `cd apps/backend && python -c "from tests.test_analysis_split import write_golden; write_golden()"`
Expected: `tests/fixtures/analyze_page_golden.json` is created from the unmodified `analyze_page`.

Run: `python -m pytest tests/test_analysis_split.py -q`
Expected: the 4 golden tests and the NOINDEX test PASS, because they run against today's code. The others FAIL with `AttributeError` on `analyze_html` / `HtmlAnalysis`.

- [ ] **Step 3: Split `check_indexability`**

In `apps/backend/app/auditor/checks.py`, replace `check_indexability` with:

```python
def meta_robots_content(page) -> str:
    """The page's robots meta directives, lowercased; "" when absent."""
    soup = _soup(page.html)
    if soup:
        tag = soup.find("meta", attrs={"name": re.compile("robots", re.I)})
        if tag and tag.get("content"):
            return tag["content"].lower()
    return ""


def robots_issues(robots_header: str, meta_robots: str) -> List[Dict]:
    """Indexability from both robots sources together, so a page that says
    noindex in its header *and* its meta tag is reported once."""
    out = []
    combined = f"{robots_header.lower()} {meta_robots}"
    if "noindex" in combined:
        out.append(issue("warning", "NOINDEX", "Page is set to noindex"))
    if "nofollow" in combined:
        out.append(issue("info", "NOFOLLOW", "Page is set to nofollow"))
    return out


def check_indexability(page) -> List[Dict]:
    robots_header = page.headers.get("X-Robots-Tag", "") if page.headers else ""
    return robots_issues(robots_header, meta_robots_content(page))
```

- [ ] **Step 4: Split page weight**

In `apps/backend/app/utils/performance.py`, replace `analyze_page_weight` with:

```python
def html_weight(page) -> Dict:
    """The parts of page weight read from the HTML -- cacheable with it."""
    soup = None
    if page.html:
        try:
            soup = BeautifulSoup(page.html, "lxml")
        except Exception:
            soup = None

    scripts = soup.find_all("script") if soup else []
    styles = soup.find_all("link", rel="stylesheet") if soup else []
    render_blocking_css = [s for s in styles if not s.get("media") or s.get("media") == "all"]
    render_blocking_js = [s for s in scripts if s.get("src") and not (s.get("async") or s.get("defer"))]

    return {
        "html_size_bytes": len(page.html.encode("utf-8")) if page.html else 0,
        "dom_node_count": len(soup.find_all(True)) if soup else 0,
        "script_tag_count": len(scripts),
        "stylesheet_count": len(styles),
        "render_blocking_css_count": len(render_blocking_css),
        "render_blocking_js_count": len(render_blocking_js),
    }


def analyze_page_weight(page, html_part_weight: Optional[Dict] = None) -> Dict:
    """Page weight: HTML-derived counts plus the response's TTFB and length.

    `html_part_weight` is a cached html_weight() for a response with no body
    (a 304); without it the HTML is read from the page.
    """
    html_part = html_part_weight if html_part_weight is not None else html_weight(page)
    return {
        "ttfb_ms": page.response_time_ms,
        "html_size_bytes": html_part["html_size_bytes"],
        "content_length_header": page.headers.get("Content-Length") if page.headers else None,
        "dom_node_count": html_part["dom_node_count"],
        "script_tag_count": html_part["script_tag_count"],
        "stylesheet_count": html_part["stylesheet_count"],
        "render_blocking_css_count": html_part["render_blocking_css_count"],
        "render_blocking_js_count": html_part["render_blocking_js_count"],
    }
```

- [ ] **Step 5: Split `analyze_page`**

In `apps/backend/app/services/page_pipeline.py`:

1. Change the dataclasses import to `from dataclasses import asdict, dataclass, field`.

2. Add above `PageAnalysis`:

```python
@dataclass
class HtmlAnalysis:
    """Everything derived from a page's HTML alone.

    This is the half worth caching across audits: it is the expensive half
    (one parse, ~20 checks), and it stays true for as long as the HTML is
    unchanged. Nothing here may read headers, status, or timing -- those
    belong to analyze_response, which runs fresh every audit.
    """
    issues: List[Dict] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    weight: Dict[str, Any] = field(default_factory=dict)
    meta_robots_content: str = ""
    dupe_row: Dict[str, Any] = field(default_factory=dict)
    keyword_data: List[Dict] = field(default_factory=list)
    internal_links: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)
    signature: Optional[bytes] = None

    def to_json(self) -> Dict[str, Any]:
        """JSON-safe form. The signature is bytes and is stored separately."""
        data = asdict(self)
        data.pop("signature")
        return data

    @classmethod
    def from_json(cls, data: Dict[str, Any], signature: Optional[bytes] = None) -> "HtmlAnalysis":
        return cls(**data, signature=signature)
```

3. Add to `PageAnalysis`, after `failed: bool = False`:

```python
    # The cacheable half this analysis was built from; None for a failure.
    html_part: Optional["HtmlAnalysis"] = None
```

4. Replace the whole body of `analyze_page` with three functions. `analyze_html` is the old body with the four response checks removed (`check_status_and_https`, `check_indexability`, `check_security_headers`, `check_performance_proxies`), `security_headers` and `performance` dropped from `meta`, and the weight computed with `html_weight`:

```python
def analyze_html(payload: PagePayload) -> HtmlAnalysis:
    page = payload  # the checks read .html/.headers/.status_code/.url off this
    page_url = payload.url

    issues: List[Dict] = []
    issues += checks.check_mixed_content(page)
    canon_issues, canonical = checks.check_canonical(page, page_url)
    issues += canon_issues

    title_issues, title = checks.check_title(page)
    issues += title_issues
    desc_issues, desc = checks.check_meta_description(page)
    issues += desc_issues
    heading_issues, h1 = checks.check_headings(page)
    issues += heading_issues
    issues += checks.check_images(page)
    issues += checks.check_links(page)
    issues += checks.check_structured_data(page)
    issues += checks.check_open_graph_twitter(page)
    issues += checks.check_url_structure(page_url)

    content_issues, content_stats = checks.check_content(page)
    issues += content_issues

    issues += checks.check_mobile(page)
    issues += checks.check_accessibility(page)
    issues += checks.check_hreflang(page)
    issues += checks.check_media(page)
    issues += checks.check_js_rendering_signal(page)

    weight = performance.html_weight(page)

    # ... the existing soup block, unchanged, from `soup = checks._soup(payload.html)`
    # through the structured_data loop. Delete `security_headers: Dict[str, Any] = {}`
    # and the `if payload.headers:` block that filled it -- that moves to
    # analyze_response.

    internal_links, external_links = _extract_links(payload.final_url or page_url, soup)
    word_cnt = content_stats.get("word_count", 0)

    meta = {
        # ... the existing meta dict, unchanged, except delete the two entries
        # "performance": weight, and "security_headers": security_headers,
    }

    keyword_data = resolve_keyword_data(
        payload.target_keywords, payload.enable_keyword_analysis, meta, content_stats
    )

    text = content_stats.get("text") or ""
    dupe_row = {
        # ... unchanged
    }

    return HtmlAnalysis(
        issues=issues,
        meta=meta,
        weight=weight,
        meta_robots_content=checks.meta_robots_content(page),
        dupe_row=dupe_row,
        keyword_data=keyword_data,
        internal_links=internal_links,
        external_links=external_links,
        signature=minhash.signature(text) if payload.compute_signature else None,
    )


def analyze_response(payload: PagePayload, html_part: HtmlAnalysis) -> PageAnalysis:
    """The checks that read the response rather than the HTML, merged with an
    HTML analysis -- fresh or cached.

    Never parses HTML, so it runs on a 304's empty body: it is what makes
    status, redirects, security headers, compression, caching and TTFB current
    on every audit while the HTML half is reused.
    """
    page = payload
    issues: List[Dict] = []
    issues += checks.check_status_and_https(page, {})
    robots_header = page.headers.get("X-Robots-Tag", "") if page.headers else ""
    issues += checks.robots_issues(robots_header, html_part.meta_robots_content)
    issues += html_part.issues
    issues += checks.check_security_headers(page)

    weight = performance.analyze_page_weight(page, html_part.weight)
    issues += performance.check_performance_proxies(page, weight)

    security_headers: Dict[str, Any] = {}
    if payload.headers:
        headers_lower = {k.lower(): v for k, v in payload.headers.items()}
        for header in ("strict-transport-security", "content-security-policy",
                       "x-frame-options", "x-content-type-options", "referrer-policy"):
            security_headers[header] = headers_lower.get(header, False)

    meta = {**html_part.meta, "performance": weight, "security_headers": security_headers}

    return PageAnalysis(
        url=payload.url,
        issues=issues,
        meta=meta,
        dupe_row=html_part.dupe_row,
        keyword_data=html_part.keyword_data,
        signature=html_part.signature,
        internal_links=html_part.internal_links,
        external_links=html_part.external_links,
        html_part=html_part,
    )


def analyze_page(payload: PagePayload) -> PageAnalysis:
    return analyze_response(payload, analyze_html(payload))
```

The `# ...` lines above mark where existing code is kept verbatim. They are instructions to move code, not new code. Every line between them must come from the current `analyze_page`.

- [ ] **Step 6: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_analysis_split.py -v && python -m pytest -q`
Expected: all PASS. If an existing test asserts exact issue *order*, it fails here. Change that assertion to compare sorted lists, since issue order was never a contract, and note it in the commit message.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/auditor/checks.py apps/backend/app/utils/performance.py apps/backend/app/services/page_pipeline.py apps/backend/tests/test_analysis_split.py apps/backend/tests/fixtures/analyze_page_golden.json
git commit -m "refactor: split page analysis into a cacheable HTML half and a fresh response half"
```

---

### Task 2: The per-site page cache

**Files:**
- Create: `apps/backend/app/models/page_cache.py`
- Modify: `apps/backend/app/crawler/crawler.py` (add `Validators` dataclass after `PageResult`)
- Modify: `apps/backend/app/config/config.py` (add `PAGE_CACHE_MAX_AGE_DAYS`)
- Modify: `apps/backend/app/models/session_model.py` (add `SessionStore.page_cache_dir`)
- Test: `apps/backend/tests/test_page_cache.py` (create)

**Interfaces:**
- Consumes: `HtmlAnalysis` (Task 1).
- Produces:
  - `crawler.Validators(etag: Optional[str] = None, last_modified: Optional[str] = None, body_hash: Optional[str] = None, headers: Dict = {})`
  - `page_cache.analyzer_fingerprint(enable_keyword_analysis: bool, target_keywords: Optional[List[str]], compute_signature: bool) -> str`
  - `page_cache.cache_file_name(start_url: str) -> str`
  - `PageCache.open(cache_dir: Path, start_url: str, fingerprint: str, max_age_days: int = config.PAGE_CACHE_MAX_AGE_DAYS, clock=time.time) -> Optional[PageCache]`
  - `PageCache.validators() -> Dict[str, Validators]`, `PageCache.get_html_part(url) -> Optional[HtmlAnalysis]`, `PageCache.put(url: str, validators: Validators, html_part: HtmlAnalysis) -> None`, `PageCache.close()`
  - `SessionStore.page_cache_dir -> Path` (equal to `<session dir>/page_cache`)

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_page_cache.py`:

```python
"""The page cache: HTML analyses kept per site, usable only while still valid."""

import time

import pytest

from app.crawler.crawler import Validators
from app.models import page_cache
from app.models.page_cache import PageCache, analyzer_fingerprint, cache_file_name
from app.services.page_pipeline import HtmlAnalysis

START = "https://example.com/"
URL = "https://example.com/a"


def _part(n=1):
    return HtmlAnalysis(
        issues=[{"severity": "info", "code": f"C{n}", "message": "m"}],
        meta={"title": f"T{n}"}, weight={"html_size_bytes": 10},
        meta_robots_content="", dupe_row={"url": URL, "text": "words " * 50},
        keyword_data=[], internal_links=["https://example.com/b"],
        external_links=["https://other.com/"], signature=b"\x01\x02",
    )


def _validators():
    return Validators(etag='"v1"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
                      body_hash="abc", headers={"Content-Security-Policy": "default-src 'self'"})


def test_a_stored_entry_round_trips(tmp_path):
    cache = PageCache.open(tmp_path, START, "fp")
    cache.put(URL, _validators(), _part())

    assert cache.validators()[URL] == _validators()
    part = cache.get_html_part(URL)
    assert part == _part()
    assert part.signature == b"\x01\x02"


def test_entries_survive_reopening(tmp_path):
    PageCache.open(tmp_path, START, "fp").put(URL, _validators(), _part())

    assert URL in PageCache.open(tmp_path, START, "fp").validators()


def test_an_entry_from_another_fingerprint_is_not_usable(tmp_path):
    PageCache.open(tmp_path, START, "old").put(URL, _validators(), _part())

    cache = PageCache.open(tmp_path, START, "new")
    assert cache.validators() == {}
    assert cache.get_html_part(URL) is None


@pytest.mark.parametrize("age_days, usable", [(29, True), (31, False)])
def test_entries_expire_after_max_age(tmp_path, age_days, usable):
    then = 1_000_000_000.0
    PageCache.open(tmp_path, START, "fp", clock=lambda: then).put(URL, _validators(), _part())

    later = PageCache.open(tmp_path, START, "fp", max_age_days=30,
                           clock=lambda: then + age_days * 86400)
    assert (URL in later.validators()) is usable
    assert (later.get_html_part(URL) is not None) is usable


def test_a_corrupt_cache_file_is_ignored_not_fatal(tmp_path):
    (tmp_path / cache_file_name(START)).write_bytes(b"this is not a database" * 100)

    assert PageCache.open(tmp_path, START, "fp") is None


def test_each_site_has_its_own_file():
    assert cache_file_name("https://Example.com/x") == "example.com.db"
    assert cache_file_name("http://localhost:8080/") == "localhost_8080.db"


def test_fingerprint_is_stable_and_follows_the_options():
    base = analyzer_fingerprint(True, ["b", "a"], False)
    assert base == analyzer_fingerprint(True, ["a", "b"], False)
    assert base != analyzer_fingerprint(False, ["a", "b"], False)
    assert base != analyzer_fingerprint(True, ["a"], False)
    assert base != analyzer_fingerprint(True, ["a", "b"], True)


def test_fingerprint_changes_when_a_check_changes(monkeypatch):
    before = analyzer_fingerprint(True, None, False)
    original = page_cache._read_source

    def edited(rel):
        data = original(rel)
        return data + b"\n# edited" if rel == "auditor/checks.py" else data

    monkeypatch.setattr(page_cache, "_read_source", edited)
    assert analyzer_fingerprint(True, None, False) != before


def test_the_cache_lives_beside_the_session_history(isolated_session_dir):
    assert isolated_session_dir.page_cache_dir.name == "page_cache"
    assert isolated_session_dir.page_cache_dir.parent == isolated_session_dir._dir
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_page_cache.py -q`
Expected: FAIL with `ImportError` (`Validators`, `page_cache`).

- [ ] **Step 3: Implement**

1. In `apps/backend/app/crawler/crawler.py`, add directly after the `PageResult` class:

```python
@dataclass
class Validators:
    """What a previous audit learned about a URL, enough to ask the server
    whether it changed: its validators, its body hash, and its headers (a 304
    carries few headers of its own, so the stored ones are merged under it)."""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    body_hash: Optional[str] = None
    headers: Dict = field(default_factory=dict)
```

2. In `apps/backend/app/config/config.py`, add next to `SESSION_DIR`:

```python
# A cached page analysis older than this is redone even if the server says the
# page is unchanged -- a bound on trusting servers that misreport changes.
PAGE_CACHE_MAX_AGE_DAYS = int(os.getenv("PAGE_CACHE_MAX_AGE_DAYS", "30"))
```

3. In `apps/backend/app/models/session_model.py`, add to `SessionStore` after `_path`:

```python
    @property
    def page_cache_dir(self) -> Path:
        """Per-site page caches. A subdirectory, so they share the sessions
        volume (and survive redeploys) without matching the `*.db` glob that
        retention prunes."""
        return self._dir / "page_cache"
```

4. Create `apps/backend/app/models/page_cache.py`:

```python
"""Per-site cache of HTML analyses, reused across audits.

One SQLite file per site. An entry is the HTML half of a page's analysis
(page_pipeline.HtmlAnalysis) plus the validators needed to ask the server
whether the page changed. It is usable only while its analyzer fingerprint
matches -- so editing any check, or auditing with different options, can never
serve a stale result -- and while younger than PAGE_CACHE_MAX_AGE_DAYS.

Every failure here is a cache miss, never an audit failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import urllib.parse as up
import zlib
from pathlib import Path
from typing import Dict, List, Optional

from app.config import config
from app.crawler.crawler import Validators
from app.services.page_pipeline import HtmlAnalysis

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, body_hash TEXT,
  headers_json TEXT, html_blob BLOB, signature BLOB,
  fingerprint TEXT, analysed_at REAL
);
"""

APP_DIR = Path(__file__).resolve().parent.parent
# The code an HTML analysis depends on. A change to any of these files makes
# every cached analysis unusable, with no version number to remember to bump.
FINGERPRINT_SOURCES = (
    "auditor/checks.py",
    "services/page_pipeline.py",
    "utils/performance.py",
    "seo/keyword_extraction.py",
    "analysis/minhash.py",
)


def _read_source(rel: str) -> bytes:
    return (APP_DIR / rel).read_bytes()


def analyzer_fingerprint(
    enable_keyword_analysis: bool,
    target_keywords: Optional[List[str]],
    compute_signature: bool,
) -> str:
    digest = hashlib.sha256()
    for rel in FINGERPRINT_SOURCES:
        digest.update(rel.encode())
        digest.update(_read_source(rel))
    options = json.dumps({
        "keyword_analysis": bool(enable_keyword_analysis),
        "target_keywords": sorted(target_keywords or []),
        "signature": bool(compute_signature),
    }, sort_keys=True)
    digest.update(options.encode())
    return digest.hexdigest()


def cache_file_name(start_url: str) -> str:
    netloc = up.urlsplit(start_url).netloc.lower().replace(":", "_")
    return f"{netloc or 'unknown'}.db"


class PageCache:
    def __init__(self, path: Path, fingerprint: str, max_age_days: int, clock) -> None:
        self._fingerprint = fingerprint
        self._max_age = max_age_days * 86400
        self._clock = clock
        self._warned = False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @classmethod
    def open(cls, cache_dir: Path, start_url: str, fingerprint: str,
             max_age_days: int = config.PAGE_CACHE_MAX_AGE_DAYS,
             clock=time.time) -> Optional["PageCache"]:
        path = Path(cache_dir) / cache_file_name(start_url)
        try:
            return cls(path, fingerprint, max_age_days, clock)
        except Exception as exc:
            logger.warning("Page cache %s unusable, auditing without it: %s", path, exc)
            return None

    def _warn(self, action: str, exc: Exception) -> None:
        if not self._warned:
            logger.warning("Page cache %s failed, continuing without it: %s", action, exc)
            self._warned = True

    def _usable_clause(self):
        return "fingerprint = ? AND analysed_at >= ?", (
            self._fingerprint, self._clock() - self._max_age,
        )

    def validators(self) -> Dict[str, Validators]:
        clause, params = self._usable_clause()
        try:
            rows = self._conn.execute(
                f"SELECT url, etag, last_modified, body_hash, headers_json FROM pages WHERE {clause}",
                params,
            ).fetchall()
        except sqlite3.Error as exc:
            self._warn("read", exc)
            return {}
        return {
            url: Validators(etag=etag, last_modified=last_modified, body_hash=body_hash,
                            headers=json.loads(headers_json or "{}"))
            for url, etag, last_modified, body_hash, headers_json in rows
        }

    def get_html_part(self, url: str) -> Optional[HtmlAnalysis]:
        clause, params = self._usable_clause()
        try:
            row = self._conn.execute(
                f"SELECT html_blob, signature FROM pages WHERE url = ? AND {clause}",
                (url, *params),
            ).fetchone()
            if row is None:
                return None
            data = json.loads(zlib.decompress(row[0]))
            return HtmlAnalysis.from_json(data, signature=row[1])
        except Exception as exc:
            self._warn("read", exc)
            return None

    def put(self, url: str, validators: Validators, html_part: HtmlAnalysis) -> None:
        try:
            blob = zlib.compress(json.dumps(html_part.to_json()).encode("utf-8"))
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?)",
                    (url, validators.etag, validators.last_modified, validators.body_hash,
                     json.dumps(validators.headers or {}), blob, html_part.signature,
                     self._fingerprint, self._clock()),
                )
        except Exception as exc:
            self._warn("write", exc)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_page_cache.py -v && python -m pytest -q`
Expected: all PASS. If `test_a_corrupt_cache_file_is_ignored_not_fatal` fails because SQLite opens the garbage file lazily, keep the `executescript(SCHEMA)` call in `__init__`: it forces the read that raises `sqlite3.DatabaseError`.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/models/page_cache.py apps/backend/app/crawler/crawler.py apps/backend/app/config/config.py apps/backend/app/models/session_model.py apps/backend/tests/test_page_cache.py
git commit -m "feat: per-site page cache of HTML analyses, keyed by an analyzer fingerprint"
```

---

### Task 3: Conditional requests in the crawler

**Files:**
- Modify: `apps/backend/app/crawler/crawler.py` (`PageResult`, `Crawler.__init__`, `_fetch`, `_owner_of`, `_handle_result`; add `fetch_unconditional`, `_merge_headers`)
- Create: `apps/backend/tests/fake_http.py` (shared fake server, reused by Task 4)
- Test: `apps/backend/tests/test_crawler_conditional.py` (create)

**Interfaces:**
- Consumes: `Validators` (Task 2).
- Produces:
  - `PageResult.cache_status: Optional[str] = None` (`"not_modified"` or `"same_hash"`), `PageResult.body_hash: Optional[str] = None`. `body_hash` is set by `_fetch` for every 200 HTML response, and by `_owner_of` when it hashes.
  - `Crawler.validators: Dict[str, Validators]` (default `{}`) and `Crawler.cached_links: Optional[Callable[[str], Optional[Tuple[List[str], List[str]]]]]` (default `None`). Both are plain attributes, set by the audit before `crawl()`.
  - `Crawler._fetch(url, conditional=True)`, `Crawler.fetch_unconditional(url) -> PageResult`.
  - A `not_modified` result reaching `_handle_result` with no cached links is re-fetched unconditionally there, so `on_page` never sees a 304 without a cache entry behind it.
  - `tests/fake_http.py`: `FakeSite(pages: Dict[url, str], etags: bool = True, extra_headers: Dict = None)` with a `.session` to assign to `crawler.session`. It has `.calls: List[Tuple[url, Dict]]`, honours `If-None-Match`, and lets you mutate `.pages` and `.not_modified_headers` between audits.

- [ ] **Step 1: Write the shared fake server**

Create `apps/backend/tests/fake_http.py`:

```python
"""A fake HTTP site for tests that must exercise the crawler's real _fetch:
conditional requests, 304s, and headers -- which replacing _fetch would skip."""

import hashlib
from typing import Dict, List, Optional, Tuple

from requests.structures import CaseInsensitiveDict


class FakeResponse:
    def __init__(self, status_code: int, headers: Dict[str, str], text: str = ""):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers)
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"


class FakeSite:
    """`pages` maps URL -> HTML. Each page's ETag is derived from its HTML, so
    editing a page changes its ETag the way a real server's would."""

    BASE_HEADERS = {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": "default-src 'self'",
        "Strict-Transport-Security": "max-age=31536000",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }

    def __init__(self, pages: Dict[str, str], etags: bool = True,
                 extra_headers: Optional[Dict[str, str]] = None):
        self.pages = dict(pages)
        self.etags = etags
        self.extra_headers = dict(extra_headers or {})
        # What a 304 carries: per RFC 9110 only a few fields; tests can add more.
        self.not_modified_headers: Dict[str, str] = {}
        self.calls: List[Tuple[str, Dict[str, str]]] = []
        self.session = self

    def etag_of(self, url: str) -> str:
        return '"' + hashlib.md5(self.pages[url].encode()).hexdigest() + '"'

    def get(self, url, timeout=None, allow_redirects=False, headers=None, **_):
        self.calls.append((url, dict(headers or {})))
        if url not in self.pages:
            return FakeResponse(404, {"Content-Type": "text/html"}, "")
        response_headers = {**self.BASE_HEADERS, **self.extra_headers}
        if self.etags:
            etag = self.etag_of(url)
            response_headers["ETag"] = etag
            if headers and headers.get("If-None-Match") == etag:
                return FakeResponse(304, {"ETag": etag, **self.not_modified_headers})
        return FakeResponse(200, response_headers, self.pages[url])

    def conditional_calls(self) -> List[str]:
        return [url for url, sent in self.calls
                if "If-None-Match" in sent or "If-Modified-Since" in sent]
```

- [ ] **Step 2: Write the failing tests**

Create `apps/backend/tests/test_crawler_conditional.py`:

```python
"""Conditional requests: ask the server whether a page changed, and treat a
304 as the cached page with today's headers."""

import hashlib

from app.crawler.crawler import Crawler, Validators
from tests.fake_http import FakeSite

HOME = "https://example.com/"
CHILD = "https://example.com/child"


def _sha(html):
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def _crawler(site, max_pages=10):
    crawler = Crawler(HOME, max_pages=max_pages, max_depth=3, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler.session = site.session
    return crawler


def test_validators_turn_into_conditional_headers_only_for_known_urls():
    site = FakeSite({HOME: "<p>home</p>", CHILD: "<p>child</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag='"x"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")}

    crawler._fetch(HOME)
    crawler._fetch(CHILD)

    sent = dict(site.calls)
    assert sent[HOME] == {"If-None-Match": '"x"', "If-Modified-Since": "Mon, 01 Jan 2026 00:00:00 GMT"}
    assert sent[CHILD] == {}


def test_a_304_becomes_the_cached_page_with_merged_headers():
    html = "<p>home</p>"
    site = FakeSite({HOME: html})
    site.not_modified_headers = {"Cache-Control": "max-age=60"}
    crawler = _crawler(site)
    stored = {"content-type": "text/html", "Content-Security-Policy": "default-src 'self'",
              "ETag": '"stale"'}
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME), body_hash=_sha(html), headers=stored)}

    result = crawler._fetch(HOME)

    assert result.status_code == 200
    assert result.html == ""
    assert result.cache_status == "not_modified"
    assert result.body_hash == _sha(html)
    lower = {k.lower(): v for k, v in result.headers.items()}
    assert lower["content-security-policy"] == "default-src 'self'"  # kept from the store
    assert lower["cache-control"] == "max-age=60"                     # added by the 304
    assert lower["etag"] == site.etag_of(HOME)                        # updated by the 304
    assert len([k for k in result.headers if k.lower() == "etag"]) == 1
    assert "text/html" in result.content_type


def test_an_unchanged_body_without_validators_is_recognised_by_its_hash():
    html = "<p>home</p>"
    site = FakeSite({HOME: html}, etags=False)
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(body_hash=_sha(html))}

    result = crawler._fetch(HOME)

    assert result.html == html
    assert result.cache_status == "same_hash"


def test_a_changed_body_is_not_marked_reusable():
    site = FakeSite({HOME: "<p>new</p>"}, etags=False)
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(body_hash=_sha("<p>old</p>"))}

    result = crawler._fetch(HOME)

    assert result.cache_status is None
    assert result.body_hash == _sha("<p>new</p>")


def test_fetch_unconditional_sends_no_validators():
    site = FakeSite({HOME: "<p>home</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME))}

    result = crawler.fetch_unconditional(HOME)

    assert site.calls == [(HOME, {})]
    assert result.html == "<p>home</p>"


def test_a_304_pages_cached_links_still_drive_the_crawl():
    site = FakeSite({HOME: f"<a href='{CHILD}'>c</a>", CHILD: "<p>child</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME))}
    crawler.cached_links = lambda url: ([CHILD], ["https://other.com/"]) if url == HOME else None

    results = crawler.crawl()

    assert results[HOME].cache_status == "not_modified"
    assert CHILD in results
    assert "https://other.com/" in crawler.external_links


def test_a_304_with_nothing_cached_is_fetched_again_in_full():
    site = FakeSite({HOME: "<p>home</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME))}
    crawler.cached_links = lambda url: None
    seen = []

    crawler.crawl(on_page=lambda r: seen.append((r.cache_status, r.html)))

    assert seen == [(None, "<p>home</p>")]


def test_two_304s_with_the_same_stored_body_are_duplicates():
    """Part A's body-hash dedup must still work when neither body was sent."""
    same = "<p>same</p>"
    site = FakeSite({HOME: f"<a href='{CHILD}'>c</a>", CHILD: same, "https://example.com/copy": same})
    crawler = _crawler(site)
    links = {HOME: ([CHILD, "https://example.com/copy"], [])}
    crawler.validators = {
        url: Validators(etag=site.etag_of(url), body_hash=_sha(site.pages[url]),
                        headers={"Content-Type": "text/html"})
        for url in site.pages
    }
    crawler.cached_links = lambda url: links.get(url, ([], []))

    crawler.crawl()

    assert len(crawler.skipped) == 1
    assert next(iter(crawler.skipped.values())).duplicate_of is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_crawler_conditional.py -q`
Expected: FAIL. There's no `cache_status`, no `fetch_unconditional`, and `crawler.validators` is ignored.

- [ ] **Step 4: Implement**

In `apps/backend/app/crawler/crawler.py`:

1. Change the typing import to `from typing import Callable, Dict, List, Optional, Set, Tuple`.

2. Add to `PageResult`, after `found_via`:

```python
    # "not_modified" when the server answered 304, "same_hash" when it sent a
    # body identical to the cached one; None for anything to analyse afresh.
    cache_status: Optional[str] = None
    body_hash: Optional[str] = None
```

3. Add a module-level helper above `class Crawler`:

```python
def _merge_headers(stored: Dict, fresh) -> Dict:
    """A 304's headers laid over the stored response's (RFC 9111 4.3.4).

    Case-insensitive: the store and the 304 may spell a field differently, and
    a plain dict merge would then hold both, with checks reading the stale one.
    """
    merged = dict(stored or {})
    by_lower = {key.lower(): key for key in merged}
    for key, value in dict(fresh).items():
        existing = by_lower.get(key.lower())
        if existing is not None:
            del merged[existing]
        merged[key] = value
        by_lower[key.lower()] = key
    return merged
```

4. In `Crawler.__init__`, after `self._fetched = 0`:

```python
        # Set by the audit from its page cache before crawl(). validators is
        # read by fetch workers but never written during a crawl.
        self.validators: Dict[str, Validators] = {}
        self.cached_links: Optional[Callable[[str], Optional[Tuple[List[str], List[str]]]]] = None
```

   (`Validators` is defined below `PageResult`, which is above `Crawler`, so the name resolves.)

5. Replace `_fetch`'s signature and its first request, and its return of a successful result. The new `_fetch`:

```python
    def _fetch(self, url: str, conditional: bool = True) -> PageResult:
        validators = self.validators.get(url) if conditional else None
        request_headers = {}
        if validators is not None:
            if validators.etag:
                request_headers["If-None-Match"] = validators.etag
            if validators.last_modified:
                request_headers["If-Modified-Since"] = validators.last_modified

        redirect_chain = []
        attempt = 0
        last_exc = None
        while attempt <= self.retries:
            try:
                start = time.time()
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=False,
                                        headers=request_headers or None)
                elapsed = (time.time() - start) * 1000

                if resp.status_code == 304 and validators is not None:
                    # Unchanged: no body, and few headers of its own. The page is
                    # the cached one, with today's headers laid over yesterday's.
                    headers = _merge_headers(validators.headers, resp.headers)
                    content_type = next(
                        (v for k, v in headers.items() if k.lower() == "content-type"), ""
                    )
                    return PageResult(
                        url=url, final_url=url, status_code=200,
                        response_time_ms=round(elapsed, 1), content_type=content_type,
                        html="", headers=headers,
                        cache_status="not_modified", body_hash=validators.body_hash,
                    )

                current_url = url
                current_resp = resp
                hops = 0
                while current_resp.status_code in REDIRECT_CODES and hops < 10:
                    # ... unchanged redirect-following loop ...

                content_type = current_resp.headers.get("Content-Type", "")
                html = ""
                if current_resp.status_code == 200 and "text/html" in content_type:
                    current_resp.encoding = current_resp.encoding or "utf-8"
                    html = current_resp.text

                body_hash = (
                    hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest() if html else None
                )
                cache_status = (
                    "same_hash"
                    if validators is not None and body_hash and body_hash == validators.body_hash
                    else None
                )

                if self.event_callback:
                    # ... unchanged broken_link / redirect events ...

                return PageResult(
                    url=url,
                    final_url=current_url,
                    status_code=current_resp.status_code,
                    redirect_chain=redirect_chain,
                    response_time_ms=round(elapsed, 1),
                    content_type=content_type,
                    html=html,
                    headers=dict(current_resp.headers),
                    cache_status=cache_status,
                    body_hash=body_hash,
                )
            except requests.RequestException as exc:
                # ... unchanged ...
```

   The `# ... unchanged ...` lines keep the existing code exactly. The redirect hops (`self.session.get(current_url, ...)`) send no conditional headers.

6. Add after `_fetch_paced`:

```python
    def fetch_unconditional(self, url: str) -> PageResult:
        """A full fetch, never answered with a 304: for a page whose cached
        analysis turned out to be missing."""
        return self._fetch(url, conditional=False)
```

7. In `_owner_of`, replace the body-hash block's condition and digest line with:

```python
        if (
            (result.html or result.body_hash)
            and result.status_code == 200
            and "text/html" in (result.content_type or "")
        ):
            # A 304 has no body, but carries the hash of the body it stands for.
            digest = result.body_hash or hashlib.sha256(
                result.html.encode("utf-8", errors="ignore")
            ).hexdigest()
            result.body_hash = digest
```

   (The rest of the block, from `first = self.body_owner.get(digest)`, is unchanged.)

8. In `_handle_result`, directly after `result = future.result()`:

```python
        cached = None
        if result.cache_status == "not_modified":
            cached = self.cached_links(url) if self.cached_links else None
            if cached is None:
                # A 304 with nothing behind it in the cache: there is no body
                # to analyse and no links to follow, so fetch it properly.
                result = self.fetch_unconditional(url)
```

   Then replace the link-extraction block (`internal_links, external_links = [], []` through the end of the `if result.html:` loop) with:

```python
        internal_links, external_links = [], []
        if cached is not None:
            cached_internal, cached_external = cached
            internal_links = [self.aliases.get(link, link) for link in cached_internal]
            external_links = list(cached_external)
        elif result.html:
            for link in self._extract_links(result.final_url, result.html):
                normalized = normalize_url(link)
                if same_registrable_domain(normalized, self.root_netloc):
                    # Resolved through known aliases, so the graph points at the
                    # page that represents the URL rather than at a skipped one.
                    internal_links.append(self.aliases.get(normalized, normalized))
                else:
                    external_links.append(normalized)
```

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_crawler_conditional.py -v && python -m pytest -q`
Expected: all PASS. Tests that replace `_fetch` with a one-argument lambda are unaffected, because `_fetch_paced` calls `self._fetch(url)`.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/crawler/crawler.py apps/backend/tests/fake_http.py apps/backend/tests/test_crawler_conditional.py
git commit -m "feat: send conditional requests and treat a 304 as the cached page with fresh headers"
```

---

### Task 4: Reuse cached analyses in the audit

**Files:**
- Modify: `apps/backend/app/services/audit_service.py` (`run_full_audit`, `_build_audit_result`)
- Modify: `apps/backend/app/models/session_db.py` (`cache_status` column + migration)
- Modify: `apps/backend/app/schemas/schemas.py` (`AuditRequestParams.fresh`)
- Modify: `apps/backend/app/api/routes.py` (pass `fresh`; `"reuse"` in `SUMMARY_FIELDS`)
- Modify: `apps/backend/app/cli.py` (`--fresh`)
- Test: `apps/backend/tests/test_page_reuse.py` (create)

**Interfaces:**
- Consumes: `analyze_response`, `HtmlAnalysis`, `PageAnalysis.html_part` (Task 1); `PageCache`, `analyzer_fingerprint`, `SessionStore.page_cache_dir` (Task 2); `Crawler.validators`, `Crawler.cached_links`, `PageResult.cache_status/body_hash` (Task 3); `tests/fake_http.FakeSite` (Task 3).
- Produces:
  - `_build_audit_result(..., fresh: bool = False)`, `run_full_audit(..., fresh: bool = False)`
  - Result and summary key `reuse: {"not_modified": int, "same_hash": int, "analysed": int}`
  - DB `pages.cache_status TEXT`
  - API request field `fresh: bool` (default false); CLI flag `--fresh`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_page_reuse.py`:

```python
"""A re-audit reuses the HTML analysis of unchanged pages and redoes the rest."""

import sqlite3

import pytest

from app.crawler.crawler import Crawler
from app.models.page_cache import cache_file_name
from app.models.session_db import SessionDB
from app.services import audit_service, page_pipeline
from tests.fake_http import FakeSite

HOME = "https://example.com/"


def _site(**kwargs):
    body = "<p>{} has enough words here for the content checks to be satisfied fully</p>"
    pages = {HOME: "<html><head><title>Home</title></head><body>"
                   "<a href='/a'>a</a><a href='/b'>b</a>" + body.format("home") + "</body></html>"}
    for name in ("a", "b"):
        pages[f"https://example.com/{name}"] = (
            f"<html><head><title>Page {name}</title></head><body><h1>{name}</h1>"
            + body.format(name) + "</body></html>"
        )
    return FakeSite(pages, **kwargs)


def _audit(site, session_id, **kwargs):
    crawler = Crawler(HOME, max_pages=10, max_depth=2, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler.session = site.session
    return audit_service._build_audit_result(
        HOME, crawler, progress_callback=None, event_callback=None,
        external_link_check_limit=0, session_id=session_id, **kwargs,
    )


def _issue_codes(result):
    return {url: sorted(i["code"] for i in issues)
            for url, issues in result["page_issues_detail"].items()}


def test_the_first_audit_analyses_every_page():
    result = _audit(_site(), "s1")

    assert result["reuse"] == {"not_modified": 0, "same_hash": 0, "analysed": 3}


def test_a_re_audit_of_an_unchanged_site_analyses_nothing(monkeypatch):
    site = _site()
    first = _audit(site, "s1")

    def no_html_analysis(payload):
        raise AssertionError(f"re-analysed {payload.url}")

    monkeypatch.setattr(page_pipeline, "analyze_html", no_html_analysis)
    second = _audit(site, "s2")

    assert second["reuse"] == {"not_modified": 3, "same_hash": 0, "analysed": 0}
    assert _issue_codes(second) == _issue_codes(first)
    assert set(site.conditional_calls()) == set(site.pages)


def test_a_changed_page_is_analysed_again_and_the_rest_reused():
    site = _site()
    _audit(site, "s1")
    site.pages["https://example.com/a"] = site.pages["https://example.com/a"].replace(
        "<title>Page a</title>", "<title>Page a, rewritten</title>"
    )

    second = _audit(site, "s2")

    assert second["reuse"] == {"not_modified": 2, "same_hash": 0, "analysed": 1}
    assert second["executive_summary"]["pages_crawled"] == 3


def test_without_validators_an_identical_body_is_reused_by_hash():
    site = _site(etags=False)
    _audit(site, "s1")

    second = _audit(site, "s2")

    assert second["reuse"] == {"not_modified": 0, "same_hash": 3, "analysed": 0}


def test_response_checks_run_fresh_on_a_304():
    """The 304 adds Cache-Control the first audit lacked: NO_CACHE_HEADER must
    clear, while the CSP stored from the first audit must not be reported
    missing just because the 304 did not repeat it."""
    site = _site()
    first = _audit(site, "s1")
    assert all("NO_CACHE_HEADER" in codes for codes in _issue_codes(first).values())

    site.not_modified_headers = {"Cache-Control": "max-age=60"}
    second = _audit(site, "s2")

    for codes in _issue_codes(second).values():
        assert "NO_CACHE_HEADER" not in codes
        assert "MISSING_HEADER_CONTENT_SECURITY_POLICY" not in codes


def test_fresh_re_checks_everything_and_sends_no_validators():
    site = _site()
    _audit(site, "s1")
    site.calls.clear()

    second = _audit(site, "s2", fresh=True)

    assert second["reuse"]["analysed"] == 3
    assert site.conditional_calls() == []


def test_changing_the_audit_options_invalidates_the_cache():
    site = _site()
    _audit(site, "s1")

    second = _audit(site, "s2", enable_keyword_analysis=False)

    assert second["reuse"]["analysed"] == 3


def test_a_corrupt_cache_does_not_fail_the_audit(isolated_session_dir):
    site = _site()
    _audit(site, "s1")
    path = isolated_session_dir.page_cache_dir / cache_file_name(HOME)
    path.write_bytes(b"corrupt" * 1000)
    for suffix in ("-wal", "-shm"):
        (path.parent / (path.name + suffix)).unlink(missing_ok=True)

    second = _audit(site, "s2")

    assert second["reuse"]["analysed"] == 3


def test_reused_pages_are_marked_in_the_stored_rows(isolated_session_dir):
    site = _site()
    _audit(site, "s1")
    _audit(site, "s2")

    rows, _ = isolated_session_dir.open_session("s2").get_pages(limit=10)

    assert {row["cache_status"] for row in rows} == {"not_modified"}


def test_a_session_db_without_cache_status_still_opens(tmp_path):
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
          meta_json TEXT, alias_of TEXT, duplicate_of TEXT, found_via TEXT
        );
        INSERT INTO pages (url, depth, status, issue_count, meta_json)
        VALUES ('https://example.com/', 0, 200, 0, '{}');
    """)
    conn.commit()
    conn.close()

    rows, total = SessionDB(path).get_pages()

    assert total == 1
    assert rows[0]["cache_status"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_page_reuse.py -q`
Expected: FAIL with `KeyError: 'reuse'`, an unexpected keyword `fresh`, and `KeyError: 'cache_status'`.

- [ ] **Step 3: Implement storage and plumbing**

1. `apps/backend/app/models/session_db.py`:
   - In `SCHEMA`, change the `pages` table's last line to `meta_json TEXT, alias_of TEXT, duplicate_of TEXT, found_via TEXT, cache_status TEXT`.
   - In `PAGE_COLUMNS`, change `"alias_of", "duplicate_of", "found_via", "issue_count",` to `"alias_of", "duplicate_of", "found_via", "cache_status", "issue_count",`.
   - In the migration loop in `__init__`, change the tuple to `("alias_of", "duplicate_of", "found_via", "cache_status")`.

2. `apps/backend/app/schemas/schemas.py`, `AuditRequestParams`: add after `rank_targets`:

```python
    # Ignore the page cache and analyse every page afresh (results are still
    # written back to it).
    fresh: Optional[bool] = False
```

3. `apps/backend/app/api/routes.py`: add `fresh=params.fresh or False,` to the `run_full_audit(...)` call after `rank_targets=params.rank_targets,`, and add `"reuse"` to `SUMMARY_FIELDS` after `"dedup"`.

4. `apps/backend/app/cli.py`: in the argument parser, next to `--skip-external-links`:

```python
    p.add_argument("--fresh", action="store_true",
                   help="Ignore the page cache and re-analyse every page")
```

   Then pass `fresh=args.fresh,` in `_run_audit`'s `_build_audit_result(...)` call.

5. `apps/backend/app/services/audit_service.py`, `run_full_audit`: add the parameter `fresh: bool = False` after `rank_targets`, and pass `fresh=fresh,` to `_build_audit_result`.

- [ ] **Step 4: Implement reuse in `_build_audit_result`**

In `apps/backend/app/services/audit_service.py`:

1. Add the imports `from app.crawler.crawler import Validators` and `from app.models import page_cache`.

2. Add the parameter `fresh: bool = False` to `_build_audit_result` after `session_id`.

3. Directly after the line `compute_signature = page_cap > analysis.EXACT_PATH_MAX_PAGES`, add:

```python
    # Pages whose HTML is unchanged since the last audit of this site reuse
    # that audit's HTML analysis; only the response checks run again.
    cache = page_cache.PageCache.open(
        session_store.page_cache_dir, url,
        page_cache.analyzer_fingerprint(enable_keyword_analysis, target_keywords, compute_signature),
    )
    reuse_counts = {"not_modified": 0, "same_hash": 0, "analysed": 0}
    if cache is not None and not fresh and hasattr(crawler, "validators"):
        crawler.validators = cache.validators()

        def _cached_links(page_url):
            part = cache.get_html_part(page_url)
            return (part.internal_links, part.external_links) if part else None

        crawler.cached_links = _cached_links
```

4. In `_record`, add to the row dict after `"found_via": result.found_via,`:

```python
            "cache_status": result.cache_status,
```

5. In `_resolve`, after `analyses[url] = resolved`, add:

```python
        page = crawler.results[url]
        # Fresh analyses of 200 HTML pages go back to the cache; reused ones
        # are left as they are, so their age still bounds how long they count.
        if (
            cache is not None
            and resolved.html_part is not None
            and not page.cache_status
            and page.status_code == 200
            and getattr(page, "body_hash", None)
        ):
            cache.put(url, Validators(
                etag=_header(page.headers, "ETag"),
                last_modified=_header(page.headers, "Last-Modified"),
                body_hash=page.body_hash,
                headers=dict(page.headers or {}),
            ), resolved.html_part)
```

   Add a module-level helper near `_match_rank_target`:

```python
def _header(headers, name: str) -> Optional[str]:
    """A response header by name, whatever case the server used."""
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return None
```

6. In `on_page`, directly after the `payload = page_pipeline.PagePayload(...)` assignment, add:

```python
        html_part = None
        if cache is not None and not fresh and result.cache_status:
            html_part = cache.get_html_part(result.url)
        if html_part is not None:
            # Unchanged since the last audit: reuse its HTML half, redo only
            # the response half. In-process -- it parses nothing.
            reuse_counts[result.cache_status] += 1
            _resolve(result.url, page_pipeline.analyze_response(payload, html_part))
            result.html = ""
            return None
        reuse_counts["analysed"] += 1
```

7. In the `finally:` that shuts the pool down, add after it (still inside the same `try`/`finally` structure, as a second statement in `finally`):

```python
        if cache is not None:
            cache.close()
```

8. In `result_data`, after the `"dedup": {...},` entry, add:

```python
        "reuse": reuse_counts,
```

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && python -m pytest tests/test_page_reuse.py -v && python -m pytest -q`
Expected: all PASS.

If `test_a_re_audit_of_an_unchanged_site_analyses_nothing` reports `analysed` > 0, check that `crawler.cached_links` is set before `crawl()` runs, and that `Validators` built in `_resolve` read `ETag` case-insensitively.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/audit_service.py apps/backend/app/models/session_db.py apps/backend/app/schemas/schemas.py apps/backend/app/api/routes.py apps/backend/app/cli.py apps/backend/tests/test_page_reuse.py
git commit -m "feat: reuse the HTML analysis of pages unchanged since the last audit"
```

---

### Task 5: Dashboard: "Re-check every page", UNCHANGED badge, reuse count

**Files:**
- Modify: `packages/shared/src/types/index.ts`
- Modify: `apps/frontend/app/page.tsx` (checkbox state, request field)
- Modify: `apps/frontend/components/pages-table.tsx` (badge)
- Modify: `apps/frontend/app/dashboard/page.tsx` (count)
- Test: `apps/frontend/components/__tests__/pages-table.test.tsx` (add), `apps/frontend/components/__tests__/fresh-audit.test.tsx` (create)

**Interfaces:**
- Consumes: page rows' `cache_status`; summary `reuse`; request `fresh` (Task 4).
- Produces: `ReuseSummary { not_modified: number; same_hash: number; analysed: number }`.

- [ ] **Step 1: Write the failing tests**

Add inside `describe("PagesTable", ...)` in `apps/frontend/components/__tests__/pages-table.test.tsx`:

```tsx
  it("marks a page whose analysis was reused from the last audit", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0, { cache_status: "not_modified" })], 1),
    );

    render(<PagesTable sessionId="sess_1" />);

    const badge = await screen.findByText("UNCHANGED");
    expect(badge).toHaveAttribute("title", "Not modified since the last audit");
  });

  it("says why a same-hash page was reused", async () => {
    vi.spyOn(ApiService, "getPages").mockResolvedValue(
      envelope([row(0, { cache_status: "same_hash" })], 1),
    );

    render(<PagesTable sessionId="sess_1" />);

    const badge = await screen.findByText("UNCHANGED");
    expect(badge).toHaveAttribute("title", "Same HTML as the last audit");
  });
```

Create `apps/frontend/components/__tests__/fresh-audit.test.tsx`:

```tsx
/**
 * "Re-check every page" asks the API to ignore its page cache for one audit.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LandingPage from "@/app/page";
import { ApiService } from "@/services/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({
    startNewAudit: vi.fn(),
    setError: vi.fn(),
    isLoading: false,
    error: null,
  }),
}));

async function submitWith(recheck: boolean) {
  const runAudit = vi.spyOn(ApiService, "runAudit").mockResolvedValue({ session_id: "s" } as never);
  render(<LandingPage />);

  await userEvent.type(screen.getByPlaceholderText("https://example.com"), "https://example.com");
  await userEvent.click(screen.getByText("Advanced Overrides"));
  if (recheck) {
    await userEvent.click(screen.getByLabelText(/re-check every page/i));
  }
  await userEvent.click(screen.getByRole("button", { name: /start seo audit/i }));

  await waitFor(() => expect(runAudit).toHaveBeenCalled());
  return runAudit.mock.calls[0][0];
}

describe("Re-check every page", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("is off by default, so unchanged pages are reused", async () => {
    expect(await submitWith(false)).toMatchObject({ fresh: false });
  });

  it("sends fresh when ticked", async () => {
    expect(await submitWith(true)).toMatchObject({ fresh: true });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/frontend && npx vitest run components/__tests__/pages-table.test.tsx components/__tests__/fresh-audit.test.tsx`
Expected: the badge tests and both fresh-audit tests FAIL. If the URL input's placeholder or the button text differs from what the test assumes, read `app/page.tsx` and match the test to the real text. Don't change the page to fit the test.

- [ ] **Step 3: Implement**

1. `packages/shared/src/types/index.ts`:
   - `PageItem`, after `found_via`: `cache_status?: "not_modified" | "same_hash" | null;`
   - Above `AuditResponse`:

```ts
export interface ReuseSummary {
  not_modified: number;
  same_hash: number;
  analysed: number;
}
```

   - `AuditResponse`, after `dedup?`: `reuse?: ReuseSummary;`
   - `AuditRequestParams`, after `target_keywords?`: `fresh?: boolean;`

2. `apps/frontend/app/page.tsx`:
   - Next to `const [ignoreRobots, setIgnoreRobots] = useState(false);` add `const [recheckAll, setRecheckAll] = useState(false);`
   - In the `ApiService.runAudit({...})` call, after `ignore_robots: ignoreRobots,` add `fresh: recheckAll,`
   - Directly after the "Ignore robots.txt" `<label>...</label>` block, add:

```tsx
                <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border/50 bg-muted/20 p-3 hover:bg-muted/40 transition-colors">
                  <input
                    type="checkbox"
                    checked={recheckAll}
                    onChange={(e) => setRecheckAll(e.target.checked)}
                    className="h-4 w-4 rounded border-input bg-background text-primary focus:ring-primary"
                    disabled={isLoading}
                    aria-label="Re-check every page"
                  />
                  <div>
                    <p className="text-sm font-semibold">Re-check every page</p>
                    <p className="text-xs text-muted-foreground">Analyse every page again, even ones unchanged since the last audit of this site</p>
                  </div>
                </label>
```

3. `apps/frontend/components/pages-table.tsx`, after the SITEMAP badge:

```tsx
                        {page.cache_status && (
                          <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-600 text-[9px] font-semibold border border-sky-500/20" title={page.cache_status === "not_modified" ? "Not modified since the last audit" : "Same HTML as the last audit"}>
                            UNCHANGED
                          </span>
                        )}
```

4. `apps/frontend/app/dashboard/page.tsx`:
   - Below `const skippedUrls = ...` add `const unchangedPages = (auditData.reuse?.not_modified ?? 0) + (auditData.reuse?.same_hash ?? 0);`
   - In the "All Crawled Pages" `CardTitle`, after the `skippedUrls` span, add:

```tsx
{unchangedPages > 0 && <span className="ml-2 text-xs font-normal text-muted-foreground">{unchangedPages} pages unchanged since the last audit</span>}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `cd packages/shared && npm run build && cd ../../apps/frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, no type errors. Then `git status --short` should show no build output under `packages/shared/src`.

- [ ] **Step 5: Commit**

```bash
git add packages/shared/src/types/index.ts apps/frontend/app/page.tsx apps/frontend/components/pages-table.tsx apps/frontend/app/dashboard/page.tsx apps/frontend/components/__tests__/pages-table.test.tsx apps/frontend/components/__tests__/fresh-audit.test.tsx
git commit -m "feat: re-check-every-page option, UNCHANGED badge, and reuse count in the dashboard"
```

---

### Task 6: Re-audit a real site twice

**Files:** none (verification only)

- [ ] **Step 1:** Using a scratch `SESSION_DIR`, run from `apps/backend`: `python -m app.cli https://books.toscrape.com/ --max-pages 30 --max-depth 2 --skip-external-links --json > first.json`
- [ ] **Step 2:** Run the same command again into `second.json`.
- [ ] **Step 3:** Compare `reuse` between the two. Expected: the first has `analysed == 30`. The second has `not_modified + same_hash` close to 30 and much less `elapsed_seconds`. Every page should have the same issue codes in both, except response-derived ones like `SLOW_TTFB`, which may legitimately differ.
- [ ] **Step 4:** Run once more with `--fresh` and confirm `reuse.analysed == 30`.
