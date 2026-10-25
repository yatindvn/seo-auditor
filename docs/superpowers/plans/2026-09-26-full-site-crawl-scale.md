# Full Site Crawl at 5000 Pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-enable the Full Site Crawl preset so a 5000-page, depth-15 audit completes in about 10 minutes on a 2 OCPU / 12 GB VM, with flat memory and a dashboard payload in the hundreds of kilobytes.

**Architecture:** The audit becomes a three-stage concurrent pipeline — a continuous 32-thread fetch pool, a process pool running each page's checks as it lands, and a single writer thread persisting to a per-session SQLite file — replacing today's three sequential phases that each hold the whole site in memory. Duplicate detection above 500 pages switches from full shingle sets to 128-value MinHash signatures with LSH banding. The dashboard stops receiving one large payload and instead reads paginated endpoints.

**Tech Stack:** Python 3.12 / FastAPI / uvicorn (single worker), `concurrent.futures` (ThreadPoolExecutor + ProcessPoolExecutor), SQLite via stdlib `sqlite3` in WAL mode, BeautifulSoup + lxml, networkx, pytest. Frontend: Next.js 14 App Router, Tailwind, Recharts, vitest.

**Spec:** `docs/superpowers/specs/2026-09-26-full-site-crawl-scale-design.md`

## Global Constraints

- Python backend only. `apps/backend/src/*.ts` is the retired Express server; never touch it.
- Single uvicorn worker is a hard requirement (`apps/backend/Dockerfile`). No state may assume a second process.
- All 121 existing backend tests stay green after every task. Run `python -m pytest -q` from `apps/backend`.
- TDD: write the failing test, run it, watch it fail for the right reason, then implement. No production code without a failing test first.
- Commit after every task. Never skip hooks.
- Near-duplicate threshold is `0.85` and shingle size is `5` in both the exact and MinHash paths. These exact values come from `app/analysis/analysis.py:105`.
- MinHash signature length is `128` 32-bit values (512 bytes). LSH uses `16` bands of `8` rows.
- The exact duplicate path is used at **≤ 500 pages**, MinHash **above** it.
- `GOOGLE_CSE_*` quota discipline and the nominated-pages scoping of rank checks and keyword suggestions must not change behaviour. The relevant tests are `tests/test_rank_quota_bounding.py` and `tests/test_keyword_suggestions.py`.
- Every new third-party import must be declared in `apps/backend/requirements.txt`, which `tests/test_requirements_declare_imports.py` enforces.
- Frontend tests run with `npm test` from `apps/frontend` (vitest).

## Deviations from the spec

One, deliberate, recorded here because the spec's diagram says otherwise:

**The spec puts link extraction in stage 1**, with the fetch thread parsing HTML to find links. This plan moves link extraction into the stage 2 worker, which returns the links alongside the analysis; the crawler enqueues them when the future completes. Reason: stage 1 parsing would mean a second full parse of every page (BeautifulSoup in the fetch thread, then again in the worker), which is the exact waste PR #14 removed. The cost is that frontier expansion now lags by one pool round-trip (~80 ms). That is acceptable because the pool is the critical path regardless — the perf budget already has checks at ~3.5 min against fetch at ~1.5–3 min, so overall throughput is pool-gated either way.

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `apps/backend/app/cli.py` | Command-line entry point; replaces the deleted duplicate engine's `cli.py` |
| `apps/backend/app/services/page_pipeline.py` | Pure, picklable per-page analysis: checks + metadata + keyword extraction + signature + links |
| `apps/backend/app/analysis/minhash.py` | MinHash signatures, LSH banding, estimated Jaccard |
| `apps/backend/app/models/session_db.py` | Per-session SQLite: schema, batched writes, paginated reads |
| `apps/backend/tests/test_page_pipeline.py` | Stage 2 unit tests |
| `apps/backend/tests/test_minhash.py` | Signature, banding and recall-against-exact tests |
| `apps/backend/tests/test_session_db.py` | Schema, write batching, pagination boundary tests |
| `apps/backend/tests/test_crawler_concurrency.py` | BFS order, `max_pages` admission, bounded in-flight |
| `apps/backend/tests/test_pipeline_integration.py` | Crawl → pool → SQLite end to end, degraded and partial paths |
| `apps/backend/tests/test_api_pagination.py` | Endpoint envelopes and boundaries |
| `apps/backend/perf/crawl_harness.py` | Manual perf harness: synthetic 1000-page site, wall-clock and RSS ceilings |
| `apps/frontend/lib/api-hooks.ts` | Shared paginated-fetch hook for panels |

**Modified:**

| File | Change |
| --- | --- |
| `apps/backend/app/crawler/crawler.py` | Continuous pool, depth heap, bounded in-flight, event throttling, HTML release |
| `apps/backend/app/services/audit_service.py` | Orchestration only; per-page work moves to `page_pipeline` |
| `apps/backend/app/analysis/analysis.py` | Duplicate-mode selection; PageRank reads from SQLite |
| `apps/backend/app/utils/report.py` | Gains the five export writers from the deleted tree |
| `apps/backend/app/api/routes.py` | Paginated endpoints, summary-only latest, clustering, `/api/duplicates` |
| `apps/backend/app/models/session_model.py` | Index over session DB files, retention 20 |
| `apps/backend/app/config/config.py` | `SESSION_DIR`, `CRAWL_CONCURRENCY`, `CRAWL_HTML_BUDGET`, `MAX_PAGES_LIMIT` |
| `apps/backend/app/schemas/schemas.py` | `MAX_PAGES_LIMIT` 1000 → 5000, configurable |
| `apps/backend/Dockerfile` | Drops `COPY seo_auditor`; adds the session volume |
| `apps/frontend/lib/audit-context.tsx` | Stores only `{sessionId, summary}`; try/catch around storage |
| `apps/frontend/lib/activity-feed.ts` | Handles `link_progress`, drops per-link events |
| `apps/frontend/components/pages-table.tsx` | Server-side pagination |
| `apps/frontend/components/issue-center.tsx` | Server-side pagination |
| `apps/frontend/components/site-architecture-graph.tsx` | Path clustering with drill-down |
| `apps/frontend/app/page.tsx` | Re-enables the preset; corrects the stale warning copy |

**Deleted:** `apps/backend/seo_auditor/` entirely, and `apps/backend/tests/test_cli_tree_parity.py` (its assertions move, they are not lost).

---

## Phase A — Delete the duplicated engine

Rewriting the crawler breaks `test_cli_tree_parity.py` either way, so the duplication goes first.

### Task 1: Move the export writers into `app/`

**Files:**
- Modify: `apps/backend/app/utils/report.py` (append five functions)
- Modify: `apps/backend/app/api/routes.py:201-245` (the `export_report` endpoint)
- Test: `apps/backend/tests/test_export_endpoint.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `app.utils.report.export_json(path, data) -> bytes`, `export_csv(path, page_rows) -> bytes`, `export_excel(path, sheets_dict) -> bytes`, `export_pdf_summary(path, exec_summary) -> bytes`, `export_html_report(path, exec_summary, pages) -> bytes`. Each returns bytes when `path` is `None` and writes to disk otherwise — this is the existing contract in the CLI copy; preserve it exactly.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/test_export_endpoint.py`:

```python
def test_export_writers_are_importable_from_the_app_package():
    """The export writers lived in the CLI package, reached through a
    ModuleNotFoundError fallback because the package resolves under two names
    depending on how it is on the path. Owning them in app/ deletes that hack."""
    from app.utils.report import (
        export_json, export_csv, export_excel, export_pdf_summary, export_html_report,
    )

    assert callable(export_json)
    assert callable(export_csv)
    assert callable(export_excel)
    assert callable(export_pdf_summary)
    assert callable(export_html_report)


def test_export_csv_returns_bytes_when_no_path_given():
    from app.utils.report import export_csv

    data = export_csv(None, [{"url": "https://example.com/", "status_code": 200}])

    assert isinstance(data, bytes)
    assert b"https://example.com/" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_export_endpoint.py -v`
Expected: FAIL with `ImportError: cannot import name 'export_json' from 'app.utils.report'`

- [ ] **Step 3: Move the writers**

Copy the five functions verbatim from `apps/backend/seo_auditor/seo_auditor/report.py` to the end of `apps/backend/app/utils/report.py`, keeping their lazy imports intact:

```python
# Appended from the CLI package, which is being deleted. openpyxl and reportlab
# stay imported inside their functions: both are heavy, and only two of the five
# export formats need them.
def export_excel(path, sheets_dict):
    from openpyxl import Workbook
    ...
```

Do not change their bodies. `openpyxl` and `reportlab` are already declared in `apps/backend/requirements.txt`.

- [ ] **Step 4: Replace the import hack in the endpoint**

In `apps/backend/app/api/routes.py`, delete the whole comment block and try/except at lines 205-220, and replace with a plain top-of-file import:

```python
from app.utils.report import (
    export_json, export_csv, export_excel, export_pdf_summary, export_html_report,
)
```

The body of `export_report` below that is unchanged.

- [ ] **Step 5: Run the full suite**

Run: `cd apps/backend && python -m pytest -q`
Expected: PASS, 123 tests (121 + 2 new)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/utils/report.py apps/backend/app/api/routes.py apps/backend/tests/test_export_endpoint.py
git commit -m "refactor: own the export writers in app/ instead of the CLI package

The five writers lived in seo_auditor/report.py and were reached through a
ModuleNotFoundError fallback, because that package resolves under two different
names depending on how it is on the path. app/ now owns them and the hack is
gone."
```

### Task 2: Delete the duplicate tree, move the CLI, migrate the parity assertions

**Files:**
- Create: `apps/backend/app/cli.py`
- Delete: `apps/backend/seo_auditor/` (entire directory), `apps/backend/tests/test_cli_tree_parity.py`
- Modify: `apps/backend/pytest.ini`, `apps/backend/Dockerfile`, `apps/backend/tests/test_keyword_suggestions.py`, `apps/backend/tests/test_rank_checker.py`, `docs/folder-structure.md`, `docs/architecture.md`
- Test: the migrated assertions plus a new CLI smoke test

**Interfaces:**
- Consumes: `app.utils.report` export writers from Task 1.
- Produces: `python -m app.cli <url> [--max-pages N] [--out DIR]` as the CLI entry point.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_cli.py`:

```python
"""The CLI is now a thin entry point over app/, not a second copy of the engine.

It previously duplicated the crawler, the checks, the analysis and the whole
per-page audit loop. Commit 8f18529 exists solely because that copy drifted.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_cli_module_is_importable_and_uses_the_app_engine():
    from app import cli

    assert cli.main is not None
    # The CLI must reuse the real pipeline, not re-implement it.
    assert cli.audit_service is not None


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        cwd=BACKEND_ROOT, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--max-pages" in result.stdout


def test_the_duplicate_engine_directory_is_gone():
    assert not (BACKEND_ROOT / "seo_auditor").exists(), (
        "the duplicate engine is back; app/ is the single source"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cli'`, and the third test fails because the directory still exists.

- [ ] **Step 3: Write `app/cli.py`**

It must **call the shared pipeline**, not re-implement the per-page loop the old `cli.py:180-250` duplicated:

```python
"""Command-line entry point: python -m app.cli https://example.com --max-pages 100

Deliberately thin. The engine lives in app/; this module parses arguments,
runs one audit through the same code path the API uses, and writes the report
files. It holds no audit logic of its own -- the previous CLI kept a second copy
of the crawler, the checks and the per-page loop, and they drifted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.crawler.crawler import Crawler
from app.services import audit_service
from app.utils.report import (
    export_csv, export_html_report, export_json, export_pdf_summary,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("url")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument("--out", default="./audit_output")
    args = parser.parse_args(argv)

    crawler = Crawler(
        start_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        respect_robots=not args.ignore_robots,
    )
    result = audit_service._build_audit_result(
        args.url, crawler, progress_callback=None, event_callback=None,
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    export_json(out / "audit_report.json", result)
    export_csv(out / "pages.csv", result.get("pages", []))
    export_html_report(out / "audit_report.html", result.get("executive_summary", {}), result.get("pages", []))
    export_pdf_summary(out / "audit_summary.pdf", result.get("executive_summary", {}))
    print(json.dumps(result.get("executive_summary", {}).get("health_score", {}), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Migrate the parity assertions before deleting anything**

`tests/test_cli_tree_parity.py` parametrises every test over `[app_module, cli_module]`. For each test in that file, move it to its single-module home — rank-checker tests to `tests/test_rank_checker.py`, suggestion tests to `tests/test_keyword_suggestions.py` — dropping only the parametrisation. Example, before:

```python
@pytest.mark.parametrize("module", BOTH_RANK_CHECKERS)
def test_cse_failure_does_not_log_the_api_key(module, caplog):
    ...
```

after, in `tests/test_rank_checker.py`:

```python
def test_cse_failure_does_not_log_the_api_key(caplog):
    """Migrated from test_cli_tree_parity.py when the duplicate tree was
    deleted. Encodes commit 2341c90: a failing CSE lookup logged the full
    request URL, which carries the Google API key."""
    ...
```

Every assertion must survive. Count them first (`grep -c "def test_" tests/test_cli_tree_parity.py`) and confirm the same number exists across the two destination files afterwards.

- [ ] **Step 5: Delete the duplicate tree and update its references**

```bash
git rm -r apps/backend/seo_auditor
git rm apps/backend/tests/test_cli_tree_parity.py
```

In `apps/backend/pytest.ini`, drop `seo_auditor` from `pythonpath` and delete the comment explaining why it was there:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

In `apps/backend/Dockerfile`, delete the `COPY seo_auditor ./seo_auditor` line and the comment above it explaining that the export endpoint needs it — Task 1 made that false.

In `docs/folder-structure.md` and `docs/architecture.md`, replace every `python -m seo_auditor.cli` with `python -m app.cli` and remove the CLI package from the layout description.

- [ ] **Step 6: Run the full suite**

Run: `cd apps/backend && python -m pytest -q`
Expected: PASS. Test count drops by the parity file's parametrised duplicates and rises by 3 CLI tests — confirm no assertion was lost by comparing `grep -c "def test_"` across the suite before and after.

- [ ] **Step 7: Commit**

```bash
git add -A apps/backend docs
git commit -m "refactor: delete the duplicated engine, CLI imports app/

apps/backend/seo_auditor/ was a second copy of the crawler, checks, analysis and
per-page loop, kept in step by hand (8f18529) and policed by a parity test.
app/ is now the single source and the CLI is a thin entry point over it.

The parity assertions are migrated, not dropped: each encodes a real fixed bug."
```

---

## Phase B — Storage

### Task 3: `session_db` — schema, batched writes, paginated reads

**Files:**
- Create: `apps/backend/app/models/session_db.py`
- Test: `apps/backend/tests/test_session_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces:

```python
class SessionDB:
    def __init__(self, path: Path) -> None          # creates schema if absent, WAL mode
    def add_pages(self, rows: list[dict]) -> None   # batched insert, one transaction
    def add_links(self, edges: list[tuple[str, str, bool]]) -> None   # (src, dst, internal)
    def add_signature(self, url: str, signature: bytes) -> None
    def set_summary(self, summary: dict) -> None
    def get_summary(self) -> dict | None
    def get_pages(self, offset=0, limit=50, sort="depth", order="asc",
                  filter_text=None, status=None, has_issues=None) -> tuple[list[dict], int]
    def get_issues(self, offset=0, limit=50, severity=None, code=None) -> tuple[list[dict], int]
    def get_page(self, url: str) -> dict | None
    def get_signatures(self) -> dict[str, bytes]
    def get_links(self) -> list[tuple[str, str]]     # internal only, for PageRank
    def close(self) -> None
```

`get_pages` and `get_issues` return `(rows, total_before_pagination)`. A page row's `meta_json` column is deserialised into the returned dict, never handed back as a string.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_session_db.py`:

```python
"""Per-session SQLite: the store that lets a 5000-page audit exist at all.

Holding every page in a dict cost ~500 MB of retained HTML plus the assembled
result, and the whole thing was returned by one endpoint. Pages now land on disk
as they are analysed and are read back a page at a time.
"""

import json

import pytest

from app.models.session_db import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "sess_test.db")
    yield database
    database.close()


def _page_row(url, **overrides):
    row = {
        "url": url, "final_url": url, "depth": 1, "status": 200,
        "response_time_ms": 12.5, "content_type": "text/html",
        "title": "T", "meta_description": "D", "h1": "H", "canonical": url,
        "word_count": 100, "char_count": 500,
        "internal_links_count": 3, "external_links_count": 1,
        "images_count": 2, "missing_alt_count": 0,
        "meta_robots": None, "lang": "en", "error": None,
        "meta": {"open_graph": {"og:title": "T"}},
        "issues": [],
    }
    row.update(overrides)
    return row


def test_pages_round_trip_with_meta_deserialised(db):
    db.add_pages([_page_row("https://example.com/")])

    rows, total = db.get_pages()

    assert total == 1
    assert rows[0]["url"] == "https://example.com/"
    assert rows[0]["meta"]["open_graph"] == {"og:title": "T"}, (
        "meta must come back as a dict, not the JSON string it is stored as"
    )


def test_pagination_returns_the_slice_and_the_unpaginated_total(db):
    db.add_pages([_page_row(f"https://example.com/{i}", depth=i) for i in range(10)])

    rows, total = db.get_pages(offset=4, limit=3, sort="depth")

    assert total == 10, "total counts every matching row, not just this page"
    assert [r["depth"] for r in rows] == [4, 5, 6]


def test_offset_past_the_end_returns_empty_not_an_error(db):
    db.add_pages([_page_row("https://example.com/")])

    rows, total = db.get_pages(offset=500, limit=50)

    assert rows == []
    assert total == 1


def test_issues_are_stored_per_page_and_filterable_by_severity(db):
    db.add_pages([
        _page_row("https://example.com/a", issues=[
            {"severity": "critical", "code": "MISSING_TITLE", "message": "m"},
            {"severity": "warning", "code": "THIN_CONTENT", "message": "m"},
        ]),
    ])

    critical, total = db.get_issues(severity="critical")

    assert total == 1
    assert critical[0]["code"] == "MISSING_TITLE"


def test_summary_round_trips(db):
    db.set_summary({"health_score": {"score": 81.5}})

    assert db.get_summary()["health_score"]["score"] == 81.5


def test_sort_column_is_whitelisted_not_interpolated(db):
    """The sort key reaches SQL. It must be validated against a fixed set, or it
    is an injection point on a public endpoint."""
    db.add_pages([_page_row("https://example.com/")])

    with pytest.raises(ValueError):
        db.get_pages(sort="url; DROP TABLE pages")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_session_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.session_db'`

- [ ] **Step 3: Implement `session_db.py`**

```python
"""Per-session SQLite store.

One file per audit under config.SESSION_DIR. Written during the crawl by a
single writer thread (SQLite permits one writer; WAL lets the read endpoints
serve while the crawl is still running) and read back a page at a time.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, final_url TEXT, depth INTEGER, status INTEGER,
  response_time_ms REAL, content_type TEXT, title TEXT, meta_description TEXT,
  h1 TEXT, canonical TEXT, word_count INTEGER, char_count INTEGER,
  internal_links_count INTEGER, external_links_count INTEGER,
  images_count INTEGER, missing_alt_count INTEGER,
  meta_robots TEXT, lang TEXT, error TEXT, issue_count INTEGER DEFAULT 0,
  meta_json TEXT
);
CREATE TABLE IF NOT EXISTS issues (url TEXT, severity TEXT, code TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS links (src TEXT, dst TEXT, internal INTEGER);
CREATE TABLE IF NOT EXISTS signatures (url TEXT PRIMARY KEY, minhash BLOB);
CREATE TABLE IF NOT EXISTS summary (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT);
CREATE INDEX IF NOT EXISTS idx_issues_url ON issues(url);
CREATE INDEX IF NOT EXISTS idx_issues_code ON issues(code);
CREATE INDEX IF NOT EXISTS idx_issues_severity ON issues(severity);
CREATE INDEX IF NOT EXISTS idx_links_src ON links(src);
CREATE INDEX IF NOT EXISTS idx_pages_depth ON pages(depth);
"""

# A sort key reaches SQL, so it is chosen from this set rather than interpolated.
SORTABLE = {
    "url", "depth", "status", "word_count", "response_time_ms",
    "internal_links_count", "issue_count",
}

PAGE_COLUMNS = [
    "url", "final_url", "depth", "status", "response_time_ms", "content_type",
    "title", "meta_description", "h1", "canonical", "word_count", "char_count",
    "internal_links_count", "external_links_count", "images_count",
    "missing_alt_count", "meta_robots", "lang", "error", "issue_count",
]


class SessionDB:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the writer thread and the request threads are
        # different threads on one connection, serialised by SQLite itself.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def add_pages(self, rows: list[dict]) -> None:
        page_values = []
        issue_values = []
        for row in rows:
            issues = row.get("issues") or []
            page_values.append(
                tuple(row.get(column) for column in PAGE_COLUMNS[:-1])
                + (len(issues), json.dumps(row.get("meta") or {}))
            )
            issue_values.extend(
                (row["url"], i["severity"], i["code"], i["message"]) for i in issues
            )
        with self._conn:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO pages ({','.join(PAGE_COLUMNS)}, meta_json) "
                f"VALUES ({','.join('?' * (len(PAGE_COLUMNS) + 1))})",
                page_values,
            )
            if issue_values:
                self._conn.executemany("INSERT INTO issues VALUES (?,?,?,?)", issue_values)

    def add_links(self, edges: list[tuple[str, str, bool]]) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT INTO links VALUES (?,?,?)",
                [(src, dst, 1 if internal else 0) for src, dst, internal in edges],
            )

    def add_signature(self, url: str, signature: bytes) -> None:
        with self._conn:
            self._conn.execute("INSERT OR REPLACE INTO signatures VALUES (?,?)", (url, signature))

    def set_summary(self, summary: dict) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO summary (id, json) VALUES (1, ?)", (json.dumps(summary),)
            )

    def get_summary(self) -> Optional[dict]:
        row = self._conn.execute("SELECT json FROM summary WHERE id = 1").fetchone()
        return json.loads(row["json"]) if row else None

    def _row_to_page(self, row: sqlite3.Row) -> dict:
        page = {column: row[column] for column in PAGE_COLUMNS}
        page["meta"] = json.loads(row["meta_json"] or "{}")
        return page

    def get_pages(self, offset=0, limit=50, sort="depth", order="asc",
                  filter_text=None, status=None, has_issues=None) -> tuple[list[dict], int]:
        if sort not in SORTABLE:
            raise ValueError(f"unsortable column {sort!r}; allowed: {sorted(SORTABLE)}")
        direction = "DESC" if str(order).lower() == "desc" else "ASC"

        where, params = [], []
        if filter_text:
            where.append("url LIKE ?")
            params.append(f"%{filter_text}%")
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if has_issues is not None:
            where.append("issue_count > 0" if has_issues else "issue_count = 0")
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        total = self._conn.execute(f"SELECT COUNT(*) AS c FROM pages{clause}", params).fetchone()["c"]
        rows = self._conn.execute(
            f"SELECT * FROM pages{clause} ORDER BY {sort} {direction}, url ASC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [self._row_to_page(r) for r in rows], total

    def get_issues(self, offset=0, limit=50, severity=None, code=None) -> tuple[list[dict], int]:
        where, params = [], []
        if severity:
            where.append("severity = ?")
            params.append(severity)
        if code:
            where.append("code = ?")
            params.append(code)
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        total = self._conn.execute(f"SELECT COUNT(*) AS c FROM issues{clause}", params).fetchone()["c"]
        rows = self._conn.execute(
            f"SELECT * FROM issues{clause} ORDER BY url LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

    def get_page(self, url: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
        return self._row_to_page(row) if row else None

    def get_signatures(self) -> dict[str, bytes]:
        return {r["url"]: r["minhash"] for r in self._conn.execute("SELECT * FROM signatures")}

    def get_links(self) -> list[tuple[str, str]]:
        return [
            (r["src"], r["dst"])
            for r in self._conn.execute("SELECT src, dst FROM links WHERE internal = 1")
        ]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_session_db.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/models/session_db.py apps/backend/tests/test_session_db.py
git commit -m "feat: per-session SQLite store with paginated reads"
```

### Task 4: `SessionStore` becomes an index over session files

**Files:**
- Modify: `apps/backend/app/models/session_model.py` (replace the in-memory list)
- Modify: `apps/backend/app/config/config.py` (add `SESSION_DIR`)
- Modify: `deploy/oracle/docker-compose.yml` (named volume for the session directory)
- Test: `apps/backend/tests/test_session_store_index.py`

**Interfaces:**
- Consumes: `SessionDB` from Task 3.
- Produces: `session_store.open_session(session_id) -> SessionDB`, `session_store.get(session_id) -> SessionDB | None`, `session_store.get_all_sessions() -> list[dict]` (id, url, timestamp, health score), `session_store.delete_session(id) -> bool`, `session_store.get_history_comparison(summary) -> dict | None`. Retention: newest 20 files, oldest deleted on `open_session`.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_session_store_index.py`:

```python
"""SessionStore holds an index over session files, not 50 audit results.

Retaining 50 full results in memory was viable only because audits were small.
At 5000 pages one result is tens of megabytes, so the store keeps files and
reads summaries from them.
"""

import pytest

from app.models.session_model import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(session_dir=tmp_path)


def test_opening_a_session_creates_its_database_file(store, tmp_path):
    db = store.open_session("sess_1")
    db.set_summary({"url": "https://example.com/", "health_score": {"score": 90}})

    assert (tmp_path / "sess_1.db").exists()


def test_sessions_survive_a_new_store_over_the_same_directory(store, tmp_path):
    """The point of moving to disk: a redeploy no longer erases history."""
    store.open_session("sess_1").set_summary({"url": "https://example.com/", "health_score": {"score": 90}})

    reopened = SessionStore(session_dir=tmp_path)

    assert [s["id"] for s in reopened.get_all_sessions()] == ["sess_1"]


def test_retention_keeps_the_newest_twenty_and_deletes_the_rest(store, tmp_path):
    for index in range(25):
        store.open_session(f"sess_{index:03d}").set_summary({"url": "u", "health_score": {"score": 1}})

    remaining = sorted(p.stem for p in tmp_path.glob("*.db"))

    assert len(remaining) == 20
    assert remaining[0] == "sess_005", "the five oldest are deleted, newest kept"


def test_deleting_a_session_removes_its_file(store, tmp_path):
    store.open_session("sess_1").set_summary({"url": "u", "health_score": {"score": 1}})

    assert store.delete_session("sess_1") is True
    assert not (tmp_path / "sess_1.db").exists()
    assert store.delete_session("sess_1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_session_store_index.py -v`
Expected: FAIL — `TypeError: SessionStore.__init__() got an unexpected keyword argument 'session_dir'`

- [ ] **Step 3: Add `SESSION_DIR` to config**

In `apps/backend/app/config/config.py`, after `CRAWL_TIMEOUT`:

```python
# Where per-session SQLite files live. A named Docker volume maps here in
# deploy/oracle/docker-compose.yml so history outlives a container rebuild.
SESSION_DIR = Path(os.getenv("SESSION_DIR", "./sessions"))
```

- [ ] **Step 4: Rewrite `session_model.py`**

Keep `get_history_comparison`'s output shape byte-for-byte — `historical-comparison-panel.tsx` reads those exact keys — but source it from two summaries instead of two full results:

```python
class SessionStore:
    RETENTION = 20

    def __init__(self, session_dir=None) -> None:
        self._dir = Path(session_dir or config.SESSION_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._open: Dict[str, SessionDB] = {}

    def open_session(self, session_id: str) -> SessionDB:
        self._enforce_retention()
        db = SessionDB(self._dir / f"{session_id}.db")
        self._open[session_id] = db
        return db

    def get(self, session_id: str) -> Optional[SessionDB]:
        if session_id in self._open:
            return self._open[session_id]
        path = self._dir / f"{session_id}.db"
        if not path.exists():
            return None
        db = SessionDB(path)
        self._open[session_id] = db
        return db
    ...
```

`get_all_sessions` lists `*.db` newest-first by modification time and reads each summary's `url`, `timestamp` and health score. `_enforce_retention` deletes the oldest files beyond `RETENTION`, closing any open handle first.

- [ ] **Step 5: Add the Docker volume**

In `deploy/oracle/docker-compose.yml`, under the `backend` service:

```yaml
    environment:
      SESSION_DIR: /data/sessions
    volumes:
      - sessions:/data/sessions
```

and add `sessions:` to the top-level `volumes:` block alongside `caddy_data`.

- [ ] **Step 6: Run the full suite**

Run: `cd apps/backend && python -m pytest -q`
Expected: PASS. `tests/test_elapsed_seconds.py::test_saved_session_id_still_uses_wall_clock_time` patches `session_store.save_session`; update that patch target to the new API in the same commit.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/models apps/backend/app/config/config.py apps/backend/tests deploy/oracle/docker-compose.yml
git commit -m "feat: SessionStore indexes session files instead of holding results

History now survives a redeploy, and a finished audit costs no resident memory."
```

---

## Phase C — Engine

### Task 5: Extract the per-page work into `page_pipeline`

This is a **pure move**. Behaviour must not change: the existing suite is the proof.

**Files:**
- Create: `apps/backend/app/services/page_pipeline.py`
- Modify: `apps/backend/app/services/audit_service.py:128-320` (the per-page loop)
- Test: `apps/backend/tests/test_page_pipeline.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:

```python
@dataclass
class PagePayload:
    url: str
    final_url: str
    status_code: Optional[int]
    headers: dict
    html: str
    depth: int
    redirect_chain: list
    response_time_ms: Optional[float]
    content_type: str
    error: Optional[str]
    enable_keyword_analysis: bool = True
    target_keywords: Optional[list] = None
    compute_signature: bool = False

@dataclass
class PageAnalysis:
    url: str
    issues: list           # [{"severity","code","message"}]
    meta: dict             # the page_meta entry, minus keyword_analysis
    dupe_row: dict         # {"url","title","meta_description","h1","canonical","content_hash","text"}
    keyword_data: list
    signature: Optional[bytes]
    internal_links: list
    external_links: list
    failed: bool = False

def analyze_page(payload: PagePayload) -> PageAnalysis
```

`analyze_page` is pure: no config, no network, no module state. That is what makes it picklable for Task 10's process pool.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_page_pipeline.py`:

```python
"""Stage 2 of the pipeline: everything that happens to one page's HTML.

Extracted from audit_service's per-page loop so it can run in a process pool
while the crawl continues. Purity is the requirement that makes that possible --
no config, no network, no module-level state -- so it is asserted here.
"""

import pickle

from app.services.page_pipeline import PagePayload, analyze_page

HTML = (
    "<html><head><title>Espresso Machines</title>"
    "<meta name='description' content='Reviews of espresso machines'></head>"
    "<body><h1>Best Espresso Machines</h1>"
    "<p>espresso machine reviews and buying guide with plenty of words to "
    "satisfy the word count checks in this pipeline test fixture.</p>"
    "<a href='/grinders'>Grinders</a><a href='https://other.example/x'>Off site</a>"
    "</body></html>"
)


def _payload(**overrides):
    base = dict(
        url="https://example.com/", final_url="https://example.com/", status_code=200,
        headers={}, html=HTML, depth=0, redirect_chain=[], response_time_ms=10.0,
        content_type="text/html", error=None,
    )
    base.update(overrides)
    return PagePayload(**base)


def test_analyze_page_returns_the_pages_title_and_issues():
    result = analyze_page(_payload())

    assert result.meta["title"] == "Espresso Machines"
    assert result.meta["word_count"] > 0
    assert isinstance(result.issues, list)


def test_analyze_page_separates_internal_from_external_links():
    result = analyze_page(_payload())

    assert "https://example.com/grinders" in result.internal_links
    assert "https://other.example/x" in result.external_links


def test_analyze_page_is_picklable_in_both_directions():
    """The process pool sends a payload and receives an analysis. Anything
    unpicklable in either -- a BeautifulSoup node, a compiled regex, a lambda --
    fails at the pool boundary, not here, where it is hard to read."""
    payload = _payload()

    assert pickle.loads(pickle.dumps(payload)).url == payload.url
    assert pickle.loads(pickle.dumps(analyze_page(payload))).meta["title"] == "Espresso Machines"


def test_keyword_extraction_is_skipped_when_disabled():
    result = analyze_page(_payload(enable_keyword_analysis=False))

    assert result.keyword_data == []


def test_signature_is_only_computed_when_asked():
    assert analyze_page(_payload()).signature is None
    assert analyze_page(_payload(compute_signature=True)).signature is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_page_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.page_pipeline'`

- [ ] **Step 3: Move the loop body into `analyze_page`**

Copy the body of the per-page loop from `audit_service.py` (the `try:` block added by commit `9884352`, lines 135-306) into `analyze_page`, substituting `payload` for `page`. Leave out the three things that are **not** pure and stay in the parent: `_match_rank_target`, `rank_checker.check_rankings`, and `keyword_suggestions.suggest_keywords`.

Add link extraction, moved from `crawler._extract_links`, reusing the soup the checks already parsed:

```python
    soup = checks._soup(payload.html)
    internal_links, external_links = [], []
    if soup:
        root_netloc = up.urlsplit(payload.final_url).netloc
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = normalize_url(up.urljoin(payload.final_url, href))
            if same_registrable_domain(absolute, root_netloc):
                internal_links.append(absolute)
            else:
                external_links.append(absolute)
```

- [ ] **Step 4: Call it from `audit_service`**

The loop becomes:

```python
    for page_url, page in crawler.results.items():
        try:
            analysis_result = page_pipeline.analyze_page(page_pipeline.PagePayload(
                url=page_url, final_url=page.final_url, status_code=page.status_code,
                headers=page.headers, html=page.html, depth=page.depth,
                redirect_chain=page.redirect_chain, response_time_ms=page.response_time_ms,
                content_type=page.content_type, error=page.error,
                enable_keyword_analysis=enable_keyword_analysis,
                target_keywords=target_keywords,
            ))
        except Exception as exc:
            logger.error("Audit checks failed for %s: %s", page_url, exc, exc_info=exc)
            all_page_issues[page_url] = [
                checks.issue("critical", "AUDIT_ERROR", f"This page could not be audited: {exc}")
            ]
            page_meta[page_url] = {}
            continue

        all_page_issues[page_url] = analysis_result.issues
        page_meta[page_url] = analysis_result.meta
        # Rank checks and suggestions stay here: they are network-bound and
        # quota-limited, and must not run inside a worker process.
        ...unchanged rank/suggestion block, using analysis_result.keyword_data...
        page_data_for_dupes.append(analysis_result.dupe_row)
```

- [ ] **Step 5: Run the full suite — this is the real test of the move**

Run: `cd apps/backend && python -m pytest -q`
Expected: PASS, every pre-existing test unchanged. A failure here means the move changed behaviour; fix the move, never the test.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services apps/backend/tests/test_page_pipeline.py
git commit -m "refactor: extract per-page analysis into a pure, picklable function

Behaviour-preserving move. Purity is the point: analyze_page holds no config,
no network and no module state, so Task 10 can run it in a process pool while
the crawl continues."
```

### Task 6: MinHash signatures and LSH banding

**Files:**
- Create: `apps/backend/app/analysis/minhash.py`
- Test: `apps/backend/tests/test_minhash.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `signature(text, shingle_size=5) -> bytes | None` (512 bytes), `estimated_jaccard(a, b) -> float`, `near_duplicates(signatures: dict[str, bytes], threshold=0.85) -> list[dict]` returning `{"url_a","url_b","similarity"}` in the same shape `analysis.near_duplicate_content` returns.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_minhash.py`:

```python
"""MinHash + LSH: duplicate detection that fits in memory at 5000 pages.

A full shingle set is ~50 KB per page, so 5000 pages cost 160-320 MB. A
128-value signature is 512 bytes. The trade is exactness: similarity becomes an
estimate, which is why the exact path is kept for crawls of 500 pages or fewer.
"""

import random

from app.analysis import minhash
from app.analysis.analysis import near_duplicate_content

WORDS = "espresso machine grinder burr tamper portafilter basket shot pull crema".split()


def _document(seed, length=400):
    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(length))


def test_signature_is_512_bytes():
    """128 x 32-bit. The memory claim this whole design rests on."""
    assert len(minhash.signature("some text with several words in it")) == 512


def test_signature_of_empty_text_is_none():
    assert minhash.signature("") is None


def test_identical_documents_estimate_as_identical():
    text = _document(1)

    assert minhash.estimated_jaccard(minhash.signature(text), minhash.signature(text)) == 1.0


def test_unrelated_documents_estimate_far_below_the_threshold():
    a = "the quick brown fox jumps over the lazy dog " * 40
    b = "financial results for the fourth quarter exceeded expectations " * 40

    assert minhash.estimated_jaccard(minhash.signature(a), minhash.signature(b)) < 0.2


def test_near_duplicates_finds_the_pair_the_exact_path_finds():
    """Recall is the property that matters: a pair the exact implementation
    reports well above the threshold must not be missed by the approximation."""
    base = _document(7)
    tweaked = base.rsplit(" ", 20)[0] + " grinder burr tamper basket shot"
    pages = [
        {"url": "https://example.com/a", "text": base},
        {"url": "https://example.com/b", "text": tweaked},
        {"url": "https://example.com/c", "text": _document(99)},
    ]
    exact = near_duplicate_content(pages)
    assert exact, "fixture must contain a genuine duplicate pair for this to test anything"

    signatures = {p["url"]: minhash.signature(p["text"]) for p in pages}
    approximate = minhash.near_duplicates(signatures)

    exact_pairs = {(p["url_a"], p["url_b"]) for p in exact}
    approximate_pairs = {(p["url_a"], p["url_b"]) for p in approximate}
    assert exact_pairs <= approximate_pairs, (
        f"MinHash missed a pair the exact path found: {exact_pairs - approximate_pairs}"
    )


def test_unrelated_documents_are_not_reported_as_duplicates():
    signatures = {f"https://example.com/{i}": minhash.signature(_document(i)) for i in range(8)}

    assert minhash.near_duplicates(signatures) == []


def test_banding_beats_comparing_every_pair():
    """The whole point of LSH: candidate generation must be sub-quadratic, or
    this is just the old algorithm with smaller sets."""
    signatures = {f"https://example.com/{i}": minhash.signature(_document(i)) for i in range(200)}

    comparisons = minhash.candidate_pairs(signatures)

    assert len(comparisons) < 200 * 199 / 2 / 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_minhash.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.minhash'`

- [ ] **Step 3: Implement `minhash.py`**

```python
"""MinHash signatures with LSH banding.

Each page reduces to SIGNATURE_LENGTH 32-bit minima over its word shingles: 512
bytes against ~50 KB for a full shingle set. Two pages are candidates when any
of BANDS consecutive slices of their signatures match exactly; the estimated
Jaccard is then the fraction of positions that agree.

Approximate by construction. At 128 permutations the standard error is about
0.04, so a pair sitting on the threshold may fall either side of it -- which is
why app/analysis/analysis.py keeps the exact path for crawls of 500 pages or
fewer and this is used only above that.
"""

from __future__ import annotations

import hashlib
from array import array
from typing import Dict, List, Optional

SIGNATURE_LENGTH = 128
BANDS = 16
ROWS_PER_BAND = SIGNATURE_LENGTH // BANDS  # 8
SHINGLE_SIZE = 5
MASK32 = 0xFFFFFFFF

# Permutations as (a, b) pairs for h_i(x) = (a*x + b) mod 2**32, drawn from a
# fixed seed so signatures are comparable across processes and across runs --
# Python's hash() is randomised per process and cannot be used here.
def _permutations() -> List[tuple]:
    digest = hashlib.blake2b(b"seo-auditor-minhash-v1", digest_size=8 * SIGNATURE_LENGTH).digest()
    pairs = []
    for i in range(SIGNATURE_LENGTH):
        chunk = digest[i * 8:(i + 1) * 8]
        a = int.from_bytes(chunk[:4], "big") | 1  # odd multiplier keeps it a bijection
        b = int.from_bytes(chunk[4:], "big")
        pairs.append((a, b))
    return pairs


_PERMUTATIONS = _permutations()


def _shingle_hashes(text: str, shingle_size: int) -> List[int]:
    words = text.lower().split()
    if not words:
        return []
    limit = max(len(words) - shingle_size + 1, 1)
    return [
        int.from_bytes(
            hashlib.blake2b(" ".join(words[i:i + shingle_size]).encode("utf-8"), digest_size=4).digest(),
            "big",
        )
        for i in range(limit)
    ]


def signature(text: str, shingle_size: int = SHINGLE_SIZE) -> Optional[bytes]:
    hashes = _shingle_hashes(text or "", shingle_size)
    if not hashes:
        return None
    minima = array("I", [MASK32] * SIGNATURE_LENGTH)
    for value in hashes:
        for index, (a, b) in enumerate(_PERMUTATIONS):
            candidate = (a * value + b) & MASK32
            if candidate < minima[index]:
                minima[index] = candidate
    return minima.tobytes()


def estimated_jaccard(a: bytes, b: bytes) -> float:
    left, right = array("I"), array("I")
    left.frombytes(a)
    right.frombytes(b)
    matches = sum(1 for x, y in zip(left, right) if x == y)
    return matches / SIGNATURE_LENGTH


def candidate_pairs(signatures: Dict[str, bytes]) -> set:
    buckets: Dict[tuple, List[str]] = {}
    for url, raw in signatures.items():
        if raw is None:
            continue
        values = array("I")
        values.frombytes(raw)
        for band in range(BANDS):
            slice_ = tuple(values[band * ROWS_PER_BAND:(band + 1) * ROWS_PER_BAND])
            buckets.setdefault((band, slice_), []).append(url)

    pairs = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i, first in enumerate(members):
            for second in members[i + 1:]:
                pairs.add(tuple(sorted((first, second))))
    return pairs


def near_duplicates(signatures: Dict[str, bytes], threshold: float = 0.85) -> List[Dict]:
    results = []
    for url_a, url_b in sorted(candidate_pairs(signatures)):
        similarity = estimated_jaccard(signatures[url_a], signatures[url_b])
        if similarity >= threshold:
            results.append({"url_a": url_a, "url_b": url_b, "similarity": round(similarity, 3)})
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_minhash.py -v`
Expected: PASS, 7 tests. If `test_near_duplicates_finds_the_pair_the_exact_path_finds` fails, the banding is too strict — do not lower the threshold to make it pass; check `ROWS_PER_BAND` first.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/analysis/minhash.py apps/backend/tests/test_minhash.py
git commit -m "feat: MinHash signatures with LSH banding for large-crawl duplicates"
```

### Task 7: Select the duplicate mode by crawl size

**Files:**
- Modify: `apps/backend/app/analysis/analysis.py` (add the selector)
- Modify: `apps/backend/app/services/audit_service.py` (call it, record the mode)
- Test: `apps/backend/tests/test_near_duplicate_content.py` (extend)

**Interfaces:**
- Consumes: `minhash.near_duplicates` from Task 6.
- Produces: `analysis.find_near_duplicates(page_data, signatures, threshold=0.85) -> tuple[list[dict], str]` where the second element is `"exact"` or `"minhash"`. `audit_service` puts it in the result as `near_duplicate_mode`.

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/test_near_duplicate_content.py`:

```python
EXACT_PATH_MAX_PAGES = 500


def test_small_crawls_use_the_exact_path():
    pages = [{"url": f"https://example.com/{i}", "text": f"unique text number {i} " * 30} for i in range(10)]

    _, mode = analysis.find_near_duplicates(pages, signatures={})

    assert mode == "exact"


def test_large_crawls_switch_to_minhash():
    pages = [
        {"url": f"https://example.com/{i}", "text": f"unique text number {i} " * 30}
        for i in range(EXACT_PATH_MAX_PAGES + 1)
    ]
    signatures = {p["url"]: minhash.signature(p["text"]) for p in pages}

    _, mode = analysis.find_near_duplicates(pages, signatures=signatures)

    assert mode == "minhash"


def test_minhash_mode_still_reports_a_real_duplicate_pair():
    """Switching modes must not switch the feature off."""
    shared = "the same paragraph repeated across two pages " * 40
    pages = [{"url": f"https://example.com/{i}", "text": f"filler {i} " * 60} for i in range(EXACT_PATH_MAX_PAGES)]
    pages += [
        {"url": "https://example.com/dupe-a", "text": shared},
        {"url": "https://example.com/dupe-b", "text": shared},
    ]
    signatures = {p["url"]: minhash.signature(p["text"]) for p in pages}

    pairs, mode = analysis.find_near_duplicates(pages, signatures=signatures)

    assert mode == "minhash"
    assert any(
        {p["url_a"], p["url_b"]} == {"https://example.com/dupe-a", "https://example.com/dupe-b"}
        for p in pairs
    )
```

Add `from app.analysis import minhash` to the file's imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_near_duplicate_content.py -v`
Expected: FAIL — `AttributeError: module 'app.analysis.analysis' has no attribute 'find_near_duplicates'`

- [ ] **Step 3: Implement the selector**

In `analysis.py`:

```python
# Above this many pages, holding a full shingle set per page costs hundreds of
# megabytes, so detection switches to MinHash estimates. Below it, exact results
# are affordable and strictly better.
EXACT_PATH_MAX_PAGES = 500


def find_near_duplicates(page_data, signatures, threshold: float = 0.85):
    """Return (pairs, mode). Mode is reported to the client because the two
    paths do not produce identical numbers: MinHash similarity is an estimate."""
    if len(page_data) <= EXACT_PATH_MAX_PAGES:
        return near_duplicate_content(page_data, threshold=threshold), "exact"
    usable = {url: sig for url, sig in signatures.items() if sig}
    return minhash.near_duplicates(usable, threshold=threshold), "minhash"
```

`near_duplicate_content` currently takes `threshold` as its third positional parameter — pass it by keyword as shown, and leave that function otherwise untouched.

In `audit_service._build_audit_result`, replace `near_dupes = analysis.near_duplicate_content(page_data_for_dupes)` with:

```python
    near_dupes, near_duplicate_mode = analysis.find_near_duplicates(
        page_data_for_dupes, signatures=collected_signatures,
    )
```

and add `"near_duplicate_mode": near_duplicate_mode,` to `result_data`.

- [ ] **Step 4: Run the full suite**

Run: `cd apps/backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/analysis apps/backend/app/services/audit_service.py apps/backend/tests/test_near_duplicate_content.py
git commit -m "feat: pick exact or MinHash duplicate detection by crawl size

Reported to the client as near_duplicate_mode, because the two paths do not
produce identical similarity numbers."
```

### Task 8: Continuous fetch pool with a depth-ordered frontier

**Files:**
- Modify: `apps/backend/app/crawler/crawler.py:248-326` (`crawl`)
- Modify: `apps/backend/app/config/config.py` (`CRAWL_CONCURRENCY`, `CRAWL_HTML_BUDGET`)
- Test: `apps/backend/tests/test_crawler_concurrency.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Crawler.crawl(progress_callback=None, event_callback=None, on_page=None)`. `on_page`, when given, is called with each `PageResult` as it completes and returns `(internal_links, external_links)`; when `None`, the crawler falls back to parsing links itself so the CLI keeps working.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_crawler_concurrency.py`:

```python
"""The crawl loop: continuous workers, BFS order preserved, cap respected.

The previous loop took a batch of 10 and waited for all 10 before starting the
next, so one slow page idled nine workers and the pool was rebuilt every batch.
"""

import threading
import time

from app.crawler.crawler import Crawler, PageResult


def _install_fake_fetch(crawler, pages, delay_for=None):
    """Replace network I/O with an in-memory site. delay_for makes one URL slow,
    which is how the batch barrier becomes visible."""
    def fake_fetch(url):
        if delay_for and url == delay_for:
            time.sleep(0.3)
        html = pages.get(url, "")
        return PageResult(url=url, final_url=url, status_code=200, html=html, headers={})
    crawler._fetch = fake_fetch


def _linked_site(width=30):
    home = "https://example.com/"
    children = [f"https://example.com/p{i}" for i in range(width)]
    pages = {home: "".join(f"<a href='{c}'>c</a>" for c in children)}
    pages.update({c: "" for c in children})
    return home, pages, children


def test_crawl_visits_pages_in_breadth_first_order():
    home, pages, children = _linked_site(width=5)
    grandchild = "https://example.com/deep"
    pages[children[0]] = f"<a href='{grandchild}'>d</a>"
    pages[grandchild] = ""
    crawler = Crawler(home, max_pages=50, max_depth=5, respect_robots=False)
    _install_fake_fetch(crawler, pages)

    results = crawler.crawl()

    depths = {url: result.depth for url, result in results.items()}
    assert depths[home] == 0
    assert all(depths[c] == 1 for c in children)
    assert depths[grandchild] == 2


def test_one_slow_page_does_not_stall_the_other_workers():
    """The regression this task exists for. With a batch barrier, 30 pages where
    one takes 300ms cost at least 300ms per batch of 10 -- nearly a second."""
    home, pages, _ = _linked_site(width=30)
    crawler = Crawler(home, max_pages=31, max_depth=2, respect_robots=False, concurrency=16)
    _install_fake_fetch(crawler, pages, delay_for="https://example.com/p7")

    started = time.monotonic()
    crawler.crawl()
    elapsed = time.monotonic() - started

    assert elapsed < 0.9, f"crawl took {elapsed:.2f}s; a slow page is still blocking a batch"


def test_max_pages_is_never_exceeded_with_many_workers_in_flight():
    """32 concurrent fetches can each pass a naive `len(visited) < max_pages`
    check before any of them records a result."""
    home, pages, _ = _linked_site(width=100)
    crawler = Crawler(home, max_pages=25, max_depth=3, respect_robots=False, concurrency=32)
    _install_fake_fetch(crawler, pages)

    results = crawler.crawl()

    assert len(results) <= 25


def test_on_page_callback_supplies_the_links_when_given():
    home, pages, children = _linked_site(width=3)
    crawler = Crawler(home, max_pages=10, max_depth=2, respect_robots=False)
    _install_fake_fetch(crawler, pages)
    seen = []

    def on_page(result):
        seen.append(result.url)
        return ([c for c in children] if result.url == home else [], [])

    crawler.crawl(on_page=on_page)

    assert home in seen
    assert set(children) <= set(seen), "links returned by on_page must be enqueued"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_crawler_concurrency.py -v`
Expected: `test_one_slow_page_does_not_stall_the_other_workers` FAILS on elapsed time; `test_on_page_callback_supplies_the_links_when_given` FAILS with `TypeError: crawl() got an unexpected keyword argument 'on_page'`.

- [ ] **Step 3: Rewrite `crawl`**

```python
    def crawl(self, progress_callback=None, event_callback=None, on_page=None):
        """BFS crawl with a continuous worker pool.

        The frontier is a heap keyed on (depth, sequence), so pages are still
        discovered in click-depth order -- the order that makes crawl depth and
        the architecture graph meaningful. What changed is that workers pull from
        it continuously instead of in lockstep batches: previously a batch of
        `concurrency` URLs had to finish before the next began, so one slow page
        idled every other worker.

        `on_page`, when supplied, receives each PageResult and returns
        (internal_links, external_links). Stage 2 supplies it so the page's HTML
        is parsed exactly once, in the worker process, rather than again here.
        """
        self.event_callback = event_callback
        frontier = []
        sequence = itertools.count()
        heapq.heappush(frontier, (0, next(sequence), self.start_url, None))
        self.queued.add(self.start_url)

        in_flight = {}
        admitted = 0
        lock = threading.Lock()
        max_in_flight = self.concurrency * 2

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            while frontier or in_flight:
                if self.is_stopped:
                    break
                if self.is_paused:
                    time.sleep(0.5)
                    continue

                while frontier and len(in_flight) < max_in_flight:
                    depth, _, url, referrer = heapq.heappop(frontier)
                    if url in self.visited or not self._allowed(url):
                        continue
                    # Admission under the lock: without it, 32 workers each pass
                    # a `len(visited) < max_pages` check before any records a
                    # result, and the crawl overshoots the cap.
                    with lock:
                        if admitted >= self.max_pages:
                            frontier.clear()
                            break
                        admitted += 1
                    in_flight[pool.submit(self._fetch, url)] = (url, depth, referrer)

                if not in_flight:
                    continue

                done, _ = concurrent.futures.wait(
                    in_flight, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    url, depth, referrer = in_flight.pop(future)
                    self._handle_result(
                        future, url, depth, referrer, frontier, sequence,
                        progress_callback, on_page,
                    )

        return self.results
```

`_handle_result` is a new private method holding what the old loop body did per completed page: record the result, fire `page_crawled`, call `on_page` (or fall back to `self._extract_links`), update `link_graph`/`inbound_links`, and push unseen internal links onto the heap at `depth + 1` when `depth < self.max_depth`.

Add `import heapq`, `import itertools`, `import threading` at the top.

Add to `config.py`:

```python
# Fetch workers. 32 is chosen against the deployed 2 OCPU / 12 GB shape: the
# work is network-bound, so it far exceeds the core count.
CRAWL_CONCURRENCY = int(os.getenv("CRAWL_CONCURRENCY", "32"))
# Backpressure: stop submitting fetches when this much un-analysed HTML is held.
CRAWL_HTML_BUDGET = int(os.getenv("CRAWL_HTML_BUDGET", str(256 * 1024 * 1024)))
```

and pass `concurrency=config.CRAWL_CONCURRENCY` in `audit_service.run_full_audit`'s `Crawler(...)` call, replacing the hardcoded `10`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_crawler_concurrency.py -v && python -m pytest -q`
Expected: PASS, both the new file and the full suite.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/crawler/crawler.py apps/backend/app/config/config.py apps/backend/app/services/audit_service.py apps/backend/tests/test_crawler_concurrency.py
git commit -m "perf: continuous crawl workers instead of lockstep batches

The frontier is a depth-ordered heap, so BFS order is unchanged; what changes is
that a slow page no longer idles every other worker. max_pages admission moves
under a lock, since 32 in-flight fetches would otherwise overshoot the cap."
```

### Task 9: Throttle the per-link activity events

**Files:**
- Modify: `apps/backend/app/crawler/crawler.py` (`_handle_result`)
- Modify: `apps/backend/app/api/routes.py:40-58` (`event_callback`)
- Modify: `apps/frontend/lib/activity-feed.ts`
- Test: `apps/backend/tests/test_crawler_events.py`, `apps/frontend/lib/__tests__/activity-feed.test.ts`

**Interfaces:**
- Consumes: Task 8's `_handle_result`.
- Produces: a `link_progress` event with payload `{"internal_total": int, "external_total": int}`, emitted at most once per second. `internal_link` and `external_link` events no longer exist.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_crawler_events.py`:

```python
"""Live events must stay proportionate to the crawl.

One event per internal link means a few hundred thousand WebSocket messages on a
5000-page site, which stalls the browser long before the crawl finishes.
"""

from app.crawler.crawler import Crawler, PageResult


def test_internal_links_are_reported_as_an_aggregate_not_one_event_each():
    home = "https://example.com/"
    links = "".join(f"<a href='https://example.com/p{i}'>x</a>" for i in range(200))
    crawler = Crawler(home, max_pages=1, max_depth=1, respect_robots=False)
    crawler._fetch = lambda url: PageResult(
        url=url, final_url=url, status_code=200, html=links, headers={},
    )
    events = []

    crawler.crawl(event_callback=lambda kind, payload: events.append((kind, payload)))

    assert not [e for e in events if e[0] in ("internal_link", "external_link")], (
        "per-link events are what this task removes"
    )
    progress = [e for e in events if e[0] == "link_progress"]
    assert progress, "the aggregate must still be reported"
    assert progress[-1][1]["internal_total"] == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_crawler_events.py -v`
Expected: FAIL — the assertion about per-link events fires, since 200 `internal_link` events are emitted.

- [ ] **Step 3: Implement the counter**

In `_handle_result`, replace the two per-link `event_callback` calls with counter increments, and flush at most once per second (and once unconditionally at the end of `crawl`):

```python
        self._link_counts["internal"] += len(internal_links)
        self._link_counts["external"] += len(external_links)
        now = time.monotonic()
        if self.event_callback and now - self._last_link_flush >= 1.0:
            self._last_link_flush = now
            self.event_callback("link_progress", {
                "internal_total": self._link_counts["internal"],
                "external_total": self._link_counts["external"],
            })
```

Initialise `self._link_counts = {"internal": 0, "external": 0}` and `self._last_link_flush = 0.0` in `__init__`.

- [ ] **Step 4: Update the API's event translator**

In `routes.py`, remove `internal_link` and `external_link` from the tuple at line 42 and add:

```python
        elif event_type == "link_progress":
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast("crawl:links", {
                "session_id": session_id,
                "internal_total": payload["internal_total"],
                "external_total": payload["external_total"],
            }), loop)
```

- [ ] **Step 5: Update the frontend feed**

In `apps/frontend/lib/activity-feed.ts`, delete the `internal_link` / `external_link` cases and handle `crawl:links` by updating a running count rather than appending a row. Update `lib/__tests__/activity-feed.test.ts` to match: replace any per-link case with one asserting the counts render.

- [ ] **Step 6: Run both suites**

Run: `cd apps/backend && python -m pytest -q` then `cd apps/frontend && npm test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app apps/backend/tests/test_crawler_events.py apps/frontend/lib
git commit -m "perf: aggregate link events instead of one message per link"
```

### Task 10: Run the checks in a process pool during the crawl

**Files:**
- Modify: `apps/backend/app/services/audit_service.py`
- Test: `apps/backend/tests/test_pipeline_integration.py`

**Interfaces:**
- Consumes: `page_pipeline.analyze_page` (Task 5), `Crawler.crawl(on_page=...)` (Task 8).
- Produces: `audit_service._run_pipeline(crawler, options) -> PipelineOutput` with `.analyses: dict[str, PageAnalysis]`, `.degraded: bool`, `.partial: bool`.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_pipeline_integration.py`:

```python
"""Crawl and checks run concurrently, and a failure in either degrades rather
than destroys the audit."""

from concurrent.futures.process import BrokenProcessPool
from unittest.mock import patch

from app.crawler.crawler import Crawler, PageResult
from app.services import audit_service

HTML = "<html><head><title>T</title></head><body><h1>H</h1><p>words here plenty</p></body></html>"


def _crawler(page_count=5):
    home = "https://example.com/"
    children = [f"https://example.com/p{i}" for i in range(page_count - 1)]
    pages = {home: "".join(f"<a href='{c}'>x</a>" for c in children)}
    pages.update({c: HTML for c in children})
    crawler = Crawler(home, max_pages=page_count, max_depth=2, respect_robots=False)
    crawler._fetch = lambda url: PageResult(
        url=url, final_url=url, status_code=200, html=pages.get(url, HTML), headers={},
    )
    return crawler


def test_every_crawled_page_is_analysed():
    result = audit_service._build_audit_result(
        "https://example.com/", _crawler(), progress_callback=None, event_callback=None,
    )

    assert len(result["pages"]) == 5


def test_html_is_released_once_a_page_is_analysed():
    """Retaining HTML for every page is ~500 MB at 5000 pages. This is the
    assertion that keeps memory flat."""
    crawler = _crawler()

    audit_service._build_audit_result(
        "https://example.com/", crawler, progress_callback=None, event_callback=None,
    )

    assert all(not page.html for page in crawler.results.values()), (
        "PageResult.html must be cleared after analysis"
    )


def test_a_dead_process_pool_falls_back_in_process_and_reports_degraded():
    """Slow beats failed: if the pool cannot run, the audit still completes."""
    crawler = _crawler()

    with patch.object(audit_service, "_submit_to_pool", side_effect=BrokenProcessPool("pool died")):
        result = audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
        )

    assert len(result["pages"]) == 5
    assert result["degraded"] is True


def test_stopping_mid_crawl_still_produces_a_summary_marked_partial():
    crawler = _crawler(page_count=50)
    original_fetch = crawler._fetch

    def stop_after_three(url):
        if len(crawler.visited) >= 3:
            crawler.is_stopped = True
        return original_fetch(url)

    crawler._fetch = stop_after_three

    result = audit_service._build_audit_result(
        "https://example.com/", crawler, progress_callback=None, event_callback=None,
    )

    assert result["partial"] is True
    assert result["executive_summary"], "a stopped crawl still renders a dashboard"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_pipeline_integration.py -v`
Expected: FAIL — `test_html_is_released_once_a_page_is_analysed` (HTML is retained), `test_a_dead_process_pool_falls_back_in_process_and_reports_degraded` (`_submit_to_pool` does not exist), `test_stopping_mid_crawl...` (no `partial` key).

- [ ] **Step 3: Wire the pool into `_build_audit_result`**

```python
    pool = concurrent.futures.ProcessPoolExecutor(max_workers=os.cpu_count() or 2)
    analyses: Dict[str, page_pipeline.PageAnalysis] = {}
    degraded = False

    def on_page(result: PageResult):
        """Called by the crawler for each fetched page. Returns the links so the
        frontier can advance; the analysis lands in `analyses`."""
        nonlocal degraded
        payload = page_pipeline.PagePayload(...)
        try:
            analysis_result = _submit_to_pool(pool, payload)
        except (BrokenProcessPool, OSError) as exc:
            logger.error("Process pool unusable, falling back in-process: %s", exc, exc_info=exc)
            degraded = True
            analysis_result = page_pipeline.analyze_page(payload)
        except Exception as exc:
            logger.error("Audit checks failed for %s: %s", result.url, exc, exc_info=exc)
            analysis_result = page_pipeline.failed_analysis(result.url, exc)

        analyses[result.url] = analysis_result
        # Freeing the HTML here is what keeps resident memory flat: the crawler
        # otherwise retains every page's markup for the whole audit.
        result.html = ""
        return analysis_result.internal_links, analysis_result.external_links
```

`_submit_to_pool(pool, payload)` is a one-line seam — `return pool.submit(page_pipeline.analyze_page, payload).result()` — that exists so the test can force a pool failure without a real broken pool.

`page_pipeline.failed_analysis(url, exc)` returns a `PageAnalysis` with `failed=True` and the single critical `AUDIT_ERROR` issue, replacing the inline construction from commit `9884352`.

After the crawl, `partial = crawler.is_stopped` and both flags go into `result_data`:

```python
        "degraded": degraded,
        "partial": partial,
```

- [ ] **Step 4: Run the full suite**

Run: `cd apps/backend && python -m pytest -q`
Expected: PASS. Watch for hangs: a `ProcessPoolExecutor` not shut down in a `finally` will keep pytest alive.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services apps/backend/tests/test_pipeline_integration.py
git commit -m "perf: analyse pages in a process pool while the crawl continues

Checks stop being a phase appended to the crawl and overlap it instead, and each
page's HTML is freed as soon as it has been analysed. A dead pool degrades to
in-process analysis rather than failing the audit."
```

### Task 11: Persist to SQLite during the crawl

**Files:**
- Modify: `apps/backend/app/services/audit_service.py`
- Test: `apps/backend/tests/test_pipeline_integration.py` (extend)

**Interfaces:**
- Consumes: `SessionDB` (Task 3), `session_store.open_session` (Task 4), the pipeline (Task 10).
- Produces: `_build_audit_result` writes rows in batches of 50 through one writer thread and stores the summary; it returns the summary dict rather than the whole audit.

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/test_pipeline_integration.py`:

```python
def test_pages_are_written_to_the_session_database(tmp_path):
    crawler = _crawler()
    store = SessionStore(session_dir=tmp_path)

    with patch.object(audit_service, "session_store", store):
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None,
            event_callback=None, session_id="sess_pipeline",
        )

    db = store.get("sess_pipeline")
    rows, total = db.get_pages()
    assert total == 5
    assert db.get_summary()["executive_summary"]


def test_the_returned_payload_no_longer_carries_every_page_row(tmp_path):
    """The response is a summary now; rows are read from /api/pages."""
    crawler = _crawler()
    store = SessionStore(session_dir=tmp_path)

    with patch.object(audit_service, "session_store", store):
        result = audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None,
            event_callback=None, session_id="sess_summary",
        )

    assert "pages" not in result
    assert result["executive_summary"]
    assert result["page_count"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_pipeline_integration.py -v`
Expected: FAIL — `_build_audit_result() got an unexpected keyword argument 'session_id'`

- [ ] **Step 3: Add the writer thread and the summary**

`_build_audit_result` gains `session_id: str = "sess_adhoc"`, opens `session_store.open_session(session_id)`, and pushes each completed `PageAnalysis` onto a `queue.Queue`. One writer thread drains it, calling `db.add_pages(batch)` every 50 rows and on shutdown. Links and signatures are written in the same batch.

After the crawl, site-wide analysis, duplicates, redirects, recommendations and the executive summary are computed as they are today — except `build_link_graph_stats` reads its edges from `db.get_links()` — and stored with `db.set_summary(summary)`. The function returns the summary plus `page_count`, `degraded`, `partial` and `near_duplicate_mode`.

- [ ] **Step 4: Run the full suite**

Run: `cd apps/backend && python -m pytest -q`
Expected: PASS. Several existing tests read `result["pages"]`; update them to read from the DB in this commit, since the contract genuinely changed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services apps/backend/tests
git commit -m "feat: persist audit rows to SQLite as the crawl runs

The audit result becomes a summary; page rows live on disk and are read back a
page at a time."
```

---

## Phase D — API

### Task 12: Paginated endpoints, clustering, and the 5000-page cap

**Files:**
- Modify: `apps/backend/app/api/routes.py`, `apps/backend/app/schemas/schemas.py`, `apps/backend/app/models/session_db.py` (add clustering queries), `docs/api.md`
- Test: `apps/backend/tests/test_api_pagination.py`

**Interfaces:**
- Consumes: `SessionDB` readers (Task 3), summaries (Task 11).
- Produces: `GET /api/pages`, `/api/issues`, `/api/duplicates` returning `{items, total, offset, limit}`; `/api/architecture` returning `{nodes, links, clustered: true}` by default and one cluster's pages under `?expand=<segment>`; `/api/audit/latest` returning the summary only.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_api_pagination.py`:

```python
"""Endpoint envelopes and boundaries.

/api/pages returned a bare array of every row. At 5000 pages that is tens of
megabytes in one response, so it paginates and reports a total.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(seeded_session):
    return TestClient(app)


def test_pages_returns_a_paginated_envelope(client, seeded_session):
    response = client.get(f"/api/pages?session_id={seeded_session}&limit=2")

    body = response.json()
    assert response.status_code == 200
    assert len(body["items"]) == 2
    assert body["total"] == 10
    assert body["offset"] == 0
    assert body["limit"] == 2


def test_limit_above_the_maximum_is_rejected(client, seeded_session):
    response = client.get(f"/api/pages?session_id={seeded_session}&limit=5000")

    assert response.status_code == 422


def test_an_unknown_sort_column_is_rejected_not_ignored(client, seeded_session):
    response = client.get(f"/api/pages?session_id={seeded_session}&sort=url;DROP TABLE pages")

    assert response.status_code == 422


def test_latest_returns_a_summary_without_page_rows(client, seeded_session):
    body = client.get(f"/api/audit/latest?session_id={seeded_session}").json()

    assert "executive_summary" in body
    assert "pages" not in body
    assert body["page_count"] == 10


def test_architecture_is_clustered_by_path_segment_by_default(client, seeded_session):
    body = client.get(f"/api/architecture?session_id={seeded_session}").json()

    assert body["clustered"] is True
    assert {n["id"] for n in body["nodes"]} >= {"home", "/blog"}


def test_expanding_a_cluster_returns_its_pages(client, seeded_session):
    body = client.get(f"/api/architecture?session_id={seeded_session}&expand=/blog").json()

    assert body["clustered"] is False
    assert all("/blog" in n["url"] for n in body["nodes"])
```

Add a `seeded_session` fixture in `tests/conftest.py` that opens a `SessionDB` in `tmp_path`, inserts 10 pages (some under `/blog`), sets a summary, and registers it with the store the app uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_api_pagination.py -v`
Expected: FAIL — `/api/pages` returns a bare list, so `body["items"]` raises `TypeError`.

- [ ] **Step 3: Rewrite the read endpoints**

```python
SORTABLE_PAGE_COLUMNS = Literal[
    "url", "depth", "status", "word_count", "response_time_ms",
    "internal_links_count", "issue_count",
]


@router.get("/pages")
def get_pages(
    session_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort: SORTABLE_PAGE_COLUMNS = Query("depth"),
    order: Literal["asc", "desc"] = Query("asc"),
    filter: Optional[str] = Query(None, max_length=200),
    status: Optional[int] = Query(None),
    has_issues: Optional[bool] = Query(None),
):
    db = _require_session(session_id)
    items, total = db.get_pages(
        offset=offset, limit=limit, sort=sort, order=order,
        filter_text=filter, status=status, has_issues=has_issues,
    )
    return {"items": items, "total": total, "offset": offset, "limit": limit}
```

`sort` typed as a `Literal` is what turns an unknown column into a 422 rather than a `ValueError` from the DB layer — both guards stay, since the DB is also called from the CLI.

`_require_session(session_id)` replaces the repeated `if session_id not in active_sessions` check and raises the same 404.

`/api/issues` and the new `/api/duplicates` follow the identical envelope. `/api/architecture` calls two new `SessionDB` methods: `get_clusters()` (group by first path segment, `home` for the start URL, largest 60 plus an `other` node) and `get_cluster_pages(segment)`.

In `schemas.py`:

```python
# 5000 is the Full Site Crawl preset. Configurable because the 1 GB E2.1.Micro
# shape documented as an alternative in docs/deployment-oracle.md cannot hold a
# crawl this size.
MAX_PAGES_LIMIT = int(os.getenv("MAX_PAGES_LIMIT", "5000"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_api_pagination.py -v && python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Document the breaking changes**

In `docs/api.md`, mark `/api/audit/latest`, `/api/pages`, `/api/issues` and `/api/architecture` as changed, with before/after response shapes, and note that direct API consumers must update.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app apps/backend/tests docs/api.md
git commit -m "feat!: paginate the read endpoints and cap crawls at 5000 pages

BREAKING: /api/pages and /api/issues return {items,total,offset,limit} instead
of bare arrays, /api/audit/latest returns a summary without page rows, and
/api/architecture returns path clusters by default."
```

---

## Phase E — Frontend

### Task 13: Stop putting the audit in localStorage; fetch per panel

**Files:**
- Modify: `apps/frontend/lib/audit-context.tsx`
- Create: `apps/frontend/lib/api-hooks.ts`
- Modify: `apps/frontend/services/api.ts`, `apps/frontend/components/pages-table.tsx`, `apps/frontend/components/issue-center.tsx`
- Test: `apps/frontend/lib/__tests__/audit-context.test.tsx`, `apps/frontend/components/__tests__/pages-table.test.tsx`

**Interfaces:**
- Consumes: Task 12's endpoints.
- Produces: `usePaginated<T>(fetcher, deps) -> {items, total, page, setPage, isLoading, error}` from `lib/api-hooks.ts`.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/lib/__tests__/audit-context.test.tsx`:

```tsx
/**
 * The audit payload must never reach localStorage.
 *
 * The whole result was JSON.stringify'd into it (audit-context.tsx:56). The
 * quota is ~5MB, so a large audit threw QuotaExceededError before the dashboard
 * could render.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

import { AuditProvider } from "@/lib/audit-context";

describe("audit context persistence", () => {
  beforeEach(() => window.localStorage.clear());

  it("stores only the session id and summary", async () => {
    render(<AuditProvider><div /></AuditProvider>);

    await waitFor(() => {
      const stored = window.localStorage.getItem("audit-state");
      if (!stored) return;
      const parsed = JSON.parse(stored);
      expect(parsed.pages).toBeUndefined();
      expect(Object.keys(parsed)).toEqual(expect.arrayContaining(["sessionId"]));
      expect(stored.length).toBeLessThan(50_000);
    });
  });

  it("renders when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });

    expect(() => render(<AuditProvider><div /></AuditProvider>)).not.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npm test -- audit-context`
Expected: FAIL — the stored object contains the full payload, and an unguarded `setItem` throws.

- [ ] **Step 3: Slim the context and guard storage**

```tsx
// Only the identifier and the summary are persisted. The page rows live on the
// server and are fetched a page at a time -- the whole payload used to be
// stringified here, and a large audit exceeded the ~5MB quota before the
// dashboard rendered.
const persist = (state: PersistedState) => {
  try {
    window.localStorage.setItem("audit-state", JSON.stringify({
      sessionId: state.sessionId,
      summary: state.summary,
    }));
  } catch {
    // Private mode, blocked site data, or a full quota. The dashboard works
    // without persistence; it must not fail because of it.
  }
};
```

Every read is wrapped in the same way.

- [ ] **Step 4: Add `usePaginated` and wire the two tables**

```ts
export function usePaginated<T>(
  fetcher: (offset: number, limit: number) => Promise<{ items: T[]; total: number }>,
  deps: unknown[] = [],
  limit = 50,
) { /* offset state, loading, error, refetch on deps change */ }
```

`pages-table.tsx` and `issue-center.tsx` call it instead of slicing an array from context, and render server-driven pagination controls.

- [ ] **Step 5: Run the frontend suite**

Run: `cd apps/frontend && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/lib apps/frontend/components apps/frontend/services
git commit -m "fix: keep the audit payload out of localStorage, paginate tables

The whole result was stringified into a ~5MB-quota store, so a large audit threw
before the dashboard rendered."
```

### Task 14: Cluster the architecture graph

**Files:**
- Modify: `apps/frontend/components/site-architecture-graph.tsx`
- Test: `apps/frontend/components/__tests__/site-architecture-graph.test.tsx`

**Interfaces:**
- Consumes: `/api/architecture` and `?expand=` (Task 12).
- Produces: no new exports; the component owns its expansion state.

- [ ] **Step 1: Write the failing test**

```tsx
/**
 * At 5000 pages a node-per-page graph is ~5000 nodes and a few hundred thousand
 * edges, which no browser draws interactively. Pages group by first path
 * segment and expand on click.
 */
it("renders one node per cluster, not per page", async () => {
  mockArchitecture({ clustered: true, nodes: [
    { id: "home", label: "home", count: 1 },
    { id: "/blog", label: "/blog", count: 412 },
    { id: "/products", label: "/products", count: 2847 },
  ], links: [] });

  render(<SiteArchitectureGraph sessionId="sess_1" />);

  expect(await screen.findAllByTestId("graph-node")).toHaveLength(3);
  expect(await screen.findByText("2,847")).toBeInTheDocument();
});

it("expands one cluster into its pages on click", async () => {
  /* ...mock ?expand=/blog, click the node, assert the expanded pages render
     and the other clusters stay collapsed... */
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npm test -- site-architecture-graph`
Expected: FAIL — the component renders one node per page from context.

- [ ] **Step 3: Implement clustering**

Fetch `/api/architecture` on mount, render cluster nodes sized by `count`, and on click fetch `?expand=<id>` and render that cluster's pages while others stay collapsed. A `clustered: false` response (the flat-site fallback from Task 12) renders the depth-limited view with the cap note.

- [ ] **Step 4: Run the frontend suite**

Run: `cd apps/frontend && npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/components
git commit -m "feat: cluster the architecture graph by path segment"
```

### Task 15: Re-enable the preset and correct the stale copy

**Files:**
- Modify: `apps/frontend/app/page.tsx:67-93`, `docs/deployment-oracle.md`, `README.md`
- Test: `apps/frontend/components/__tests__/presets.test.tsx`

**Interfaces:**
- Consumes: everything above.
- Produces: the Full Site Crawl preset, selectable.

- [ ] **Step 1: Write the failing test**

```tsx
/**
 * The preset has been disabled since 551c5b9. Its comment blamed quadratic
 * duplicate detection, which 8d29bcd replaced and Task 6 replaced again.
 */
it("offers Full Site Crawl as a selectable preset", async () => {
  render(<LandingPage />);

  const preset = screen.getByRole("button", { name: /Full Site Crawl/i });

  expect(preset).not.toBeDisabled();
  await userEvent.click(preset);
  expect(screen.getByLabelText(/max pages/i)).toHaveValue(5000);
});

it("states the real page ceiling, not the stale one", () => {
  render(<LandingPage />);

  expect(screen.getByText(/up to 5,000 pages/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npm test -- presets`
Expected: FAIL — the preset is disabled and the slider caps at 1000.

- [ ] **Step 3: Re-enable it**

In `apps/frontend/app/page.tsx`, delete `disabled: true`, `disabledReason`, and the entire stale comment block above them. Set `pages: 5000`. Raise the slider and the `Math.min(Math.max(maxPages, 1), 1000)` clamp at line 176 to 5000. Correct the Enterprise Warning to name 5000 pages and the real expected duration.

In `docs/deployment-oracle.md`, replace the memory section's claim that `max_pages` is capped at 1000 with the new cap, and state that a 5000-page crawl assumes the 2 OCPU / 12 GB shape.

- [ ] **Step 4: Run both suites**

Run: `cd apps/frontend && npm test` then `cd apps/backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Run the perf harness before declaring this done**

Create `apps/backend/perf/crawl_harness.py`: serve a synthetic 1000-page site from `http.server` on localhost, run one audit against it, and print wall-clock seconds and peak RSS. Fail loudly above 180 s or 1.5 GB.

Run: `cd apps/backend && python perf/crawl_harness.py`
Expected: under both ceilings. If not, the lever is per-page check cost — the metadata block in `page_pipeline` walks the parsed tree several times and can be folded into one pass. Do not add pool workers; the deployed shape has 2 OCPUs.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend apps/backend/perf docs README.md
git commit -m "feat: re-enable Full Site Crawl at 5000 pages

The preset was disabled for a quadratic duplicate pass that no longer exists.
Verified against the perf harness on a synthetic 1000-page site."
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Stage 1, continuous fetch pool | 8 |
| Event throttling | 9 |
| Stage 2, process pool + purity | 5, 10 |
| HTML released after analysis | 10 |
| Stage 3, batched writer | 11 |
| SQLite schema and retention | 3, 4 |
| MinHash + LSH above 500 pages | 6, 7 |
| PageRank (networkx declaration) | Already fixed, commit `f4ea190` |
| API contract, all five endpoints | 12 |
| `MAX_PAGES_LIMIT` 1000 → 5000 | 12 |
| localStorage, per-panel fetching | 13 |
| Architecture clustering | 12 (server), 14 (client) |
| Preset re-enabled, stale copy | 15 |
| CLI dedup, parity assertions migrated | 1, 2 |
| Error handling: page failure | Already fixed, commit `9884352`; carried across the pool in 10 |
| Error handling: degraded, partial, backpressure | 10 |
| Perf harness | 15 |

No spec requirement is unassigned.

**Known gap, stated rather than hidden:** the spec's `CRAWL_HTML_BUDGET` backpressure is declared in Task 8's config but only enforced implicitly, through Task 8's `max_in_flight` bound of `2 x concurrency`. At 32 workers that caps un-analysed HTML at ~64 pages, which is well inside 256 MB for any plausible page size. If the harness in Task 15 shows memory climbing anyway, add explicit byte accounting there rather than earlier — it is dead code until proven necessary.

**Type consistency:** `PageAnalysis` is produced in Task 5 and consumed unchanged in 10 and 11. `SessionDB.get_pages`/`get_issues` return `(rows, total)` in Task 3 and are unpacked that way in Task 12. `signature()` returns `bytes | None` in Task 6 and every consumer (7, 10, 11) handles `None`. `near_duplicates` returns the same `{"url_a","url_b","similarity"}` shape as the exact path, so Task 7's selector can return either without the caller branching.
