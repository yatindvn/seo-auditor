# Content Explorer (Phase 7.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a topic, show the top 10 organic results with:
- our on-page analysis (words, outline, schema, links, readability, issues)
- bulk backlink counts
- a summary of what the results share

Searches are cached for 7 days.

**Architecture:**
- `app/content_explorer/pages.py`: fetches each result and turns it into facts, plus a dry run.
- `bulk_metrics` is added to both backlink providers.
- `app/content_explorer/explore.py`: orchestration, the summary and the cache. The cache is one table, `content_searches` (migration 0011).
- An API router, and a global `/content` page.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, requests, pytest; Next.js 14, Recharts, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-31-content-explorer-design.md`

## Global Constraints

- **SERP:** the existing SERP provider fetches the top 10 with `depth=10`, under `SERP_DAILY_CAP`. At the cap it returns 429; any other SERP failure returns 502. Neither saves anything.
- **Backlinks:**
  - `POST /v3/backlinks/bulk_backlinks/live` and `POST /v3/backlinks/bulk_referring_domains/live` with `{"targets": [...]}`
  - each takes one unit of `DATAFORSEO_BACKLINKS_DAILY_CAP`
  - a backlinks failure only adds a note
- **Pages:** 15 s timeout, 1 retry, 4 at a time; the first 30 H2/H3 headings, text cut to 120 characters; at most 10 schema types.
- **Cache:** 7 days, live searches only. `refresh=true` skips it. Every search is saved.
- **Topic:** trimmed, lowercased, spaces collapsed, 2–80 characters. The country is 2 letters and upper case; the language is 2 letters and lower case. Anything else returns 422.
- **Commits:** the full backend suite must exit 0 before each commit.

---

### Task 1: Bulk backlink counts

**Files:**
- Modify: `apps/backend/app/backlinks/provider.py`
- Test: `apps/backend/tests/test_backlinks_bulk.py`

**Interfaces:**
- Produces: `DataForSeoBacklinks.bulk_metrics(urls) -> Dict[str, Tuple[Optional[int], Optional[int]]]`, which maps each URL to `(backlinks, referring_domains)`. `DryRunBacklinks.bulk_metrics` has the same shape.

- [ ] **Step 1: Write the failing test**

```python
"""Bulk backlink counts for many URLs: two DataForSEO requests, capped."""

from unittest.mock import MagicMock

import pytest

from app.backlinks.provider import DataForSeoBacklinks, DryRunBacklinks
from app.providers.serp import ProviderSkipped


def resp(body):
    r = MagicMock(status_code=200)
    r.json.return_value = body
    return r


def ok(items):
    return resp({"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"items": items}]}]})


def test_two_requests_cover_every_url_and_match_trailing_slashes():
    http = MagicMock()
    http.post.side_effect = [
        ok([{"target": "https://a.com/x", "backlinks": 120}, {"target": "https://b.com/", "backlinks": 7}]),
        ok([{"target": "https://a.com/x", "referring_domains": 30}, {"target": "https://b.com", "referring_domains": 2}]),
    ]
    p = DataForSeoBacklinks("l", "p", cap=10, http=http)
    out = p.bulk_metrics(["https://a.com/x", "https://b.com/", "https://c.com/"])
    assert out == {"https://a.com/x": (120, 30), "https://b.com/": (7, 2), "https://c.com/": (None, None)}
    paths = [call.args[0] for call in http.post.call_args_list]
    assert paths == ["https://api.dataforseo.com/v3/backlinks/bulk_backlinks/live",
                     "https://api.dataforseo.com/v3/backlinks/bulk_referring_domains/live"]
    assert http.post.call_args_list[0].kwargs["json"] == [{"targets": ["https://a.com/x", "https://b.com/", "https://c.com/"]}]


def test_no_urls_no_call_and_the_cap_stops_it():
    http = MagicMock()
    assert DataForSeoBacklinks("l", "p", cap=10, http=http).bulk_metrics([]) == {}
    with pytest.raises(ProviderSkipped):
        DataForSeoBacklinks("l", "p", cap=0, http=http).bulk_metrics(["https://a.com/"])
    http.post.assert_not_called()


def test_dry_run_is_stable():
    d = DryRunBacklinks()
    first = d.bulk_metrics(["https://a.com/x", "https://b.com/"])
    assert first == d.bulk_metrics(["https://a.com/x", "https://b.com/"])
    assert all(isinstance(b, int) and isinstance(r, int) and b >= r for b, r in first.values())
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd apps/backend && python -m pytest tests/test_backlinks_bulk.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'bulk_metrics'`.

- [ ] **Step 3: Implement**

Add to the path constants:

```python
BULK_BACKLINKS = "/v3/backlinks/bulk_backlinks/live"
BULK_REFERRING_DOMAINS = "/v3/backlinks/bulk_referring_domains/live"


def _url_key(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()
```

Add to `DataForSeoBacklinks` (after `intersection`):

```python
    def bulk_metrics(self, urls: List[str]) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        """Backlinks and referring domains for many URLs: two requests in all."""
        if not urls:
            return {}
        task = {"targets": list(urls)}
        links = {_url_key(i.get("target")): _int(i.get("backlinks")) for i in _items(self._result(BULK_BACKLINKS, task))}
        domains = {_url_key(i.get("target")): _int(i.get("referring_domains"))
                   for i in _items(self._result(BULK_REFERRING_DOMAINS, task))}
        return {u: (links.get(_url_key(u)), domains.get(_url_key(u))) for u in urls}
```

Add to `DryRunBacklinks`:

```python
    def bulk_metrics(self, urls: List[str]) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        out = {}
        for u in urls:
            s = _seed(u)
            domains = 3 + s % 300
            out[u] = (domains * (2 + s % 9), domains)
        return out
```

Add `Tuple` to the `typing` import.

- [ ] **Step 4: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_backlinks_bulk.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add app/backlinks/provider.py tests/test_backlinks_bulk.py
git commit -m "feat(content-explorer): bulk backlink counts for many URLs (2 capped requests)"
```

---

### Task 2: Page facts

**Files:**
- Create: `apps/backend/app/content_explorer/__init__.py`, `apps/backend/app/content_explorer/pages.py`
- Test: `apps/backend/tests/test_content_pages.py`

**Interfaces:**
- Consumes: `page_pipeline.analyze_page`, `PagePayload`, `Crawler`, `checks.readability_flesch`, `SerpItem`.
- Produces:
  - `empty_row(item) -> dict`
  - `schema_types(structured_data) -> List[str]`
  - `page_facts(item, page) -> dict`
  - `fetch_results(items, fetch=None) -> List[dict]`
  - `DryRunPages().results(items, topic) -> List[dict]`

  Each row has the keys `position, url, domain, title, status, error, word_count, h1, outline, schema_types, images, internal_links, external_links, readability, issues, backlinks, referring_domains`.

- [ ] **Step 1: Write the failing test**

```python
"""Turning a top result into facts: outline, schema, counts, failures."""

from app.content_explorer.pages import DryRunPages, empty_row, fetch_results, page_facts, schema_types
from app.crawler.crawler import PageResult
from app.providers.serp import SerpItem

HTML = """<html><head><title>Rare Books Guide</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Article"},{"@type":["BreadcrumbList","Article"]}]}</script>
<script type="application/ld+json">[{"@type":"FAQPage"}]</script>
<script type="application/ld+json">{not json</script>
</head><body><h1>Rare books</h1><h2>What makes a book rare</h2><h3>First editions</h3><h2>Where to buy</h2>
<p>""" + "Collectors look for condition and provenance. " * 40 + """</p>
<img src="a.png" alt="a"><a href="/more">more</a><a href="https://other.org/">other</a></body></html>"""

ITEM = SerpItem(1, "https://books.example.com/rare", "books.example.com", "SERP title")


def test_schema_types_walk_graphs_and_lists_and_skip_bad_json():
    blocks = [{"type": "JSON-LD", "raw": '{"@graph":[{"@type":"Article"},{"@type":["BreadcrumbList","Article"]}]}'},
              {"type": "JSON-LD", "raw": '[{"@type":"FAQPage"}]'}, {"type": "JSON-LD", "raw": "{bad"}]
    assert schema_types(blocks) == ["Article", "BreadcrumbList", "FAQPage"]
    assert schema_types(None) == []


def test_facts_from_a_fetched_page():
    row = page_facts(ITEM, PageResult(url=ITEM.url, final_url=ITEM.url, status_code=200, html=HTML,
                                      headers={"content-type": "text/html"}))
    assert row["title"] == "Rare Books Guide" and row["h1"] == "Rare books" and row["status"] == 200
    assert row["outline"] == [{"level": 2, "text": "What makes a book rare"}, {"level": 3, "text": "First editions"},
                              {"level": 2, "text": "Where to buy"}]
    assert row["schema_types"] == ["Article", "BreadcrumbList", "FAQPage"]
    assert row["word_count"] > 200 and row["images"] == 1 and row["internal_links"] == 1 and row["external_links"] == 1
    assert isinstance(row["readability"], float) and isinstance(row["issues"], int) and row["error"] is None
    assert row["backlinks"] is None and row["referring_domains"] is None


def test_failures_keep_serp_fields():
    blocked = page_facts(ITEM, PageResult(url=ITEM.url, final_url=ITEM.url, status_code=403, html="<p>no</p>"))
    assert blocked["error"] == "HTTP 403" and blocked["status"] == 403 and blocked["word_count"] is None
    assert blocked["title"] == "SERP title" and blocked["outline"] == []
    down = page_facts(ITEM, PageResult(url=ITEM.url, final_url=ITEM.url, status_code=None, error="ConnectTimeout"))
    assert down["error"] == "ConnectTimeout"


def test_fetch_results_keeps_order_and_survives_exceptions():
    items = [ITEM, SerpItem(2, "https://boom.example/", "boom.example", "Boom")]

    def fetch(url):
        if "boom" in url:
            raise RuntimeError("x")
        return PageResult(url=url, final_url=url, status_code=200, html=HTML)

    rows = fetch_results(items, fetch=fetch)
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[1]["error"] == "fetch failed (RuntimeError)" and rows[0]["h1"] == "Rare books"


def test_dry_run_pages_are_stable_and_varied():
    items = [SerpItem(i, f"https://site{i}.example/rare-books", f"site{i}.example", f"rare books #{i}") for i in range(1, 11)]
    a = DryRunPages().results(items, "rare books")
    assert a == DryRunPages().results(items, "rare books")
    assert len(a) == 10 and any(r["schema_types"] for r in a)
    assert all(r["outline"] and "rare books" in r["outline"][0]["text"] for r in a if r["error"] is None)
    assert empty_row(items[0])["position"] == 1
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_content_pages.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`app/content_explorer/__init__.py`:

```python
"""Content Explorer (Phase 7.2): what the top results for a topic look like."""
```

`app/content_explorer/pages.py`:

```python
"""Each top result fetched once and run through the audit's own page analysis."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.auditor import checks
from app.crawler.crawler import Crawler, PageResult
from app.providers.serp import SerpItem
from app.services import page_pipeline

WORKERS = 4
MAX_OUTLINE = 30
MAX_HEADING = 120
MAX_SCHEMA = 10


def empty_row(item: SerpItem) -> Dict[str, Any]:
    return {"position": item.position, "url": item.url, "domain": item.domain, "title": item.title or None,
            "status": None, "error": None, "word_count": None, "h1": None, "outline": [], "schema_types": [],
            "images": None, "internal_links": None, "external_links": None, "readability": None, "issues": None,
            "backlinks": None, "referring_domains": None}


def schema_types(structured_data) -> List[str]:
    found: List[str] = []

    def walk(node) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            kind = node.get("@type")
            for value in kind if isinstance(kind, list) else [kind]:
                if isinstance(value, str) and value and value not in found:
                    found.append(value)
            if "@graph" in node:
                walk(node["@graph"])

    for block in structured_data or []:
        if not isinstance(block, dict) or block.get("type") != "JSON-LD":
            continue
        try:
            walk(json.loads(block.get("raw") or ""))
        except (ValueError, TypeError):
            continue
    return found[:MAX_SCHEMA]


def fetch_page(url: str) -> PageResult:
    """One page, fetched the way an audit fetches it."""
    crawler = Crawler(start_url=url, max_pages=1, max_depth=0, timeout=15, retries=1)
    return crawler._fetch(url, conditional=False)


def _round(value: Optional[float]) -> Optional[float]:
    return round(float(value), 1) if value is not None else None


def page_facts(item: SerpItem, page: PageResult) -> Dict[str, Any]:
    row = empty_row(item)
    row["status"] = page.status_code
    if page.error or page.status_code is None:
        row["error"] = page.error or "no response"
        return row
    if page.status_code >= 400:
        row["error"] = f"HTTP {page.status_code}"
        return row
    analysis = page_pipeline.analyze_page(page_pipeline.PagePayload(
        url=item.url, final_url=page.final_url or item.url, status_code=page.status_code, headers=page.headers or {},
        html=page.html or "", response_time_ms=page.response_time_ms, content_type=page.content_type or "",
        enable_keyword_analysis=False))
    meta = analysis.meta
    outline = [{"level": h["level"], "text": (h.get("text") or "")[:MAX_HEADING]}
               for h in meta.get("heading_hierarchy") or [] if h.get("level") in (2, 3)]
    row.update(title=meta.get("title") or item.title or None, word_count=meta.get("word_count"), h1=meta.get("h1"),
               outline=outline[:MAX_OUTLINE], schema_types=schema_types(meta.get("structured_data")),
               images=meta.get("images_count"), internal_links=meta.get("internal_links_count"),
               external_links=meta.get("external_links_count"),
               readability=_round(checks.readability_flesch(analysis.dupe_row.get("text") or "")),
               issues=sum(1 for i in analysis.issues if i.get("severity") in ("error", "warning")))
    return row


def fetch_results(items: List[SerpItem], fetch=None) -> List[Dict[str, Any]]:
    fetch = fetch or fetch_page

    def one(item: SerpItem) -> Dict[str, Any]:
        try:
            return page_facts(item, fetch(item.url))
        except Exception as exc:
            row = empty_row(item)
            row["error"] = f"fetch failed ({type(exc).__name__})"
            return row

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(one, items))


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


_SCHEMAS = ["Article", "Product", "FAQPage", "BreadcrumbList", "Organization", "Review", "HowTo"]
_H2 = ["What is", "Best", "How to choose", "Prices of", "Reviews of", "Where to buy", "History of", "FAQ about"]


class DryRunPages:
    """Stable made-up facts: the dry-run SERP's URLs can't be fetched."""

    def results(self, items: List[SerpItem], topic: str) -> List[Dict[str, Any]]:
        rows = []
        for item in items:
            s = _seed(item.url)
            row = empty_row(item)
            if s % 10 == 7:
                row.update(status=403, error="HTTP 403")
                rows.append(row)
                continue
            outline = []
            for n in range(3 + s % 6):
                outline.append({"level": 2, "text": f"{_H2[(s + n) % len(_H2)]} {topic}"})
                if (s >> n) % 3 == 0:
                    outline.append({"level": 3, "text": f"Tips {n + 1}"})
            types = list(dict.fromkeys(_SCHEMAS[(s >> k) % len(_SCHEMAS)] for k in (0, 4, 8)[: 1 + s % 3]))
            row.update(status=200, title=item.title or None, word_count=600 + s % 2400, h1=(item.title or topic),
                       outline=outline[:MAX_OUTLINE], schema_types=types, images=2 + s % 20, internal_links=20 + s % 80,
                       external_links=s % 15, readability=round(40 + (s % 400) / 10, 1), issues=s % 6)
            rows.append(row)
        return rows
```

- [ ] **Step 4: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_content_pages.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add app/content_explorer tests/test_content_pages.py
git commit -m "feat(content-explorer): page facts from our analysis (outline, schema, counts), dry run"
```

---

### Task 3: Explore, summary and cache

**Files:**
- Create: `apps/backend/app/content_explorer/explore.py`, `apps/backend/alembic/versions/0011_content_searches.py`, `apps/backend/tests/test_content_explore.py`
- Modify: `apps/backend/app/db/models.py`, `apps/backend/tests/test_db_schema.py`

**Interfaces:**
- Produces:
  - `ContentSearch` model
  - `normalize(topic, country, language) -> Tuple[str, str, str]`, raising `ValueError`
  - `summarize(rows) -> dict`
  - `explore(topic, country="US", language="en", refresh=False, serp=None, backlinks=None, fetch=None, factory=None, now=None) -> dict`
  - `get_search(search_id, factory=None) -> Optional[dict]`
  - `recent(limit=10, factory=None) -> List[dict]`

- [ ] **Step 1: Write the failing test**

```python
"""Content Explorer: SERP -> pages -> backlinks -> summary, cached 7 days."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.content_explorer.explore import explore, get_search, normalize, recent, summarize
from app.crawler.crawler import PageResult
from app.db.engine import get_session_factory
from app.db.models import ContentSearch
from app.providers.dry_run import DryRunProvider
from app.providers.serp import ProviderError, ProviderSkipped, SerpItem, SerpResult

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
PAGE = "<html><head><title>{t}</title></head><body><h1>{t}</h1><h2>Best rare books</h2><h2>Rare book prices</h2><p>" + "word " * 300 + "</p></body></html>"


class LiveSerp:
    name = "dataforseo"

    def __init__(self, exc=None):
        self.calls, self.exc = 0, exc

    def search(self, query):
        self.calls += 1
        if self.exc:
            raise self.exc
        return SerpResult([SerpItem(i, f"https://s{i}.com/p", f"s{i}.com", f"S{i}") for i in range(1, 13)], self.name)


class Links:
    dry_run = False

    def __init__(self, exc=None):
        self.exc = exc

    def bulk_metrics(self, urls):
        if self.exc:
            raise self.exc
        return {u: (100 * n, 10 * n) for n, u in enumerate(urls, start=1)}


def fetch(url):
    return PageResult(url=url, final_url=url, status_code=200, html=PAGE.format(t=url))


def count():
    with get_session_factory()() as s:
        return s.scalar(select(func.count()).select_from(ContentSearch))


def test_normalize():
    assert normalize("  Rare   BOOKS ", "us", "EN") == ("rare books", "US", "en")
    for bad in (("a", "US", "en"), ("x" * 81, "US", "en"), ("ok topic", "USA", "en"), ("ok topic", "US", "e1")):
        with pytest.raises(ValueError):
            normalize(*bad)


def test_summary_math():
    rows = [{"word_count": 100, "schema_types": ["Article", "FAQPage"], "referring_domains": 5,
             "outline": [{"level": 2, "text": "Best rare books"}, {"level": 2, "text": "Rare rare"}, {"level": 3, "text": "Shipping"}]},
            {"word_count": 300, "schema_types": ["Article"], "referring_domains": None, "outline": [{"level": 2, "text": "Rare prices"}]},
            {"word_count": 900, "schema_types": [], "referring_domains": 15, "outline": []},
            {"word_count": None, "schema_types": [], "referring_domains": 25, "outline": [{"level": 2, "text": "ignored"}]}]
    s = summarize(rows)
    assert s["median_words"] == 300 and s["median_referring_domains"] == 15
    assert s["schema_counts"] == {"Article": 2, "FAQPage": 1}
    assert s["common_h2_terms"][0] == {"term": "rare", "count": 2}
    assert {"term": "shipping", "count": 1} not in s["common_h2_terms"]
    assert summarize([])["median_words"] is None


def test_live_search_is_analysed_saved_and_cached():
    serp = LiveSerp()
    first = explore("Rare Books", serp=serp, backlinks=Links(), fetch=fetch, now=NOW)
    assert first["cached"] is False and first["dry_run"] is False and len(first["results"]) == 10
    assert first["results"][0]["h1"] == "https://s1.com/p" and first["results"][2]["referring_domains"] == 30
    assert first["summary"]["median_words"] > 300 and first["summary"]["common_h2_terms"][0]["term"] == "rare"
    again = explore("rare books", serp=serp, backlinks=Links(), fetch=fetch, now=NOW + timedelta(days=6))
    assert again["cached"] is True and again["id"] == first["id"] and serp.calls == 1
    fresh = explore("rare books", refresh=True, serp=serp, backlinks=Links(), fetch=fetch, now=NOW + timedelta(days=6))
    assert fresh["cached"] is False and serp.calls == 2
    stale = explore("rare books", serp=serp, backlinks=Links(), fetch=fetch, now=NOW + timedelta(days=14))
    assert stale["cached"] is False and serp.calls == 3


def test_dry_run_is_saved_but_never_served_from_cache():
    a = explore("rare books", serp=DryRunProvider(), backlinks=Links(), now=NOW)
    b = explore("rare books", serp=DryRunProvider(), backlinks=Links(), now=NOW)
    assert a["dry_run"] and b["dry_run"] and not b["cached"] and a["id"] != b["id"]
    assert get_search(a["id"])["cached"] is True and get_search(9999) is None
    assert [r["id"] for r in recent()] == [b["id"], a["id"]]


def test_serp_failures_save_nothing_and_backlink_failures_only_note():
    with pytest.raises(ProviderSkipped):
        explore("rare books", serp=LiveSerp(ProviderSkipped("daily cap")), backlinks=Links(), fetch=fetch, now=NOW)
    with pytest.raises(ProviderError):
        explore("rare books", serp=LiveSerp(RuntimeError("boom")), backlinks=Links(), fetch=fetch, now=NOW)
    assert count() == 0
    r = explore("rare books", serp=LiveSerp(), backlinks=Links(ProviderSkipped("daily cap of 0")), fetch=fetch, now=NOW)
    assert r["notes"] == ["Backlinks skipped: daily cap of 0"] and r["results"][0]["word_count"] > 0
    assert r["results"][0]["backlinks"] is None
```

Add `"content_searches"` to `TABLES` in `tests/test_db_schema.py`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_content_explore.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Model and migration**

Append to `app/db/models.py`:

```python
class ContentSearch(Base):
    """A Content Explorer search (Phase 7.2), reused for 7 days when live."""
    __tablename__ = "content_searches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(80), index=True)
    country: Mapped[str] = mapped_column(String(2))
    language: Mapped[str] = mapped_column(String(2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    result_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
```

`alembic/versions/0011_content_searches.py`:

```python
"""content searches

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-31 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('content_searches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic', sa.String(length=80), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('language', sa.String(length=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('result_json', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_searches_topic'), 'content_searches', ['topic'], unique=False)
    op.create_index(op.f('ix_content_searches_created_at'), 'content_searches', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_content_searches_created_at'), table_name='content_searches')
    op.drop_index(op.f('ix_content_searches_topic'), table_name='content_searches')
    op.drop_table('content_searches')
```

- [ ] **Step 4: `app/content_explorer/explore.py`**

```python
"""A topic's top results: SERP, our page analysis, bulk backlinks, a summary.
Live searches are reused for 7 days; dry-run ones are kept but never reused."""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select

from app.backlinks.provider import get_backlink_provider
from app.content_explorer.pages import DryRunPages, fetch_results
from app.db.engine import get_session_factory
from app.db.models import ContentSearch, as_utc, utcnow
from app.providers import registry
from app.providers.serp import ProviderError, ProviderSkipped, SerpQuery

CACHE_DAYS = 7
RESULTS = 10
STOP_WORDS = {"the", "and", "for", "with", "you", "your", "are", "how", "what", "why", "when", "where", "who",
              "which", "can", "does", "from", "that", "this", "these", "those", "into", "about", "our", "all",
              "best", "top", "not", "but", "has", "have", "will", "more", "most", "its", "their", "them", "they"}


def normalize(topic: str, country: str, language: str) -> Tuple[str, str, str]:
    topic = " ".join((topic or "").lower().split())
    country, language = (country or "").strip().upper(), (language or "").strip().lower()
    if not 2 <= len(topic) <= 80:
        raise ValueError("topic must be 2-80 characters")
    if not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[a-z]{2}", language):
        raise ValueError("country and language must be 2-letter codes")
    return topic, country, language


def _median(values: List[Optional[float]]) -> Optional[int]:
    present = [v for v in values if v is not None]
    return round(statistics.median(present)) if present else None


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    fetched = [r for r in rows if r.get("word_count") is not None]
    schema = Counter(t for r in fetched for t in set(r.get("schema_types") or []))
    terms: Counter = Counter()
    for r in fetched:
        words = {w for h in r.get("outline") or [] if h.get("level") == 2
                 for w in re.findall(r"[a-z]{3,}", (h.get("text") or "").lower()) if w not in STOP_WORDS}
        terms.update(words)
    return {"median_words": _median([r["word_count"] for r in fetched]),
            "median_referring_domains": _median([r.get("referring_domains") for r in rows]),
            "schema_counts": dict(sorted(schema.items(), key=lambda kv: (-kv[1], kv[0]))),
            "common_h2_terms": [{"term": t, "count": c} for t, c in sorted(terms.items(), key=lambda kv: (-kv[1], kv[0]))[:15]]}


def _json(row: ContentSearch, cached: bool) -> Dict[str, Any]:
    return {"id": row.id, "topic": row.topic, "country": row.country, "language": row.language,
            "created_at": as_utc(row.created_at).isoformat(), "cached": cached, "dry_run": row.dry_run,
            **(row.result_json or {})}


def explore(topic: str, country: str = "US", language: str = "en", refresh: bool = False, serp=None,
            backlinks=None, fetch=None, factory=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    topic, country, language = normalize(topic, country, language)
    factory = factory or get_session_factory()
    now = now or utcnow()
    if not refresh:
        with factory() as session:
            hit = session.scalars(select(ContentSearch).where(
                ContentSearch.topic == topic, ContentSearch.country == country, ContentSearch.language == language,
                ContentSearch.dry_run.is_(False), ContentSearch.created_at >= now - timedelta(days=CACHE_DAYS),
                ContentSearch.created_at <= now,
            ).order_by(desc(ContentSearch.created_at), desc(ContentSearch.id)).limit(1)).first()
            if hit is not None:
                return _json(hit, cached=True)

    serp = serp if serp is not None else registry.get_serp_provider()
    try:
        items = serp.search(SerpQuery(topic, country, language, depth=RESULTS)).items[:RESULTS]
    except (ProviderSkipped, ProviderError):
        raise
    except Exception as exc:
        raise ProviderError(f"SERP request failed ({type(exc).__name__})") from exc
    live_serp = registry.is_live(serp)
    rows = fetch_results(items, fetch=fetch) if live_serp else DryRunPages().results(items, topic)

    backlinks = backlinks if backlinks is not None else get_backlink_provider()
    notes: List[str] = []
    metrics: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    try:
        metrics = backlinks.bulk_metrics([r["url"] for r in rows]) if rows else {}
    except ProviderSkipped as exc:
        notes.append(f"Backlinks skipped: {exc}")
    except Exception as exc:
        notes.append(f"Backlinks failed ({type(exc).__name__})")
    for r in rows:
        r["backlinks"], r["referring_domains"] = metrics.get(r["url"], (None, None))

    dry = not live_serp or bool(getattr(backlinks, "dry_run", False))
    with factory.begin() as session:
        row = ContentSearch(topic=topic, country=country, language=language, created_at=now, dry_run=dry,
                            result_json={"summary": summarize(rows), "results": rows, "notes": notes})
        session.add(row)
        session.flush()
        return _json(row, cached=False)


def get_search(search_id: int, factory=None) -> Optional[Dict[str, Any]]:
    with (factory or get_session_factory())() as session:
        row = session.get(ContentSearch, search_id)
        return _json(row, cached=True) if row else None


def recent(limit: int = 10, factory=None) -> List[Dict[str, Any]]:
    with (factory or get_session_factory())() as session:
        rows = session.scalars(select(ContentSearch).order_by(desc(ContentSearch.created_at), desc(ContentSearch.id))
                               .limit(limit)).all()
        return [{"id": r.id, "topic": r.topic, "country": r.country, "language": r.language,
                 "created_at": as_utc(r.created_at).isoformat(), "dry_run": r.dry_run} for r in rows]
```

- [ ] **Step 5: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_content_explore.py tests/test_db_schema.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add app/content_explorer/explore.py app/db/models.py alembic/versions/0011_content_searches.py tests/test_content_explore.py tests/test_db_schema.py
git commit -m "feat(content-explorer): explore a topic (SERP, pages, bulk backlinks, summary), 7-day cache (migration 0011)"
```

---

### Task 4: API

**Files:**
- Create: `apps/backend/app/api/content_explorer.py`, `apps/backend/tests/test_content_api.py`
- Modify: `apps/backend/app/main.py`

**Interfaces:**
- Produces:
  - `POST /api/content-explorer`
  - `GET /api/content-explorer/recent`, which returns `{items}`
  - `GET /api/content-explorer/{id}`
  - `GET /api/content-explorer/{id}/csv`

- [ ] **Step 1: Write the failing test**

```python
"""Content Explorer over HTTP (dry-run SERP and backlinks)."""

import pytest
from fastapi.testclient import TestClient

from app.config import config
from app.content_explorer import explore as explore_mod
from app.main import app
from app.providers.serp import ProviderError, ProviderSkipped


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "SERP_PROVIDER", "")
    monkeypatch.setattr(config, "GOOGLE_CSE_API_KEY", "")
    return TestClient(app)


def test_search_reopen_recent_and_csv(client):
    r = client.post("/api/content-explorer", json={"topic": "Rare Books"})
    assert r.status_code == 200
    body = r.json()
    assert body["topic"] == "rare books" and body["dry_run"] is True and len(body["results"]) == 10
    assert body["summary"]["median_words"] is not None
    again = client.get(f"/api/content-explorer/{body['id']}").json()
    assert again["cached"] is True and again["results"] == body["results"]
    assert client.get("/api/content-explorer/recent").json()["items"][0]["id"] == body["id"]
    csv = client.get(f"/api/content-explorer/{body['id']}/csv")
    lines = csv.text.splitlines()
    assert csv.headers["content-type"].startswith("text/csv") and lines[0].startswith("# DRY RUN")
    assert lines[1].startswith("position,url,domain,title") and len(lines) == 12
    assert client.get("/api/content-explorer/9999").status_code == 404
    assert client.get("/api/content-explorer/9999/csv").status_code == 404


def test_errors(client, monkeypatch):
    assert client.post("/api/content-explorer", json={"topic": "x"}).status_code == 422
    assert client.post("/api/content-explorer", json={"topic": "ok topic", "country": "USA"}).status_code == 422

    class Raiser:
        name = "dataforseo"

        def __init__(self, exc):
            self.exc = exc

        def search(self, query):
            raise self.exc

    monkeypatch.setattr(explore_mod.registry, "get_serp_provider", lambda: Raiser(ProviderSkipped("daily cap of 50 reached")))
    r = client.post("/api/content-explorer", json={"topic": "rare books"})
    assert r.status_code == 429 and "daily cap" in r.json()["detail"]
    monkeypatch.setattr(explore_mod.registry, "get_serp_provider", lambda: Raiser(ProviderError("DataForSEO 500")))
    assert client.post("/api/content-explorer", json={"topic": "rare books"}).status_code == 502
    assert client.get("/api/content-explorer/recent").json()["items"] == []
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_content_api.py -q`
Expected: FAIL with 404s or an import error.

- [ ] **Step 3: `app/api/content_explorer.py`**

```python
"""Content Explorer (Phase 7.2): the top results for a topic, analysed."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.keywords import _csv, _csv_response
from app.content_explorer import explore as explore_mod
from app.providers.serp import ProviderError, ProviderSkipped

router = APIRouter()

CSV_COLUMNS = ["position", "url", "domain", "title", "status", "error", "word_count", "h1", "h2_count", "schema_types",
               "images", "internal_links", "external_links", "readability", "issues", "referring_domains", "backlinks"]


class SearchIn(BaseModel):
    topic: str = Field(..., max_length=200)
    country: str = Field("US", max_length=8)
    language: str = Field("en", max_length=8)
    refresh: bool = False


@router.post("/content-explorer")
def search(body: SearchIn):
    try:
        return explore_mod.explore(body.topic, body.country, body.language, refresh=body.refresh)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ProviderSkipped as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/content-explorer/recent")
def recent():
    return {"items": explore_mod.recent()}


def _found(search_id: int):
    found = explore_mod.get_search(search_id)
    if found is None:
        raise HTTPException(status_code=404, detail="search not found")
    return found


@router.get("/content-explorer/{search_id}")
def get_search(search_id: int):
    return _found(search_id)


@router.get("/content-explorer/{search_id}/csv")
def search_csv(search_id: int):
    found = _found(search_id)
    rows = []
    for r in found["results"]:
        values = {**r, "h2_count": sum(1 for h in r.get("outline") or [] if h.get("level") == 2),
                  "schema_types": ";".join(r.get("schema_types") or [])}
        rows.append(["" if values.get(c) is None else values.get(c) for c in CSV_COLUMNS])
    slug = "-".join(found["topic"].split())[:60] or "content"
    return _csv_response(_csv(found["dry_run"], CSV_COLUMNS, rows), f"content-{slug}.csv")
```

In `app/main.py`, after the AI Visibility router lines:

```python
from app.api.content_explorer import router as content_explorer_router  # noqa: E402
app.include_router(content_explorer_router, prefix="/api")
```

- [ ] **Step 4: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_content_api.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add app/api/content_explorer.py app/main.py tests/test_content_api.py
git commit -m "feat(content-explorer): API (search, reopen, recent, CSV)"
```

---

### Task 5: Frontend

**Files:**
- Modify:
  - `packages/shared/src/types/platform.ts`
  - `apps/frontend/services/platform.ts`
  - `components/platform/global-nav.tsx`
  - `components/platform/ai-charts.tsx` (move `Frame` out)
- Create:
  - `components/platform/chart-frame.tsx`
  - `lib/content.ts` (+ `lib/__tests__/content.test.ts`)
  - `components/platform/content-charts.tsx`
  - `components/platform/content-results.tsx`
  - `app/content/page.tsx`
  - `components/__tests__/content-explorer-page.test.tsx`

**Interfaces:**
- Produces:
  - types `ContentResult`, `ContentSummary`, `ContentSearchResult`, `ContentRecent`
  - `Platform.contentSearch`, `contentRecent`, `contentGet`, `contentCsvUrl`
  - `ago(iso, now?)` and `topSchema(summary)`

- [ ] **Step 1: Shared pieces**

Append to `packages/shared/src/types/platform.ts`:

```ts
// Content Explorer (backend Phase 7.2).
export interface ContentResult {
  position: number; url: string; domain: string; title: string | null; status: number | null; error: string | null;
  word_count: number | null; h1: string | null; outline: { level: number; text: string }[]; schema_types: string[];
  images: number | null; internal_links: number | null; external_links: number | null; readability: number | null;
  issues: number | null; backlinks: number | null; referring_domains: number | null;
}
export interface ContentSummary {
  median_words: number | null; median_referring_domains: number | null;
  schema_counts: Record<string, number>; common_h2_terms: { term: string; count: number }[];
}
export interface ContentSearchResult {
  id: number; topic: string; country: string; language: string; created_at: string; cached: boolean; dry_run: boolean;
  notes: string[]; summary: ContentSummary; results: ContentResult[];
}
export interface ContentRecent { id: number; topic: string; country: string; language: string; created_at: string; dry_run: boolean }
```

In `services/platform.ts`, import the types and add after `exploreCsvUrl`:

```ts
  contentSearch: (body: { topic: string; country?: string; language?: string; refresh?: boolean }) =>
    request<ContentSearchResult>("/content-explorer", post(body)),
  contentRecent: () => request<{ items: ContentRecent[] }>("/content-explorer/recent"),
  contentGet: (id: number) => request<ContentSearchResult>(`/content-explorer/${id}`),
  contentCsvUrl: (id: number) => `${API_BASE_URL}/api/content-explorer/${id}/csv`,
```

`components/platform/chart-frame.tsx` (the `Frame` from `ai-charts.tsx`, now shared; `ai-charts.tsx` imports it as `Frame`):

```tsx
"use client";

import React from "react";

export function ChartFrame({ title, asTable, onToggle, children }: { title: string; asTable: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        <button type="button" onClick={onToggle} className="shrink-0 rounded-full border px-3 py-1 text-xs active:scale-95">{asTable ? "Show as chart" : "Show as table"}</button>
      </div>
      {children}
    </section>
  );
}
```

`lib/content.ts`:

```ts
import type { ContentSummary } from "@seo-auditor/shared";

export function ago(iso: string, now: number = Date.now()): string {
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export function topSchema(summary: ContentSummary): { type: string; count: number } | null {
  const entries = Object.entries(summary.schema_counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return entries.length ? { type: entries[0][0], count: entries[0][1] } : null;
}

export const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString());
```

`lib/__tests__/content.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { ago, num, topSchema } from "@/lib/content";

describe("content helpers", () => {
  it("says how long ago", () => {
    const now = Date.parse("2026-10-31T12:00:00Z");
    expect(ago("2026-10-31T12:00:00Z", now)).toBe("just now");
    expect(ago("2026-10-31T11:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-10-31T10:00:00Z", now)).toBe("2 h ago");
    expect(ago("2026-10-27T12:00:00Z", now)).toBe("4 d ago");
  });
  it("picks the top schema type and formats numbers", () => {
    expect(topSchema({ median_words: 1, median_referring_domains: null, schema_counts: { FAQPage: 2, Article: 6, Product: 6 }, common_h2_terms: [] }))
      .toEqual({ type: "Article", count: 6 });
    expect(topSchema({ median_words: null, median_referring_domains: null, schema_counts: {}, common_h2_terms: [] })).toBeNull();
    expect(num(null)).toBe("—");
    expect(num(1200)).toBe((1200).toLocaleString());
  });
});
```

`components/platform/global-nav.tsx`: add `{ href: "/content", label: "Content Explorer" },` after Keywords Explorer.

Rebuild shared with `cd packages/shared && npx tsc`.

- [ ] **Step 2: Write the failing page test** (`components/__tests__/content-explorer-page.test.tsx`)

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ContentPage from "@/app/content/page";
import { Platform } from "@/services/platform";

const row = (position: number, over: object = {}) => ({
  position, url: `https://s${position}.com/p`, domain: `s${position}.com`, title: `Page ${position}`, status: 200, error: null,
  word_count: 1000 + position, h1: `H ${position}`, outline: [{ level: 2, text: "Best rare books" }, { level: 3, text: "First editions" }],
  schema_types: ["Article"], images: 3, internal_links: 20, external_links: 4, readability: 55.5, issues: 2,
  backlinks: 500, referring_domains: 40, ...over });
const search = (over: object = {}) => ({
  id: 7, topic: "rare books", country: "US", language: "en", created_at: new Date(Date.now() - 2 * 3600e3).toISOString(),
  cached: false, dry_run: false, notes: [],
  summary: { median_words: 1500, median_referring_domains: 40, schema_counts: { Article: 6, FAQPage: 2 }, common_h2_terms: [{ term: "rare", count: 8 }] },
  results: [row(1), row(2, { status: 403, error: "HTTP 403", word_count: null, outline: [], schema_types: [] })],
  ...over });

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "contentRecent").mockResolvedValue({ items: [{ id: 3, topic: "old topic", country: "US", language: "en", created_at: "2026-10-30T10:00:00Z", dry_run: false }] });
});

describe("Content Explorer", () => {
  it("searches and shows tiles, results and terms", async () => {
    const run = vi.spyOn(Platform, "contentSearch").mockResolvedValue(search() as any);
    render(<ContentPage />);
    expect(screen.getByText(/≈ \$0\.05–0\.08 per new search/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Topic"), "rare books");
    await userEvent.click(screen.getByRole("button", { name: "Explore" }));
    expect(run).toHaveBeenCalledWith({ topic: "rare books", country: "US", language: "en" });
    expect(await screen.findByText("1,500")).toBeInTheDocument();
    expect(screen.getByText("Article")).toBeInTheDocument();
    expect(screen.getByText(/used by 6 of 1 fetched/)).toBeInTheDocument();
    expect(screen.getByText(/Couldn't fetch \(HTTP 403\)/)).toBeInTheDocument();
    expect(screen.getByText("rare")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /export csv/i })).toHaveAttribute("href", expect.stringContaining("/api/content-explorer/7/csv"));
  });

  it("shows cached state, refreshes, and opens recent searches", async () => {
    vi.spyOn(Platform, "contentGet").mockResolvedValue(search({ cached: true }) as any);
    const run = vi.spyOn(Platform, "contentSearch").mockResolvedValue(search() as any);
    render(<ContentPage />);
    await userEvent.click(await screen.findByRole("button", { name: "old topic" }));
    expect(await screen.findByText(/fetched 2 h ago \(cached\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(run).toHaveBeenCalledWith({ topic: "rare books", country: "US", language: "en", refresh: true });
  });

  it("expands a row's outline and has chart tables", async () => {
    vi.spyOn(Platform, "contentSearch").mockResolvedValue(search() as any);
    render(<ContentPage />);
    await userEvent.type(screen.getByLabelText("Topic"), "rare books");
    await userEvent.click(screen.getByRole("button", { name: "Explore" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show outline: Page 1" }));
    const outline = screen.getByRole("list", { name: "Outline of Page 1" });
    expect(within(outline).getByText("First editions")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /show as table/i })[0]);
    expect(screen.getByRole("cell", { name: "#1" })).toBeInTheDocument();
  });

  it("dry run shows the banner and no cost; errors show", async () => {
    vi.spyOn(Platform, "contentSearch").mockResolvedValueOnce(search({ dry_run: true, notes: ["Backlinks skipped: cap"] }) as any);
    render(<ContentPage />);
    await userEvent.type(screen.getByLabelText("Topic"), "rare books");
    await userEvent.click(screen.getByRole("button", { name: "Explore" }));
    expect(await screen.findByRole("note")).toBeInTheDocument();
    expect(screen.getByText("Dry run: no cost")).toBeInTheDocument();
    expect(screen.getByText("Backlinks skipped: cap")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run and watch it fail**

Run: `cd apps/frontend && npx vitest run lib/__tests__/content.test.ts components/__tests__/content-explorer-page.test.tsx`
Expected: FAIL (the modules don't exist yet).

- [ ] **Step 4: Components and page**

`components/platform/content-charts.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ContentResult, ContentSummary } from "@seo-auditor/shared";

import { ChartFrame } from "@/components/platform/chart-frame";
import { num } from "@/lib/content";
import { SERIES_LIGHT } from "@/lib/platform-charts";

const axis = { fontSize: 12, fill: "hsl(var(--muted-foreground))" };
const tooltip = { borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 };

export function WordsChart({ results }: { results: ContentResult[] }) {
  const [asTable, setAsTable] = useState(false);
  const data = results.filter((r) => r.word_count != null).map((r) => ({ label: `#${r.position}`, words: r.word_count as number }));
  return (
    <ChartFrame title="Words per result" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Position</th><th className="py-1">Words</th></tr></thead>
          <tbody>{data.map((d) => <tr key={d.label}><td className="py-1">{d.label}</td><td className="py-1 tabular-nums">{num(d.words)}</td></tr>)}</tbody></table>
      ) : (
        <div className="h-56 w-full" role="img" aria-label="Word count per result">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} />
              <YAxis tick={axis} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltip} />
              <Bar dataKey="words" name="Words" fill={SERIES_LIGHT[0]} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartFrame>
  );
}

export function SchemaChart({ summary }: { summary: ContentSummary }) {
  const [asTable, setAsTable] = useState(false);
  const data = Object.entries(summary.schema_counts).map(([type, count]) => ({ type, count }));
  return (
    <ChartFrame title="Schema types used" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {data.length === 0 ? <p className="text-sm text-muted-foreground">None of the fetched results use JSON-LD.</p> : asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Type</th><th className="py-1">Results</th></tr></thead>
          <tbody>{data.map((d) => <tr key={d.type}><td className="py-1">{d.type}</td><td className="py-1 tabular-nums">{d.count}</td></tr>)}</tbody></table>
      ) : (
        <div className="w-full" style={{ height: Math.max(120, data.length * 36) }} role="img" aria-label="Schema types across results">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
              <XAxis type="number" allowDecimals={false} tick={axis} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="type" width={120} tick={axis} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltip} />
              <Bar dataKey="count" name="Results" fill={SERIES_LIGHT[1]} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartFrame>
  );
}
```

`components/platform/content-results.tsx`:

```tsx
"use client";

import { Fragment, useState } from "react";
import { ExternalLink } from "lucide-react";
import type { ContentResult } from "@seo-auditor/shared";

import { num } from "@/lib/content";

export function ContentResults({ results }: { results: ContentResult[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
          <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th><th className="py-2 pr-4 font-medium">Words</th>
          <th className="py-2 pr-4 font-medium">H2s</th><th className="py-2 pr-4 font-medium">Schema</th>
          <th className="py-2 pr-4 font-medium">Ref. domains</th><th className="py-2 pr-4 font-medium">Backlinks</th>
          <th className="py-2 pr-4 font-medium">Readability</th><th className="py-2 font-medium">Issues</th></tr></thead>
        <tbody className="divide-y">
          {results.map((r) => {
            const label = r.title || r.domain;
            const isOpen = open === r.position;
            const h2s = r.outline.filter((h) => h.level === 2).length;
            return (
              <Fragment key={r.position}>
                <tr className="align-top">
                  <td className="sticky left-0 max-w-[220px] bg-card py-2 pr-4 sm:max-w-[340px]">
                    <div className="flex items-start gap-2">
                      <span className="tabular-nums text-muted-foreground">{r.position}</span>
                      <div className="min-w-0">
                        {r.outline.length > 0 ? (
                          <button type="button" onClick={() => setOpen(isOpen ? null : r.position)} aria-expanded={isOpen}
                                  aria-label={`Show outline: ${label}`} className="text-left font-medium hover:text-primary">{label}</button>
                        ) : <span className="font-medium">{label}</span>}
                        <a href={/^https?:\/\//i.test(r.url) ? r.url : undefined} target="_blank" rel="noopener noreferrer"
                           className="flex items-center gap-1 break-all text-xs text-muted-foreground hover:text-primary">{r.domain}<ExternalLink className="h-3 w-3 shrink-0" aria-hidden /></a>
                      </div>
                    </div>
                  </td>
                  {r.error ? <td colSpan={7} className="py-2 text-muted-foreground">Couldn&apos;t fetch ({r.error}){r.referring_domains != null ? ` · ${num(r.referring_domains)} referring domains` : ""}</td> : (
                    <>
                      <td className="py-2 pr-4 tabular-nums">{num(r.word_count)}</td>
                      <td className="py-2 pr-4 tabular-nums">{h2s}</td>
                      <td className="py-2 pr-4"><div className="flex flex-wrap gap-1">{r.schema_types.length ? r.schema_types.map((t) => (
                        <span key={t} className="rounded-full border px-2 py-0.5 text-[11px]">{t}</span>)) : <span className="text-muted-foreground">—</span>}</div></td>
                      <td className="py-2 pr-4 tabular-nums">{num(r.referring_domains)}</td>
                      <td className="py-2 pr-4 tabular-nums">{num(r.backlinks)}</td>
                      <td className="py-2 pr-4 tabular-nums">{r.readability ?? "—"}</td>
                      <td className="py-2 tabular-nums">{num(r.issues)}</td>
                    </>
                  )}
                </tr>
                {isOpen && (
                  <tr><td colSpan={8} className="bg-muted/30 px-3 py-3">
                    <ul aria-label={`Outline of ${label}`} className="space-y-1 text-sm">
                      {r.outline.map((h, i) => (
                        <li key={i} className={h.level === 3 ? "pl-6 text-muted-foreground" : "font-medium"}>
                          <span className="mr-2 text-[11px] text-muted-foreground">H{h.level}</span>{h.text}</li>
                      ))}
                    </ul>
                  </td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

`app/content/page.tsx`:

```tsx
"use client";

import { FormEvent, useState } from "react";
import type { ContentSearchResult } from "@seo-auditor/shared";

import { EmptyState } from "@/components/platform/async-state";
import { SchemaChart, WordsChart } from "@/components/platform/content-charts";
import { ContentResults } from "@/components/platform/content-results";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { KpiTile } from "@/components/platform/kpi-tile";
import { PageHeader } from "@/components/platform/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ago, num, topSchema } from "@/lib/content";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function ContentPage() {
  const [topic, setTopic] = useState("");
  const [country, setCountry] = useState("US");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ContentSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recent = useApi(() => Platform.contentRecent(), [result?.id]);

  const go = async (fn: () => Promise<ContentSearchResult>) => {
    setRunning(true); setError(null);
    try { setResult(await fn()); } catch (err) { setError(err instanceof ApiError ? err.detail : String(err)); }
    finally { setRunning(false); }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (topic.trim()) go(() => Platform.contentSearch({ topic, country, language: "en" }));
  };

  const fetched = result ? result.results.filter((r) => r.word_count != null).length : 0;
  const schema = result ? topSchema(result.summary) : null;

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title="Content Explorer" description="What the top 10 results for a topic look like: length, headings, schema and backlinks." />
      <form onSubmit={submit} className="space-y-3 rounded-[18px] border bg-card p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <label className="flex-1 space-y-1 text-sm"><span className="text-xs text-muted-foreground">Topic</span>
            <Input aria-label="Topic" placeholder="rare books" value={topic} maxLength={80} onChange={(e) => setTopic(e.target.value)} className="rounded-full" />
          </label>
          <label className="space-y-1 text-sm"><span className="text-xs text-muted-foreground">Country</span>
            <Input aria-label="Country" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="w-20 rounded-full" />
          </label>
          <Button type="submit" className="rounded-full active:scale-95" disabled={running || !topic.trim()}>{running ? "Exploring…" : "Explore"}</Button>
        </div>
        <p className="text-xs text-muted-foreground">{result?.dry_run ? "Dry run: no cost" : "≈ $0.05–0.08 per new search · cached 7 days (free)"}</p>
        {recent.data && recent.data.items.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Recent:</span>
            {recent.data.items.map((r) => (
              <button key={r.id} type="button" onClick={() => go(() => Platform.contentGet(r.id))}
                      className="rounded-full border px-2.5 py-0.5 hover:bg-muted active:scale-95">{r.topic}</button>
            ))}
          </div>
        )}
      </form>

      {error && <div role="alert" className="rounded-[18px] border border-rose-200 bg-rose-50/60 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-400">{error}</div>}
      {!result && !error && <EmptyState title="Enter a topic" text="You'll see the top 10 results analysed with the same checks as a site audit, plus their backlinks." />}

      {result && (
        <div className="space-y-6">
          <DryRunBanner show={result.dry_run} message="Preview data. The SERP or backlink provider isn't live, so these results are made up." />
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <p className="min-w-0 flex-1">Top {result.results.length} for <strong>&ldquo;{result.topic}&rdquo;</strong> · {result.country} · fetched {ago(result.created_at)}{result.cached ? " (cached)" : ""}</p>
            <Button type="button" variant="outline" className="rounded-full active:scale-95" disabled={running}
                    onClick={() => go(() => Platform.contentSearch({ topic: result.topic, country: result.country, language: result.language, refresh: true }))}>Refresh</Button>
            <a href={Platform.contentCsvUrl(result.id)} className="rounded-full border px-4 py-2 text-sm hover:bg-muted">Export CSV</a>
          </div>
          {result.notes.map((n) => <p key={n} className="text-sm text-muted-foreground">{n}</p>)}
          <div className="grid gap-4 sm:grid-cols-3">
            <KpiTile label="Median words" value={num(result.summary.median_words)} hint={`across ${fetched} fetched results`} />
            <KpiTile label="Top schema type" value={schema ? schema.type : "—"} hint={schema ? `used by ${schema.count} of ${fetched} fetched` : "no JSON-LD found"} />
            <KpiTile label="Median referring domains" value={num(result.summary.median_referring_domains)} hint="per ranking URL" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <WordsChart results={result.results} />
            <SchemaChart summary={result.summary} />
          </div>
          <section className="min-w-0 rounded-[18px] border bg-card p-5">
            <h2 className="mb-3 font-semibold tracking-tight">Results</h2>
            <ContentResults results={result.results} />
          </section>
          {result.summary.common_h2_terms.length > 0 && (
            <section className="min-w-0 rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Common H2 terms <span className="text-xs font-normal text-muted-foreground">(pages using each)</span></h2>
              <ul className="flex flex-wrap gap-2 text-[13px]">{result.summary.common_h2_terms.map((t) => (
                <li key={t.term} className="rounded-full border px-3 py-1"><span>{t.term}</span> <span className="tabular-nums text-muted-foreground">{t.count}</span></li>))}</ul>
            </section>
          )}
        </div>
      )}
    </main>
  );
}
```

`row(2)` in the test has `word_count: null`, so fetched = 1 and the hint reads "used by 6 of 1 fetched". The test only checks the wording; real data never has a count higher than the number of fetched results.

- [ ] **Step 5: Run and pass, gated, then commit**

```bash
npx vitest run > /tmp/fe.txt 2>&1; echo "vitest exit=$?"; grep -E "Tests " /tmp/fe.txt
npx tsc --noEmit; echo "tsc exit=$?"; npx next lint 2>&1 | grep -c "Error:"
(cd ../backend && python -m pytest -q > /tmp/t.txt 2>&1; echo "pytest exit=$?")
git add packages/shared/src apps/frontend
git commit -m "feat(frontend): Content Explorer page (search, tiles, charts, results with outlines, CSV)"
```

---

### Task 6: Docs and the dry-run live check

- [ ] **Step 1: Docs**
  - `.env.example`: extend the `DATAFORSEO_BACKLINKS_DAILY_CAP` comment ("a new Content Explorer search is 2 requests, about $0.05").
  - `docs/env.md`: the same note on that row.
  - `docs/api.md`: a "Content Explorer" section covering:
    - the flow and costs
    - the cache rule
    - each field
    - the four endpoints and their errors
  - `README.md`: a "Content Explorer (Phase 7.2)" section with **How to verify (no money spent)**:

```bash
cd apps/backend
python -m pytest tests/test_backlinks_bulk.py tests/test_content_pages.py tests/test_content_explore.py tests/test_content_api.py -q
export SESSION_DIR=/tmp/seo-content       # SERP not live = dry run
python -m uvicorn app.main:app --port 5000 &
curl -s -X POST -H 'Content-Type: application/json' -d '{"topic":"rare books"}' localhost:5000/api/content-explorer | python -c "import sys,json; d=json.load(sys.stdin); print(d['dry_run'], d['summary'])"
curl -s localhost:5000/api/content-explorer/recent
curl -s localhost:5000/api/content-explorer/1/csv | head -3
```

Commit the docs (suite gated).

- [ ] **Step 2: Live check (dry run)**
  1. Run the README block.
  2. Open `/content`, search "rare books", expand an outline, switch a chart to its table view, reopen it from the recent chips, and check the CSV link.
  3. Take Playwright screenshots at 1440 and 390 px; there must be no sideways scroll.
  4. Fix anything found (with a test when it's behaviour), then stop the servers.
  5. **Optional live-path check:** fetch the top results for a real topic, using fake SERP items that point at books.toscrape.com, through `fetch_results`. This is a free site and no paid API is involved. It shows the real fetch and analysis work.
