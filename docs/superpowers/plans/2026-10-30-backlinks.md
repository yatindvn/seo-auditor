# Backlinks / Site Explorer (Phase 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each project gets a backlink profile from DataForSEO:
- the authority score (labelled as DataForSEO's) and totals
- top referring domains
- new, lost and broken links
- growth charts from stored snapshots and history
- an on-demand competitor link gap

Broken pages with backlinks are flagged in audits. Weekly refresh is opt-in,
and every request is capped and dry-run safe.

**Architecture:**
- `app/backlinks/` holds:
  - `provider.py`: the interface, DataForSEO and dry run, plus the factory
  - `snapshot.py`: `refresh_project`
  - `gap.py`: the link gap
  - `audit.py`: the broken-backlink issues
- Migration 0009 extends `backlink_snapshots` and adds two child tables plus
  project fields.
- An API router, a scheduler job (opt-in, never dry run) and a pipeline
  step that reads the latest snapshot.
- A Backlinks tab in the frontend.

**Tech Stack:** Python, requests (via the existing `post_task`), SQLAlchemy/Alembic, APScheduler, FastAPI, pytest; Next.js 14, Recharts, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-backlinks-design.md`

## Global Constraints

- **Live only when** `SERP_PROVIDER == "dataforseo"`, `not SERP_DRY_RUN`, and `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` are set. Otherwise `DryRunBacklinks`. No credentials exist today.
- **Every DataForSEO request** first calls `spend.reserve("dataforseo_backlinks", DATAFORSEO_BACKLINKS_DAILY_CAP)` (default 20).
- **Snapshot:** summary, referring domains (100), backlinks new/lost/broken (100 each, since today − 30 days), plus history (12 months) on the first snapshot only. All calls finish before one write transaction.
- **Authority** is always labelled "DataForSEO rank, 0–1000".
- **Weekly schedule** is opt-in per project (`backlink_schedule = "weekly"`). The scheduler never runs on a dry-run provider.
- **Link gap:** 1–5 competitors (default: the project's `Competitor` rows). Sorted by linked_count desc, then rank desc. Not stored.
- **`BACKLINK_TO_BROKEN_PAGE`** (warning): a crawled page with status ≥ 400 whose normalised URL is a broken-backlink target in the latest snapshot. No API call during audits.
- **No FK change:** the old `backlink_snapshots.project_id` FK is unnamed in 0001 and left as is. The new child tables cascade from snapshots.
- **Commits:** the full backend suite must exit 0 before each commit.

---

### Task 1: Provider layer

**Files:**
- Create: `apps/backend/app/backlinks/__init__.py`, `apps/backend/app/backlinks/provider.py`, `apps/backend/tests/test_backlinks_provider.py`
- Modify: `apps/backend/app/config/config.py`

**Interfaces:**
- Produces:
  - dataclasses `BacklinkSummary`, `RefDomain`, `Backlink`, `HistoryPoint`, `GapDomain`
  - `DataForSeoBacklinks(login, password, cap, http=requests, factory=None)`
  - `DryRunBacklinks()`
  - `get_backlink_provider(cfg=config)`
  - `months_back(today, months) -> date`
  - config `DATAFORSEO_BACKLINKS_DAILY_CAP`

- [ ] **Step 1: Config**

In `app/config/config.py`, after `DATAFORSEO_LABS_DAILY_CAP`:

```python
# Hard daily cap on DataForSEO Backlinks API requests (Phase 6). About $0.024
# a request plus $0.000036 a row; a snapshot is 5 requests (~$0.25).
DATAFORSEO_BACKLINKS_DAILY_CAP = int(os.getenv("DATAFORSEO_BACKLINKS_DAILY_CAP", "20"))
```

- [ ] **Step 2: Write the failing test**

```python
"""Backlinks provider: DataForSEO request bodies and parsing, the cap, dry run."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.backlinks import provider as bp
from app.backlinks.provider import DataForSeoBacklinks, DryRunBacklinks, get_backlink_provider, months_back
from app.config import config
from app.providers.serp import ProviderError, ProviderSkipped


def ok(result):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"status_code": 20000, "tasks": [{"status_code": 20000, "result": result}]}
    return resp


class Http:
    def __init__(self, *responses):
        self.calls, self.responses = [], list(responses)

    def post(self, url, json=None, auth=None, timeout=None):
        self.calls.append((url.split("/v3/")[1], json[0]))
        return self.responses.pop(0)


def test_summary():
    http = Http(ok([{"rank": 412, "backlinks": 18230, "referring_domains": 640, "broken_backlinks": 37}]))
    s = DataForSeoBacklinks("l", "p", cap=5, http=http).summary("shop.com")
    assert http.calls == [("backlinks/summary/live", {"target": "shop.com", "include_subdomains": True})]
    assert (s.authority, s.backlinks, s.referring_domains, s.broken_backlinks) == (412, 18230, 640, 37)


def test_referring_domains():
    http = Http(ok([{"items": [{"domain": "news.com", "rank": 700, "backlinks": 12, "first_seen": "2025-01-02 10:00:00 +00:00"}]}]))
    rows = DataForSeoBacklinks("l", "p", cap=5, http=http).referring_domains("shop.com", 100)
    assert http.calls[0] == ("backlinks/referring_domains/live", {"target": "shop.com", "limit": 100, "order_by": ["rank,desc"]})
    assert rows[0].domain == "news.com" and rows[0].rank == 700 and rows[0].backlinks == 12


@pytest.mark.parametrize("kind, filters", [
    ("new", ["first_seen", ">=", "2026-09-30"]),
    ("lost", [["is_lost", "=", True], "and", ["last_seen", ">=", "2026-09-30"]]),
    ("broken", ["is_broken", "=", True]),
])
def test_backlink_filters(kind, filters):
    item = {"url_from": "https://news.com/a", "url_to": "https://shop.com/x", "anchor": "great shop",
            "domain_from_rank": 650, "dofollow": True, "first_seen": "2026-10-01 00:00:00 +00:00",
            "last_seen": "2026-10-20 00:00:00 +00:00", "url_to_status_code": 404}
    http = Http(ok([{"items": [item]}]))
    links = DataForSeoBacklinks("l", "p", cap=5, http=http).backlinks("shop.com", kind, date(2026, 9, 30), 100)
    path, task = http.calls[0]
    assert path == "backlinks/backlinks/live"
    assert task == {"target": "shop.com", "mode": "as_is", "limit": 100, "order_by": ["domain_from_rank,desc"], "filters": filters}
    assert (links[0].url_to, links[0].anchor, links[0].domain_from_rank, links[0].dofollow, links[0].target_status) == (
        "https://shop.com/x", "great shop", 650, True, 404)


def test_history_months():
    http = Http(ok([{"items": [{"date": "2026-08-01 00:00:00 +00:00", "rank": 400, "backlinks": 17000, "referring_domains": 600},
                               {"date": "bad"}]}]))
    pts = DataForSeoBacklinks("l", "p", cap=5, http=http).history("shop.com", 12, today=date(2026, 10, 30))
    assert http.calls[0] == ("backlinks/history/live", {"target": "shop.com", "date_from": "2025-10-01", "date_to": "2026-10-30"})
    assert [(p.month, p.authority, p.referring_domains) for p in pts] == [(date(2026, 8, 1), 400, 600)]
    assert months_back(date(2026, 1, 15), 3) == date(2025, 10, 1)


def test_intersection():
    item = {"domain_intersection": {"1": {"domain": "blog.io", "rank": 500, "backlinks": 3},
                                    "2": {"domain": "blog.io", "rank": 500, "backlinks": 1}}}
    only_one = {"domain_intersection": {"1": {"domain": "news.com", "rank": 600, "backlinks": 2}}}
    http = Http(ok([{"items": [item, only_one]}]))
    rows = DataForSeoBacklinks("l", "p", cap=5, http=http).intersection(["rival.com", "other.com"], "shop.com", 100)
    assert http.calls[0] == ("backlinks/domain_intersection/live", {
        "targets": {"1": "rival.com", "2": "other.com"}, "exclude_targets": ["shop.com"], "limit": 100,
        "order_by": ["1.rank,desc"]})
    assert [(r.domain, r.rank, r.linked_competitors) for r in rows] == [
        ("blog.io", 500, {"rival.com": 3, "other.com": 1}), ("news.com", 600, {"rival.com": 2})]


def test_errors_and_cap(monkeypatch):
    bad = MagicMock(status_code=200)
    bad.json.return_value = {"status_code": 40104, "status_message": "Please visit https://app.dataforseo.com/backlinks-subscription"}
    with pytest.raises(ProviderError) as err:
        DataForSeoBacklinks("l", "p", cap=5, http=Http(bad)).summary("shop.com")
    assert "40104" in str(err.value)
    http = Http()
    with pytest.raises(ProviderSkipped):
        DataForSeoBacklinks("l", "p", cap=0, http=http).summary("shop.com")
    assert http.calls == []


def test_dry_run_is_deterministic_and_complete():
    a, b = DryRunBacklinks(), DryRunBacklinks()
    assert a.summary("shop.com") == b.summary("shop.com") and a.dry_run is True
    assert len(a.referring_domains("shop.com", 100)) >= 10
    broken = a.backlinks("shop.com", "broken", date(2026, 9, 30), 100)
    assert broken and all(l.url_to.startswith("https://shop.com/") and l.target_status == 404 for l in broken)
    assert len(a.history("shop.com", 12, today=date(2026, 10, 30))) == 12
    gap = a.intersection(["rival.com", "other.com"], "shop.com", 100)
    assert gap and max(len(g.linked_competitors) for g in gap) == 2


def test_factory(monkeypatch):
    assert isinstance(get_backlink_provider(), DryRunBacklinks)
    monkeypatch.setattr(config, "SERP_PROVIDER", "dataforseo")
    monkeypatch.setattr(config, "SERP_DRY_RUN", False)
    monkeypatch.setattr(config, "DATAFORSEO_LOGIN", "l")
    monkeypatch.setattr(config, "DATAFORSEO_PASSWORD", "p")
    assert isinstance(get_backlink_provider(), DataForSeoBacklinks)
    monkeypatch.setattr(config, "SERP_DRY_RUN", True)
    assert isinstance(get_backlink_provider(), DryRunBacklinks)
```

- [ ] **Step 3: Run and watch it fail**

Run: `cd apps/backend && python -m pytest tests/test_backlinks_provider.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.backlinks'`

- [ ] **Step 4: Implement**

`app/backlinks/__init__.py`:

```python
"""Backlinks (Phase 6): who links to a site, how that changes, and who links to competitors instead."""
```

`app/backlinks/provider.py`:

```python
"""Backlinks behind a provider interface: DataForSEO's Backlinks API and a
deterministic dry run. DataForSEO field names follow its v3 docs; the parsers
are checked against its free sandbox once credentials exist."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests

from app.config import config
from app.providers import spend
from app.providers.dataforseo import post_task

BUDGET = "dataforseo_backlinks"
SUMMARY = "backlinks/summary/live"
REFERRING_DOMAINS = "backlinks/referring_domains/live"
BACKLINKS = "backlinks/backlinks/live"
HISTORY = "backlinks/history/live"
INTERSECTION = "backlinks/domain_intersection/live"


@dataclass(frozen=True)
class BacklinkSummary:
    authority: Optional[int]
    backlinks: int
    referring_domains: int
    broken_backlinks: int


@dataclass(frozen=True)
class RefDomain:
    domain: str
    rank: Optional[int]
    backlinks: int
    first_seen: Optional[str]


@dataclass(frozen=True)
class Backlink:
    url_from: str
    url_to: str
    anchor: str
    domain_from_rank: Optional[int]
    dofollow: bool
    first_seen: Optional[str]
    last_seen: Optional[str]
    target_status: Optional[int]


@dataclass(frozen=True)
class HistoryPoint:
    month: date
    authority: Optional[int]
    backlinks: int
    referring_domains: int


@dataclass(frozen=True)
class GapDomain:
    domain: str
    rank: Optional[int]
    linked_competitors: Dict[str, int] = field(default_factory=dict)


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _opt_int(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def months_back(today: date, months: int) -> date:
    """The first day of the month `months` months before today's month."""
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _items(result: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return (result[0].get("items") or []) if result else []


class DataForSeoBacklinks:
    name = "dataforseo"
    dry_run = False

    def __init__(self, login: str, password: str, cap: int, http=requests, factory=None) -> None:
        self._auth = (login, password)
        self._http = http
        self.cap = cap
        self._factory = factory

    def _result(self, path: str, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        spend.reserve(BUDGET, self.cap, factory=self._factory)     # ProviderSkipped at the cap
        return post_task(self._http, self._auth, path, task).get("result") or []

    def summary(self, target: str) -> BacklinkSummary:
        result = self._result(SUMMARY, {"target": target, "include_subdomains": True})
        d = result[0] if result else {}
        return BacklinkSummary(_opt_int(d.get("rank")), _int(d.get("backlinks")), _int(d.get("referring_domains")),
                               _int(d.get("broken_backlinks")))

    def referring_domains(self, target: str, limit: int = 100) -> List[RefDomain]:
        result = self._result(REFERRING_DOMAINS, {"target": target, "limit": limit, "order_by": ["rank,desc"]})
        return [RefDomain(i["domain"], _opt_int(i.get("rank")), _int(i.get("backlinks")), i.get("first_seen"))
                for i in _items(result) if i.get("domain")]

    def backlinks(self, target: str, kind: str, since: date, limit: int = 100) -> List[Backlink]:
        filters = {
            "new": ["first_seen", ">=", since.isoformat()],
            "lost": [["is_lost", "=", True], "and", ["last_seen", ">=", since.isoformat()]],
            "broken": ["is_broken", "=", True],
        }[kind]
        result = self._result(BACKLINKS, {"target": target, "mode": "as_is", "limit": limit,
                                          "order_by": ["domain_from_rank,desc"], "filters": filters})
        return [Backlink(i.get("url_from") or "", i.get("url_to") or "", i.get("anchor") or "",
                         _opt_int(i.get("domain_from_rank")), bool(i.get("dofollow")), i.get("first_seen"),
                         i.get("last_seen"), _opt_int(i.get("url_to_status_code")))
                for i in _items(result) if i.get("url_from") and i.get("url_to")]

    def history(self, target: str, months: int = 12, today: Optional[date] = None) -> List[HistoryPoint]:
        today = today or date.today()
        result = self._result(HISTORY, {"target": target, "date_from": months_back(today, months).isoformat(),
                                        "date_to": today.isoformat()})
        points = []
        for i in _items(result):
            try:
                month = date.fromisoformat((i.get("date") or "")[:10]).replace(day=1)
            except ValueError:
                continue
            points.append(HistoryPoint(month, _opt_int(i.get("rank")), _int(i.get("backlinks")),
                                       _int(i.get("referring_domains"))))
        return points

    def intersection(self, competitors: List[str], exclude: str, limit: int = 100) -> List[GapDomain]:
        targets = {str(n): c for n, c in enumerate(competitors, start=1)}
        result = self._result(INTERSECTION, {"targets": targets, "exclude_targets": [exclude], "limit": limit,
                                             "order_by": ["1.rank,desc"]})
        rows = []
        for item in _items(result):
            per = item.get("domain_intersection") or {}
            domain, rank, linked = None, None, {}
            for key, competitor in targets.items():
                entry = per.get(key)
                if not entry:
                    continue
                domain = domain or entry.get("domain")
                rank = rank if rank is not None else _opt_int(entry.get("rank"))
                linked[competitor] = _int(entry.get("backlinks"))
            if domain:
                rows.append(GapDomain(domain, rank, linked))
        return rows


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


class DryRunBacklinks:
    """Stable made-up data, so the tab and the audit join can be tried without
    DataForSEO. Everything it produces is stored as dry_run."""

    name = "dataforseo_dry_run"
    dry_run = True

    def summary(self, target: str) -> BacklinkSummary:
        s = _seed(target)
        return BacklinkSummary(150 + s % 300, 1000 + s % 9000, 80 + s % 400, 3 + s % 20)

    def referring_domains(self, target: str, limit: int = 100) -> List[RefDomain]:
        base = _seed(target) % 200
        return [RefDomain(f"site{n}.example-{target.split('.')[0]}.com", 900 - n * 25 - base % 20, 40 // (n + 1) + 1,
                          f"2026-0{1 + n % 9}-15 00:00:00 +00:00") for n in range(min(limit, 30))]

    def backlinks(self, target: str, kind: str, since: date, limit: int = 100) -> List[Backlink]:
        rows = []
        for n in range(min(limit, 10)):
            path = {"new": f"page-{n}", "lost": f"article-{n}", "broken": f"old-page-{n}"}[kind]
            rows.append(Backlink(f"https://blog{n}.example.net/post-{_seed(target, kind, str(n)) % 900}",
                                 f"https://{target}/{path}", f"{target.split('.')[0]} {kind} link {n}",
                                 800 - n * 40, n % 3 != 0, (since + timedelta(days=n)).isoformat(),
                                 (since + timedelta(days=n + 5)).isoformat(), 404 if kind == "broken" else 200))
        return rows

    def history(self, target: str, months: int = 12, today: Optional[date] = None) -> List[HistoryPoint]:
        today = today or date.today()
        s = _seed(target)
        out = []
        for n in range(months):
            month = months_back(today, months - n)
            out.append(HistoryPoint(month, 140 + s % 300 + n * 3, 800 + s % 9000 + n * 60, 60 + s % 400 + n * 4))
        return out

    def intersection(self, competitors: List[str], exclude: str, limit: int = 100) -> List[GapDomain]:
        rows = []
        for n in range(min(limit, 25)):
            linked = {c: 1 + (_seed(c, str(n)) % 6) for i, c in enumerate(competitors) if (n + i) % 3 != 2}
            if linked:
                rows.append(GapDomain(f"outreach{n}.example.org", 850 - n * 20, linked))
        return rows


def get_backlink_provider(cfg=config):
    """Live DataForSEO only when it's switched on and credentials exist;
    otherwise made-up data, never a silent spend."""
    if (cfg.SERP_PROVIDER == "dataforseo" and not cfg.SERP_DRY_RUN
            and cfg.DATAFORSEO_LOGIN and cfg.DATAFORSEO_PASSWORD):
        return DataForSeoBacklinks(cfg.DATAFORSEO_LOGIN, cfg.DATAFORSEO_PASSWORD, cfg.DATAFORSEO_BACKLINKS_DAILY_CAP)
    return DryRunBacklinks()
```

- [ ] **Step 5: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_backlinks_provider.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/backlinks apps/backend/app/config/config.py apps/backend/tests/test_backlinks_provider.py
git commit -m "feat(backlinks): DataForSEO Backlinks provider with daily cap, and a dry run"
```

---

### Task 2: Storage and the project schedule

**Files:**
- Create: `apps/backend/alembic/versions/0009_backlinks.py`, `apps/backend/tests/test_backlinks_storage.py`
- Modify: `apps/backend/app/db/models.py`, `apps/backend/app/api/projects.py`, `apps/backend/tests/test_db_schema.py`

**Interfaces:**
- Produces:
  - `BacklinkSnapshot` gains `authority, backlinks, referring_domains, broken_backlinks, source, period, dry_run`
  - models `BacklinkRefDomain`, `BacklinkLink`
  - `Project.backlink_schedule`, `Project.last_backlink_refresh_at`
  - the project JSON gains both; `PATCH` accepts `backlink_schedule: "weekly" | null`

- [ ] **Step 1: Write the failing test**

```python
"""Backlink tables and the opt-in weekly schedule."""

from fastapi.testclient import TestClient

from app.main import app


def test_schedule_is_off_by_default_and_opt_in():
    client = TestClient(app)
    project = client.post("/api/projects", json={"domain": "shop.com"}).json()
    assert project["backlink_schedule"] is None and project["last_backlink_refresh_at"] is None
    on = client.patch(f"/api/projects/{project['id']}", json={"backlink_schedule": "weekly"}).json()
    assert on["backlink_schedule"] == "weekly"
    assert client.patch(f"/api/projects/{project['id']}", json={"backlink_schedule": None}).json()["backlink_schedule"] is None
    assert client.patch(f"/api/projects/{project['id']}", json={"backlink_schedule": "hourly"}).status_code == 422
```

Add `"backlink_ref_domains", "backlink_links"` to `TABLES` in `tests/test_db_schema.py`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_backlinks_storage.py tests/test_db_schema.py -q`
Expected: FAIL (a `KeyError` for `backlink_schedule`, and missing tables).

- [ ] **Step 3: Models**

In `app/db/models.py`:
- Change the sqlalchemy import to include `false` (next to `true`).
- In `class Project`, after `last_gsc_sync_at`, add:

```python
    backlink_schedule: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_backlink_refresh_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- In `class BacklinkSnapshot`, after `metrics_json`, add:

```python
    authority: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backlinks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    referring_domains: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    broken_backlinks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(16), default="snapshot", server_default="snapshot")
    period: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
```

- Append:

```python
class BacklinkRefDomain(Base):
    """A top referring domain in one backlink snapshot (Phase 6)."""
    __tablename__ = "backlink_ref_domains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("backlink_snapshots.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255))
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backlinks: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class BacklinkLink(Base):
    """A new, lost or broken backlink in one snapshot."""
    __tablename__ = "backlink_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("backlink_snapshots.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    url_from: Mapped[str] = mapped_column(Text)
    url_to: Mapped[str] = mapped_column(Text)
    anchor: Mapped[str] = mapped_column(Text, default="")
    domain_from_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dofollow: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    last_seen: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    target_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: Migration `alembic/versions/0009_backlinks.py`**

```python
"""backlinks

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('backlink_schedule', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('last_backlink_refresh_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('backlink_snapshots') as batch_op:
        batch_op.add_column(sa.Column('authority', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('backlinks', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('referring_domains', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('broken_backlinks', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('source', sa.String(length=16), server_default='snapshot', nullable=False))
        batch_op.add_column(sa.Column('period', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('dry_run', sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table('backlink_ref_domains',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('backlinks', sa.Integer(), nullable=False),
    sa.Column('first_seen', sa.String(length=40), nullable=True),
    sa.ForeignKeyConstraint(['snapshot_id'], ['backlink_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_backlink_ref_domains_snapshot_id'), 'backlink_ref_domains', ['snapshot_id'], unique=False)

    op.create_table('backlink_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('url_from', sa.Text(), nullable=False),
    sa.Column('url_to', sa.Text(), nullable=False),
    sa.Column('anchor', sa.Text(), nullable=False),
    sa.Column('domain_from_rank', sa.Integer(), nullable=True),
    sa.Column('dofollow', sa.Boolean(), nullable=False),
    sa.Column('first_seen', sa.String(length=40), nullable=True),
    sa.Column('last_seen', sa.String(length=40), nullable=True),
    sa.Column('target_status', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['snapshot_id'], ['backlink_snapshots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_backlink_links_snapshot_id'), 'backlink_links', ['snapshot_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_backlink_links_snapshot_id'), table_name='backlink_links')
    op.drop_table('backlink_links')
    op.drop_index(op.f('ix_backlink_ref_domains_snapshot_id'), table_name='backlink_ref_domains')
    op.drop_table('backlink_ref_domains')
    with op.batch_alter_table('backlink_snapshots') as batch_op:
        for column in ('dry_run', 'period', 'source', 'broken_backlinks', 'referring_domains', 'backlinks', 'authority'):
            batch_op.drop_column(column)
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('last_backlink_refresh_at')
        batch_op.drop_column('backlink_schedule')
```

- [ ] **Step 5: Project API**

In `app/api/projects.py`:
- Add `backlink_schedule: Optional[Literal["weekly"]] = None` to `ProjectUpdate`.
- In `update_project`, add `if "backlink_schedule" in fields: project.backlink_schedule = fields["backlink_schedule"]`.
- In `_project_json`, add:

```python
        "backlink_schedule": project.backlink_schedule,
        "last_backlink_refresh_at": as_utc(project.last_backlink_refresh_at).isoformat() if project.last_backlink_refresh_at else None,
```

- [ ] **Step 6: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_backlinks_storage.py tests/test_db_schema.py tests/test_projects_api.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/db/models.py apps/backend/alembic/versions/0009_backlinks.py apps/backend/app/api/projects.py apps/backend/tests/test_backlinks_storage.py apps/backend/tests/test_db_schema.py
git commit -m "feat(backlinks): snapshot columns, ref-domain and link tables (migration 0009), opt-in schedule"
```

---

### Task 3: Snapshot refresh and the weekly job

**Files:**
- Create: `apps/backend/app/backlinks/snapshot.py`, `apps/backend/tests/test_backlinks_snapshot.py`
- Modify: `apps/backend/app/scheduler/jobs.py`

**Interfaces:**
- Produces:
  - `refresh_project(project_id, provider, today=None, factory=None) -> dict` (status `refreshed` / `capped` / `error`)
  - `jobs.run_due_backlink_refreshes(now=None, provider=None) -> List[int]`

- [ ] **Step 1: Write the failing test**

```python
"""Backlink snapshots: what's stored, history once, failures write nothing,
and the opt-in weekly job."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.backlinks.provider import DryRunBacklinks
from app.backlinks.snapshot import refresh_project
from app.db.engine import get_session_factory
from app.db.models import BacklinkLink, BacklinkRefDomain, BacklinkSnapshot, Project
from app.providers.serp import ProviderError, ProviderSkipped
from app.scheduler import jobs


def _project(domain="shop.com", schedule=None, last=None):
    with get_session_factory().begin() as s:
        p = Project(name=domain, domain=domain, backlink_schedule=schedule, last_backlink_refresh_at=last)
        s.add(p); s.flush()
        return p.id


def _count(model, **where):
    with get_session_factory()() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return s.scalar(q)


class Recording(DryRunBacklinks):
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def summary(self, target):
        self.calls.append(("summary", target))
        if self.fail:
            raise self.fail
        return super().summary(target)

    def backlinks(self, target, kind, since, limit=100):
        self.calls.append(("backlinks", kind, since))
        return super().backlinks(target, kind, since, limit)

    def history(self, target, months=12, today=None):
        self.calls.append(("history", months))
        return super().history(target, months, today=date(2026, 10, 30))


def test_first_refresh_stores_everything_and_history_once():
    pid = _project()
    provider = Recording()
    result = refresh_project(pid, provider, today=date(2026, 10, 30))
    assert result["status"] == "refreshed" and result["dry_run"] is True and result["history_months"] == 12
    assert ("history", 12) in provider.calls
    assert ("backlinks", "new", date(2026, 9, 30)) in provider.calls
    assert _count(BacklinkSnapshot, source="snapshot") == 1 and _count(BacklinkSnapshot, source="history") == 12
    assert _count(BacklinkRefDomain) == 30 and _count(BacklinkLink, kind="broken") == 10
    with get_session_factory()() as s:
        snap = s.scalar(select(BacklinkSnapshot).where(BacklinkSnapshot.source == "snapshot"))
        assert snap.dry_run is True and snap.authority is not None and snap.referring_domains > 0
        assert s.get(Project, pid).last_backlink_refresh_at is not None

    second = Recording()
    assert refresh_project(pid, second, today=date(2026, 11, 6))["history_months"] == 0
    assert not any(c[0] == "history" for c in second.calls)
    assert _count(BacklinkSnapshot, source="snapshot") == 2 and _count(BacklinkSnapshot, source="history") == 12


def test_cap_and_errors_write_nothing():
    pid = _project()
    capped = refresh_project(pid, Recording(fail=ProviderSkipped("daily cap of 20 dataforseo_backlinks calls reached")))
    assert capped == {"status": "capped", "message": "daily cap of 20 dataforseo_backlinks calls reached", "dry_run": True}
    errored = refresh_project(pid, Recording(fail=ProviderError("DataForSEO 40104: subscription needed")))
    assert errored["status"] == "error" and "40104" in errored["message"]
    assert _count(BacklinkSnapshot) == 0


class Live(Recording):
    dry_run = False


def test_weekly_job_is_opt_in_and_never_dry_run():
    now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    due = _project("due.com", schedule="weekly")
    _project("fresh.com", schedule="weekly", last=now - timedelta(days=2))
    _project("off.com", schedule=None)
    assert jobs.run_due_backlink_refreshes(now=now, provider=Recording()) == []      # dry run: never scheduled
    assert jobs.run_due_backlink_refreshes(now=now, provider=Live()) == [due]
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_backlinks_snapshot.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.backlinks.snapshot'`

- [ ] **Step 3: `app/backlinks/snapshot.py`**

```python
"""One backlink snapshot for a project: every call first, then one write."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import insert, select

from app.db.engine import get_session_factory
from app.db.models import BacklinkLink, BacklinkRefDomain, BacklinkSnapshot, Project, utcnow
from app.providers.serp import ProviderError, ProviderSkipped

WINDOW_DAYS = 30
TOP = 100
HISTORY_MONTHS = 12


def refresh_project(project_id: int, provider, today: Optional[date] = None, factory=None) -> Dict[str, Any]:
    factory = factory or get_session_factory()
    today = today or utcnow().date()
    with factory() as session:
        domain = session.get(Project, project_id).domain
        first = session.scalar(select(BacklinkSnapshot.id).where(
            BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "snapshot").limit(1)) is None
        known = set(session.scalars(select(BacklinkSnapshot.period).where(
            BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "history")))
    since = today - timedelta(days=WINDOW_DAYS)
    try:
        summary = provider.summary(domain)
        domains = provider.referring_domains(domain, TOP)
        links = {kind: provider.backlinks(domain, kind, since, TOP) for kind in ("new", "lost", "broken")}
        history = provider.history(domain, HISTORY_MONTHS) if first else []
    except ProviderSkipped as exc:
        return {"status": "capped", "message": str(exc), "dry_run": provider.dry_run}
    except ProviderError as exc:
        return {"status": "error", "message": str(exc), "dry_run": provider.dry_run}

    now, dry = utcnow(), provider.dry_run
    with factory.begin() as session:
        snap = BacklinkSnapshot(project_id=project_id, taken_at=now, provider=provider.name, metrics_json={},
                                source="snapshot", dry_run=dry, authority=summary.authority,
                                backlinks=summary.backlinks, referring_domains=summary.referring_domains,
                                broken_backlinks=summary.broken_backlinks)
        session.add(snap)
        session.flush()
        if domains:
            session.execute(insert(BacklinkRefDomain), [
                {"snapshot_id": snap.id, "domain": d.domain[:255], "rank": d.rank, "backlinks": d.backlinks,
                 "first_seen": (d.first_seen or None) and d.first_seen[:40]} for d in domains])
        link_rows = [{"snapshot_id": snap.id, "kind": kind, "url_from": l.url_from, "url_to": l.url_to,
                      "anchor": l.anchor, "domain_from_rank": l.domain_from_rank, "dofollow": l.dofollow,
                      "first_seen": (l.first_seen or None) and l.first_seen[:40],
                      "last_seen": (l.last_seen or None) and l.last_seen[:40], "target_status": l.target_status}
                     for kind, rows in links.items() for l in rows]
        if link_rows:
            session.execute(insert(BacklinkLink), link_rows)
        added = 0
        for point in history:
            if point.month in known:
                continue
            session.add(BacklinkSnapshot(
                project_id=project_id, provider=provider.name, metrics_json={}, source="history", dry_run=dry,
                period=point.month, taken_at=datetime(point.month.year, point.month.month, 1, tzinfo=timezone.utc),
                authority=point.authority, backlinks=point.backlinks, referring_domains=point.referring_domains))
            added += 1
        session.get(Project, project_id).last_backlink_refresh_at = now
        snapshot_id = snap.id
    return {"status": "refreshed", "snapshot_id": snapshot_id, "dry_run": dry, "history_months": added}
```

- [ ] **Step 4: The weekly job** (`app/scheduler/jobs.py`)

Add after `run_due_gsc_syncs`:

```python
def run_due_backlink_refreshes(now: Optional[datetime] = None, provider=None) -> List[int]:
    """Weekly backlink snapshots for projects that opted in. Never on a dry-run
    provider: made-up history must not pile up on a schedule."""
    from app.backlinks.provider import get_backlink_provider
    from app.backlinks.snapshot import refresh_project

    provider = provider if provider is not None else get_backlink_provider()
    if provider.dry_run:
        logger.warning("Scheduled backlink refreshes skipped: DataForSEO is not live")
        return []
    now = now or utcnow()
    factory = get_session_factory()
    with factory() as session:
        due = [(p.id, p.last_backlink_refresh_at) for p in session.scalars(
            select(Project).where(Project.backlink_schedule == "weekly")).all()
            if p.last_backlink_refresh_at is None or now - as_utc(p.last_backlink_refresh_at) >= timedelta(days=7)]
    refreshed: List[int] = []
    for project_id, previous in due:
        with factory() as session:
            if not claim(session, project_id, previous, now, column=Project.last_backlink_refresh_at):
                continue
        try:
            result = refresh_project(project_id, provider, today=now.date())
            if result["status"] == "refreshed":
                refreshed.append(project_id)
            else:
                logger.warning("Backlink refresh of project %s: %s %s", project_id, result["status"],
                               result.get("message", ""))
        except Exception as exc:
            logger.error("Backlink refresh of project %s failed: %s", project_id, exc, exc_info=exc)
    return refreshed
```

In `start_scheduler`, add `scheduler.add_job(run_due_backlink_refreshes, "interval", hours=6, id="run_due_backlink_refreshes", max_instances=1, coalesce=True)`.

- [ ] **Step 5: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_backlinks_snapshot.py tests/test_scheduler.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/backlinks/snapshot.py apps/backend/app/scheduler/jobs.py apps/backend/tests/test_backlinks_snapshot.py
git commit -m "feat(backlinks): snapshot refresh (history on first run) and opt-in weekly job"
```

---

### Task 4: Link gap and broken backlinks in audits

**Files:**
- Create: `apps/backend/app/backlinks/gap.py`, `apps/backend/app/backlinks/audit.py`, `apps/backend/tests/test_backlinks_gap_audit.py`
- Modify: `apps/backend/app/services/audit_service.py`, `apps/backend/app/ai/ai_suggestions.py`

**Interfaces:**
- Produces:
  - `GapError(ValueError)`
  - `link_gap(project_id, competitors, provider, factory=None) -> dict`
  - `broken_backlink_targets(domain, factory=None) -> Dict[str, Tuple[int, int]]`
  - `backlink_issues(targets, results) -> Dict[str, List[issue]]`

- [ ] **Step 1: Write the failing test**

```python
"""Competitor link gap, and broken backlinks raised on the audit."""

from datetime import datetime, timezone
from types import SimpleNamespace as Page

import pytest

from app.backlinks.audit import backlink_issues, broken_backlink_targets
from app.backlinks.gap import GapError, link_gap
from app.backlinks.provider import DryRunBacklinks, GapDomain
from app.db.engine import get_session_factory
from app.db.models import BacklinkLink, BacklinkSnapshot, Competitor, Project
from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler


def _project(domain="shop.com", competitors=()):
    with get_session_factory().begin() as s:
        p = Project(name=domain, domain=domain); s.add(p); s.flush()
        for c in competitors:
            s.add(Competitor(project_id=p.id, domain=c))
        return p.id


class Gap(DryRunBacklinks):
    def __init__(self):
        self.args = None

    def intersection(self, competitors, exclude, limit=100):
        self.args = (competitors, exclude, limit)
        return [GapDomain("one.com", 900, {"rival.com": 2}), GapDomain("both.com", 300, {"rival.com": 1, "other.com": 4}),
                GapDomain("both-strong.com", 700, {"rival.com": 1, "other.com": 1})]


def test_gap_defaults_to_project_competitors_and_sorts():
    pid = _project(competitors=["rival.com", "other.com"])
    provider = Gap()
    result = link_gap(pid, None, provider)
    assert provider.args == (["rival.com", "other.com"], "shop.com", 100)
    assert [r["domain"] for r in result["rows"]] == ["both-strong.com", "both.com", "one.com"]
    assert result["rows"][1] == {"domain": "both.com", "rank": 300, "linked_count": 2,
                                 "backlinks_by_competitor": {"rival.com": 1, "other.com": 4}}
    assert result["dry_run"] is True and result["my_domain"] == "shop.com"


def test_gap_needs_one_to_five_competitors():
    pid = _project()
    with pytest.raises(GapError):
        link_gap(pid, None, Gap())
    with pytest.raises(GapError):
        link_gap(pid, [f"c{i}.com" for i in range(6)], Gap())
    assert link_gap(pid, ["Rival.com ", "shop.com"], Gap())["competitors"] == ["rival.com"]   # own domain dropped


def _snapshot_with_broken(domain, targets):
    pid = _project(domain)
    with get_session_factory().begin() as s:
        snap = BacklinkSnapshot(project_id=pid, taken_at=datetime(2026, 10, 30, tzinfo=timezone.utc), provider="x",
                                metrics_json={}, source="snapshot")
        s.add(snap); s.flush()
        for url_from, url_to in targets:
            s.add(BacklinkLink(snapshot_id=snap.id, kind="broken", url_from=url_from, url_to=url_to, anchor="",
                               dofollow=True, target_status=404))
    return pid


def test_broken_targets_and_issues():
    _snapshot_with_broken("example.com", [("https://a.net/1", "https://example.com/old"),
                                          ("https://a.net/2", "https://example.com/old"),
                                          ("https://b.org/x", "https://EXAMPLE.com/old"),
                                          ("https://c.io/y", "https://example.com/gone")])
    targets = broken_backlink_targets("example.com")
    assert targets["https://example.com/old"] == (3, 2)
    results = {"https://example.com/old": Page(status_code=404), "https://example.com/gone": Page(status_code=200)}
    issues = backlink_issues(targets, results)
    assert list(issues) == ["https://example.com/old"]
    assert issues["https://example.com/old"] == [{
        "severity": "warning", "code": "BACKLINK_TO_BROKEN_PAGE",
        "message": "3 backlinks from 2 domains point to this broken page. Redirect it to keep their value."}]
    assert broken_backlink_targets("nosnapshot.com") == {}


def test_audit_flags_a_broken_page_with_backlinks():
    _snapshot_with_broken("example.com", [("https://a.net/1", "https://example.com/missing")])
    crawler = FakeCrawler()
    page = next(iter(crawler.results.values()))
    from app.crawler.crawler import PageResult
    crawler.results["https://example.com/missing"] = PageResult(url="https://example.com/missing",
                                                                final_url="https://example.com/missing",
                                                                status_code=404, html="", headers={}, depth=1)
    result = audit_service._build_audit_result("https://example.com/", crawler, progress_callback=None, event_callback=None)
    codes = [i["code"] for i in result["page_issues_detail"]["https://example.com/missing"]]
    assert "BACKLINK_TO_BROKEN_PAGE" in codes
```

If `FakeCrawler.crawl` only hands over the pages present when it was built, the
added 404 page must be in `results` before `crawl()` runs. It is here, because
`_build_audit_result` calls `crawl()` itself. If the page isn't analysed, check
how `FakeCrawler.crawl` iterates and add it the same way the fake does.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_backlinks_gap_audit.py -q`
Expected: FAIL (modules missing).

- [ ] **Step 3: `app/backlinks/gap.py`**

```python
"""Competitor link gap: domains that link to competitors but not to you."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import Competitor, Project

MAX_COMPETITORS = 5


class GapError(ValueError):
    pass


def link_gap(project_id: int, competitors: Optional[List[str]], provider, factory=None) -> Dict[str, Any]:
    """ProviderSkipped / ProviderError propagate to the caller."""
    factory = factory or get_session_factory()
    with factory() as session:
        project = session.get(Project, project_id)
        mine = project.domain
        if competitors is None:
            competitors = list(session.scalars(select(Competitor.domain).where(
                Competitor.project_id == project_id).order_by(Competitor.id)))
    chosen: List[str] = []
    for c in competitors:
        domain = (c or "").strip().lower()
        if domain and domain != mine and domain not in chosen:
            chosen.append(domain)
    if not 1 <= len(chosen) <= MAX_COMPETITORS:
        raise GapError(f"pick 1 to {MAX_COMPETITORS} competitors")
    rows = [{"domain": r.domain, "rank": r.rank, "linked_count": len(r.linked_competitors),
             "backlinks_by_competitor": dict(r.linked_competitors)}
            for r in provider.intersection(chosen, mine, 100)]
    rows.sort(key=lambda r: (-r["linked_count"], -(r["rank"] or 0), r["domain"]))
    return {"my_domain": mine, "competitors": chosen, "dry_run": provider.dry_run, "rows": rows[:100]}
```

- [ ] **Step 4: `app/backlinks/audit.py`**

```python
"""Broken backlinks on the audit: a page that errors but still has links pointing at it."""

from __future__ import annotations

import urllib.parse as up
from typing import Any, Dict, List, Tuple

from sqlalchemy import desc, select

from app.auditor.checks import issue
from app.crawler.crawler import normalize_url
from app.db.engine import get_session_factory
from app.db.models import BacklinkLink, BacklinkSnapshot, Project


def broken_backlink_targets(domain: str, factory=None) -> Dict[str, Tuple[int, int]]:
    """normalised target URL -> (backlinks, distinct linking domains), from the
    project's latest snapshot. No snapshot, no targets."""
    factory = factory or get_session_factory()
    with factory() as session:
        snap_id = session.scalar(
            select(BacklinkSnapshot.id).join(Project, Project.id == BacklinkSnapshot.project_id)
            .where(Project.domain == domain, BacklinkSnapshot.source == "snapshot")
            .order_by(desc(BacklinkSnapshot.taken_at), desc(BacklinkSnapshot.id)).limit(1))
        if snap_id is None:
            return {}
        links = session.execute(select(BacklinkLink.url_from, BacklinkLink.url_to).where(
            BacklinkLink.snapshot_id == snap_id, BacklinkLink.kind == "broken")).all()
    counts: Dict[str, List[Any]] = {}
    for url_from, url_to in links:
        entry = counts.setdefault(normalize_url(url_to), [0, set()])
        entry[0] += 1
        entry[1].add((up.urlsplit(url_from).hostname or "").lower())
    return {url: (n, len(domains)) for url, (n, domains) in counts.items()}


def backlink_issues(targets: Dict[str, Tuple[int, int]], results: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    out: Dict[str, List[Dict[str, str]]] = {}
    if not targets:
        return out
    for url, page in results.items():
        status = getattr(page, "status_code", None)
        match = targets.get(normalize_url(url))
        if status is not None and status >= 400 and match:
            n, d = match
            out[url] = [issue("warning", "BACKLINK_TO_BROKEN_PAGE",
                              f"{n} backlink{'' if n == 1 else 's'} from {d} domain{'' if d == 1 else 's'} point to "
                              f"this broken page. Redirect it to keep their value.")]
    return out
```

- [ ] **Step 5: Pipeline, issue weights**

`app/services/audit_service.py`:
- Import `from app.backlinks.audit import backlink_issues, broken_backlink_targets` and `from app.db.projects import project_domain`.
- After the Search Console block, add:

```python
    # Broken pages that still have backlinks, from the project's latest backlink
    # snapshot -- no API call here, and nothing without a snapshot.
    try:
        for page_url, found in backlink_issues(broken_backlink_targets(project_domain(url)), crawler.results).items():
            all_page_issues.setdefault(page_url, []).extend(found)
            db.add_issues(page_url, found)
    except Exception as exc:
        logger.error("Broken-backlink check failed: %s", exc, exc_info=exc)
```

`app/ai/ai_suggestions.py`:
- Add `"BACKLINK_TO_BROKEN_PAGE": 8,` to `IMPACT_WEIGHTS`.
- Add this to `RECOMMENDATION_TEXT`: `"BACKLINK_TO_BROKEN_PAGE": "301-redirect this URL to the most relevant live page so the links pointing at it keep passing value."`

- [ ] **Step 6: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_backlinks_gap_audit.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app apps/backend/tests/test_backlinks_gap_audit.py
git commit -m "feat(backlinks): competitor link gap; BACKLINK_TO_BROKEN_PAGE on audits from the latest snapshot"
```

---

### Task 5: Backlinks API

**Files:**
- Create: `apps/backend/app/api/backlinks.py`, `apps/backend/tests/test_backlinks_api.py`
- Modify: `apps/backend/app/main.py`

**Interfaces:**
- Produces, under `/api/projects/{id}/backlinks`:
  - `GET ""`
  - `GET "/referring-domains"`
  - `GET "/links?kind="`
  - `POST "/refresh"`
  - `POST "/gap"`

- [ ] **Step 1: Write the failing test**

```python
"""Backlinks over HTTP."""

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.backlinks.snapshot import refresh_project
from app.backlinks.provider import DryRunBacklinks
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditPage, BacklinkSnapshot, Competitor, Project
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _project():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com"); s.add(p); s.flush()
        s.add_all([Competitor(project_id=p.id, domain="rival.com"), Competitor(project_id=p.id, domain="other.com")])
        return p.id


def test_empty_then_refreshed_overview(client):
    pid = _project()
    empty = client.get(f"/api/projects/{pid}/backlinks").json()
    assert empty["latest"] is None and empty["history"] == [] and empty["dry_run_provider"] is True
    assert client.post(f"/api/projects/{pid}/backlinks/refresh").json()["status"] == "refreshed"
    refresh_project(pid, DryRunBacklinks(), today=date(2026, 11, 6))
    body = client.get(f"/api/projects/{pid}/backlinks").json()
    assert body["latest"]["dry_run"] is True and body["previous"] is not None
    assert {"taken_at", "authority", "backlinks", "referring_domains", "broken_backlinks"} <= set(body["latest"])
    sources = [h["source"] for h in body["history"]]
    assert sources.count("history") == 12 and sources.count("snapshot") == 2
    assert [h["date"] for h in body["history"]] == sorted(h["date"] for h in body["history"])


def test_lists_and_crawled_status(client):
    pid = _project()
    client.post(f"/api/projects/{pid}/backlinks/refresh")
    domains = client.get(f"/api/projects/{pid}/backlinks/referring-domains?limit=5").json()
    assert domains["total"] == 30 and len(domains["items"]) == 5
    assert domains["items"][0]["rank"] >= domains["items"][1]["rank"]
    t = datetime(2026, 10, 30, tzinfo=timezone.utc)
    with get_session_factory().begin() as s:
        audit = Audit(project_id=pid, session_id="s1", start_url="https://shop.com/", status="completed",
                      trigger="manual", started_at=t, finished_at=t)
        s.add(audit); s.flush()
        s.add(AuditPage(audit_id=audit.id, url="https://shop.com/old-page-0", status=404))
    broken = client.get(f"/api/projects/{pid}/backlinks/links?kind=broken").json()
    assert broken["total"] == 10
    first = [i for i in broken["items"] if i["url_to"] == "https://shop.com/old-page-0"][0]
    assert first["crawled_status"] == 404
    assert client.get(f"/api/projects/{pid}/backlinks/links?kind=bogus").status_code == 422


def test_gap(client):
    pid = _project()
    body = client.post(f"/api/projects/{pid}/backlinks/gap", json={}).json()
    assert body["competitors"] == ["rival.com", "other.com"] and body["rows"] and body["dry_run"] is True
    assert client.post(f"/api/projects/{pid}/backlinks/gap", json={"competitors": []}).status_code == 400


def test_404s(client):
    assert client.get("/api/projects/999/backlinks").status_code == 404
    assert client.post("/api/projects/999/backlinks/refresh").status_code == 404
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_backlinks_api.py -q`
Expected: FAIL (404s).

- [ ] **Step 3: `app/api/backlinks.py`**

```python
"""Backlinks (Phase 6): profile, growth, lists, refresh, and the link gap."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import desc, func, select

from app.api.projects import _factory
from app.backlinks.gap import GapError, link_gap
from app.backlinks.provider import get_backlink_provider
from app.backlinks.snapshot import refresh_project
from app.crawler.crawler import normalize_url
from app.db.models import Audit, AuditPage, BacklinkLink, BacklinkRefDomain, BacklinkSnapshot, Project, as_utc
from app.providers.serp import ProviderError, ProviderSkipped

router = APIRouter()


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _totals(s: BacklinkSnapshot) -> Dict[str, Any]:
    return {"taken_at": as_utc(s.taken_at).isoformat(), "authority": s.authority, "backlinks": s.backlinks,
            "referring_domains": s.referring_domains, "broken_backlinks": s.broken_backlinks, "dry_run": s.dry_run}


def _latest_snapshot_id(session, project_id: int) -> Optional[int]:
    return session.scalar(select(BacklinkSnapshot.id).where(
        BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "snapshot")
        .order_by(desc(BacklinkSnapshot.taken_at), desc(BacklinkSnapshot.id)).limit(1))


@router.get("/projects/{project_id}/backlinks")
def overview(project_id: int):
    provider = get_backlink_provider()
    with _factory()() as session:
        project = _project(session, project_id)
        snaps = session.scalars(select(BacklinkSnapshot).where(
            BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "snapshot")
            .order_by(desc(BacklinkSnapshot.taken_at), desc(BacklinkSnapshot.id)).limit(2)).all()
        rows = session.scalars(select(BacklinkSnapshot).where(BacklinkSnapshot.project_id == project_id)).all()
        history = sorted(({"date": (r.period or as_utc(r.taken_at).date()).isoformat(), "authority": r.authority,
                           "backlinks": r.backlinks, "referring_domains": r.referring_domains,
                           "source": r.source} for r in rows), key=lambda h: (h["date"], h["source"] != "history"))
        return {"dry_run_provider": provider.dry_run, "schedule": project.backlink_schedule,
                "last_refresh_at": as_utc(project.last_backlink_refresh_at).isoformat() if project.last_backlink_refresh_at else None,
                "latest": _totals(snaps[0]) if snaps else None,
                "previous": _totals(snaps[1]) if len(snaps) > 1 else None,
                "history": history}


@router.get("/projects/{project_id}/backlinks/referring-domains")
def referring_domains(project_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    with _factory()() as session:
        _project(session, project_id)
        snap_id = _latest_snapshot_id(session, project_id)
        if snap_id is None:
            return {"total": 0, "items": []}
        where = BacklinkRefDomain.snapshot_id == snap_id
        total = session.scalar(select(func.count()).select_from(BacklinkRefDomain).where(where))
        items = session.scalars(select(BacklinkRefDomain).where(where)
                                .order_by(desc(BacklinkRefDomain.rank), BacklinkRefDomain.id).offset(offset).limit(limit)).all()
        return {"total": total, "items": [{"domain": d.domain, "rank": d.rank, "backlinks": d.backlinks,
                                           "first_seen": d.first_seen} for d in items]}


@router.get("/projects/{project_id}/backlinks/links")
def links(project_id: int, kind: Literal["new", "lost", "broken"], limit: int = Query(50, ge=1, le=200),
          offset: int = Query(0, ge=0)):
    with _factory()() as session:
        _project(session, project_id)
        snap_id = _latest_snapshot_id(session, project_id)
        if snap_id is None:
            return {"total": 0, "items": []}
        where = (BacklinkLink.snapshot_id == snap_id) & (BacklinkLink.kind == kind)
        total = session.scalar(select(func.count()).select_from(BacklinkLink).where(where))
        rows = session.scalars(select(BacklinkLink).where(where)
                               .order_by(desc(BacklinkLink.domain_from_rank), BacklinkLink.id).offset(offset).limit(limit)).all()
        crawled: Dict[str, int] = {}
        if kind == "broken":
            audit_id = session.scalar(select(Audit.id).where(Audit.project_id == project_id)
                                      .order_by(desc(Audit.finished_at), desc(Audit.id)).limit(1))
            if audit_id is not None:
                crawled = {normalize_url(u): s for u, s in session.execute(
                    select(AuditPage.url, AuditPage.status).where(AuditPage.audit_id == audit_id)) if s is not None}
        items: List[Dict[str, Any]] = []
        for l in rows:
            item = {"url_from": l.url_from, "url_to": l.url_to, "anchor": l.anchor, "domain_from_rank": l.domain_from_rank,
                    "dofollow": l.dofollow, "first_seen": l.first_seen, "last_seen": l.last_seen,
                    "target_status": l.target_status}
            if kind == "broken":
                item["crawled_status"] = crawled.get(normalize_url(l.url_to))
            items.append(item)
        return {"total": total, "items": items}


@router.post("/projects/{project_id}/backlinks/refresh")
def refresh(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
    return refresh_project(project_id, get_backlink_provider())


@router.post("/projects/{project_id}/backlinks/gap")
def gap(project_id: int, body: Dict[str, Any] = Body(default={})):
    with _factory()() as session:
        _project(session, project_id)
    competitors = body.get("competitors") if isinstance(body, dict) else None
    try:
        return link_gap(project_id, competitors, get_backlink_provider())
    except GapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProviderSkipped as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
```

In `app/main.py`, after the gsc router lines:

```python
from app.api.backlinks import router as backlinks_router  # noqa: E402
app.include_router(backlinks_router, prefix="/api")
```

- [ ] **Step 4: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_backlinks_api.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/api/backlinks.py apps/backend/app/main.py apps/backend/tests/test_backlinks_api.py
git commit -m "feat(backlinks): API (overview + growth, referring domains, links, refresh, link gap)"
```

---

### Task 6: Frontend

**Files:**
- Modify:
  - `packages/shared/src/types/platform.ts`
  - `apps/frontend/services/platform.ts`
  - `components/platform/project-tabs.tsx`
- Create:
  - `apps/frontend/components/platform/metric-trend-chart.tsx`
  - `apps/frontend/components/platform/link-gap.tsx`
  - `apps/frontend/components/platform/backlink-tables.tsx`
  - `apps/frontend/app/projects/[id]/backlinks/page.tsx`
  - `components/__tests__/backlinks-page.test.tsx`

**Interfaces:**
- Produces:
  - Types `BacklinkTotals, BacklinkOverview, RefDomainRow, BacklinkRow, BacklinkRefresh, LinkGapRow, LinkGapResult`
  - `Platform.backlinksOverview(id)`, `refDomains(id, offset)`, `backlinkLinks(id, kind, offset)`, `refreshBacklinks(id)`, `backlinkGap(id, competitors?)`
  - `updateProject` accepts `backlink_schedule`

- [ ] **Step 1: Types and service**

Append to `packages/shared/src/types/platform.ts`:

```ts
// Backlinks (backend Phase 6, DataForSEO).
export interface BacklinkTotals { taken_at: string; authority: number | null; backlinks: number; referring_domains: number; broken_backlinks: number; dry_run: boolean }
export interface BacklinkOverview {
  dry_run_provider: boolean; schedule: "weekly" | null; last_refresh_at: string | null;
  latest: BacklinkTotals | null; previous: BacklinkTotals | null;
  history: { date: string; authority: number | null; backlinks: number; referring_domains: number; source: "snapshot" | "history" }[];
}
export interface RefDomainRow { domain: string; rank: number | null; backlinks: number; first_seen: string | null }
export interface BacklinkRow {
  url_from: string; url_to: string; anchor: string; domain_from_rank: number | null; dofollow: boolean;
  first_seen: string | null; last_seen: string | null; target_status: number | null; crawled_status?: number | null;
}
export type BacklinkKind = "new" | "lost" | "broken";
export interface BacklinkRefresh { status: "refreshed" | "capped" | "error"; snapshot_id?: number; dry_run: boolean; history_months?: number; message?: string }
export interface LinkGapRow { domain: string; rank: number | null; linked_count: number; backlinks_by_competitor: Record<string, number> }
export interface LinkGapResult { my_domain: string; competitors: string[]; dry_run: boolean; rows: LinkGapRow[] }
```

In `ProjectSummary`, add `backlink_schedule?: "weekly" | null; last_backlink_refresh_at?: string | null;`.

In `services/platform.ts`:
- Import the new types.
- Widen `updateProject`'s body with `backlink_schedule: "weekly" | null`.
- Add:

```ts
  backlinksOverview: (id: number) => request<BacklinkOverview>(`/projects/${id}/backlinks`),
  refDomains: (id: number, offset = 0) => request<{ total: number; items: RefDomainRow[] }>(`/projects/${id}/backlinks/referring-domains?limit=50&offset=${offset}`),
  backlinkLinks: (id: number, kind: BacklinkKind, offset = 0) => request<{ total: number; items: BacklinkRow[] }>(`/projects/${id}/backlinks/links?kind=${kind}&limit=50&offset=${offset}`),
  refreshBacklinks: (id: number) => request<BacklinkRefresh>(`/projects/${id}/backlinks/refresh`, post()),
  backlinkGap: (id: number, competitors?: string[]) => request<LinkGapResult>(`/projects/${id}/backlinks/gap`, post(competitors ? { competitors } : {})),
```

Rebuild shared: `cd packages/shared && npx tsc`.

- [ ] **Step 2: Write the failing test** (`components/__tests__/backlinks-page.test.tsx`)

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import BacklinksPage from "@/app/projects/[id]/backlinks/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/backlinks" }));

const totals = (over: object = {}) => ({ taken_at: "2026-10-30T10:00:00+00:00", authority: 412, backlinks: 18230,
  referring_domains: 640, broken_backlinks: 3, dry_run: false, ...over });
const overview = (over: object = {}) => ({
  dry_run_provider: false, schedule: null, last_refresh_at: "2026-10-30T10:00:00+00:00",
  latest: totals(), previous: totals({ authority: 400, referring_domains: 600, backlinks: 18000, broken_backlinks: 5 }),
  history: [{ date: "2026-09-01", authority: 400, backlinks: 18000, referring_domains: 600, source: "history" },
            { date: "2026-10-30", authority: 412, backlinks: 18230, referring_domains: 640, source: "snapshot" }],
  ...over,
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "refDomains").mockResolvedValue({ total: 1, items: [{ domain: "news.com", rank: 700, backlinks: 12, first_seen: null }] });
  vi.spyOn(Platform, "backlinkLinks").mockResolvedValue({ total: 1, items: [{ url_from: "https://blog.net/p", url_to: "https://shop.com/old",
    anchor: "shop", domain_from_rank: 600, dofollow: true, first_seen: null, last_seen: null, target_status: 404, crawled_status: 404 }] });
  vi.spyOn(Platform, "listCompetitors").mockResolvedValue({ items: [{ id: 1, domain: "rival.com" }, { id: 2, domain: "other.com" }] } as any);
});

describe("Backlinks tab", () => {
  it("shows an empty state before the first refresh", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview({ latest: null, previous: null, history: [] }) as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    expect(await screen.findByText(/No backlink data yet/)).toBeInTheDocument();
  });

  it("labels authority as DataForSEO's and shows changes (broken: lower is better)", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    expect(await screen.findByText("412")).toBeInTheDocument();
    expect(screen.getByText(/DataForSEO rank, 0–1000/)).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 40")).toBeInTheDocument();     // referring domains 600 -> 640
    expect(screen.getByLabelText("improved by 2")).toBeInTheDocument();      // broken 5 -> 3
    expect(await screen.findByText("news.com")).toBeInTheDocument();
    expect((await screen.findAllByText(/Redirect this URL/)).length).toBeGreaterThan(0);
  });

  it("shows the preview banner on dry run", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview({ dry_run_provider: true }) as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    expect((await screen.findAllByRole("note")).length).toBeGreaterThan(0);
  });

  it("toggles the weekly refresh and refreshes on demand", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    const update = vi.spyOn(Platform, "updateProject").mockResolvedValue({} as any);
    const refresh = vi.spyOn(Platform, "refreshBacklinks").mockResolvedValue({ status: "capped", dry_run: false,
      message: "daily cap of 20 dataforseo_backlinks calls reached" });
    render(<BacklinksPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("switch", { name: /weekly refresh/i }));
    expect(update).toHaveBeenCalledWith(7, { backlink_schedule: "weekly" });
    await userEvent.click(screen.getByRole("button", { name: /refresh now/i }));
    expect(refresh).toHaveBeenCalledWith(7);
    expect(await screen.findByText(/daily cap of 20/)).toBeInTheDocument();
  });

  it("charts have a table view that marks history rows", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    render(<BacklinksPage params={{ id: "7" }} />);
    await userEvent.click((await screen.findAllByRole("button", { name: /show as table/i }))[0]);
    expect(screen.getByText(/from DataForSEO history/)).toBeInTheDocument();
  });

  it("runs the link gap with the chosen competitors", async () => {
    vi.spyOn(Platform, "backlinksOverview").mockResolvedValue(overview() as any);
    const gap = vi.spyOn(Platform, "backlinkGap").mockResolvedValue({ my_domain: "shop.com", competitors: ["rival.com", "other.com"],
      dry_run: false, rows: [{ domain: "both.com", rank: 700, linked_count: 2, backlinks_by_competitor: { "rival.com": 1, "other.com": 4 } }] });
    render(<BacklinksPage params={{ id: "7" }} />);
    expect(await screen.findByLabelText("rival.com")).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /run link gap/i }));
    await waitFor(() => expect(gap).toHaveBeenCalledWith(7, ["rival.com", "other.com"]));
    expect(await screen.findByText("both.com")).toBeInTheDocument();
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run and watch it fail**

Run: `cd apps/frontend && npx vitest run components/__tests__/backlinks-page.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Components**

`components/platform/metric-trend-chart.tsx` (one measure per chart):

```tsx
"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { SERIES_LIGHT } from "@/lib/platform-charts";

export interface TrendPoint { label: string; value: number | null; note?: string }

export function MetricTrendChart({ title, data }: { title: string; data: TrendPoint[] }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        <button type="button" onClick={() => setAsTable((v) => !v)} className="rounded-full border px-3 py-1 text-xs active:scale-95">
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-[13px]">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Date</th><th className="py-1">{title}</th><th className="py-1" /></tr></thead>
            <tbody>{data.map((d, i) => (
              <tr key={`${d.label}-${i}`}><td className="py-1">{d.label}</td><td className="py-1 tabular-nums">{d.value ?? "—"}</td>
                <td className="py-1 text-xs text-muted-foreground">{d.note ?? ""}</td></tr>))}</tbody>
          </table>
        </div>
      ) : (
        <div className="h-48 w-full" role="img" aria-label={`${title} over time`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Line type="monotone" dataKey="value" name={title} stroke={SERIES_LIGHT[0]} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
```

`components/platform/backlink-tables.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { BacklinkKind } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

function Pager({ offset, total, onChange }: { offset: number; total: number; onChange: (o: number) => void }) {
  if (total <= 50) return null;
  return (
    <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
      <button type="button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - 50))} className="rounded-full border px-3 py-1 disabled:opacity-50">Previous</button>
      <span>{offset + 1}–{Math.min(offset + 50, total)} of {total}</span>
      <button type="button" disabled={offset + 50 >= total} onClick={() => onChange(offset + 50)} className="rounded-full border px-3 py-1 disabled:opacity-50">Next</button>
    </div>
  );
}

export function RefDomainsTable({ projectId }: { projectId: number }) {
  const [offset, setOffset] = useState(0);
  const state = useApi(() => Platform.refDomains(projectId, offset), [projectId, offset]);
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <h2 className="mb-3 font-semibold tracking-tight">Top referring domains</h2>
      <AsyncState state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No referring domains yet">
        {(d) => (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                  <th className="py-2 pr-4 font-medium">Domain</th><th className="py-2 pr-4 font-medium">DataForSEO rank</th>
                  <th className="py-2 pr-4 font-medium">Backlinks</th><th className="py-2 font-medium">First seen</th></tr></thead>
                <tbody className="divide-y">{d.items.map((r) => (
                  <tr key={r.domain}><td className="break-all py-2 pr-4">{r.domain}</td><td className="py-2 pr-4 tabular-nums">{r.rank ?? "—"}</td>
                    <td className="py-2 pr-4 tabular-nums">{r.backlinks}</td><td className="py-2 text-muted-foreground">{r.first_seen?.slice(0, 10) ?? "—"}</td></tr>))}</tbody>
              </table>
            </div>
            <Pager offset={offset} total={d.total} onChange={setOffset} />
          </>
        )}
      </AsyncState>
    </section>
  );
}

const TITLES: Record<BacklinkKind, string> = { new: "New links (30 days)", lost: "Lost links (30 days)", broken: "Broken backlinks" };

export function LinksTable({ projectId, kind }: { projectId: number; kind: BacklinkKind }) {
  const [offset, setOffset] = useState(0);
  const state = useApi(() => Platform.backlinkLinks(projectId, kind, offset), [projectId, kind, offset]);
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <h2 className="mb-1 font-semibold tracking-tight">{TITLES[kind]}</h2>
      {kind === "broken" && <p className="mb-3 text-xs text-muted-foreground">Links pointing at pages that error. Redirect this URL to a live page to keep their value.</p>}
      <AsyncState state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="None">
        {(d) => (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                  <th className="py-2 pr-4 font-medium">From</th><th className="py-2 pr-4 font-medium">To</th>
                  <th className="py-2 pr-4 font-medium">Anchor</th><th className="py-2 pr-4 font-medium">Rank</th>
                  <th className="py-2 font-medium">{kind === "broken" ? "Status" : "Follow"}</th></tr></thead>
                <tbody className="divide-y">{d.items.map((l, i) => (
                  <tr key={`${l.url_from}-${i}`} className="align-top">
                    <td className="max-w-[200px] break-all py-2 pr-4">{l.url_from}</td>
                    <td className="max-w-[200px] break-all py-2 pr-4">{l.url_to}{kind === "broken" && <p className="text-xs text-muted-foreground">Redirect this URL to a live page</p>}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{l.anchor || "—"}</td>
                    <td className="py-2 pr-4 tabular-nums">{l.domain_from_rank ?? "—"}</td>
                    <td className="py-2 text-muted-foreground">{kind === "broken" ? (l.crawled_status ?? l.target_status ?? "—") : (l.dofollow ? "follow" : "nofollow")}</td>
                  </tr>))}</tbody>
              </table>
            </div>
            <Pager offset={offset} total={d.total} onChange={setOffset} />
          </>
        )}
      </AsyncState>
    </section>
  );
}
```

`components/platform/link-gap.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import type { LinkGapResult } from "@seo-auditor/shared";

import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export function LinkGap({ projectId }: { projectId: number }) {
  const competitors = useApi(() => Platform.listCompetitors(projectId), [projectId]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<LinkGapResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  useEffect(() => { setChosen((competitors.data?.items ?? []).slice(0, 5).map((c) => c.domain)); }, [competitors.data]);

  const run = async () => {
    setRunning(true); setError(null);
    try { setResult(await Platform.backlinkGap(projectId, chosen)); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Link gap failed"); }
    finally { setRunning(false); }
  };

  const all = competitors.data?.items ?? [];
  return (
    <section className="min-w-0 space-y-3 rounded-[18px] border bg-card p-5">
      <h2 className="font-semibold tracking-tight">Link gap</h2>
      <p className="text-sm text-muted-foreground">Domains that link to your competitors but not to you: outreach targets.</p>
      {all.length === 0 ? <p className="text-sm text-muted-foreground">Add competitors in the Rank Tracker tab first.</p> : (
        <div className="flex flex-wrap items-center gap-3">
          {all.map((c) => (
            <label key={c.domain} className="flex items-center gap-2 rounded-full border px-3 py-1 text-sm">
              <input type="checkbox" aria-label={c.domain} checked={chosen.includes(c.domain)} disabled={!chosen.includes(c.domain) && chosen.length >= 5}
                     onChange={(e) => setChosen((cur) => e.target.checked ? [...cur, c.domain] : cur.filter((d) => d !== c.domain))} />
              {c.domain}
            </label>
          ))}
          <button type="button" onClick={run} disabled={running || chosen.length === 0} aria-label="Run link gap"
                  className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
            {running ? "Running…" : "Run"}
          </button>
          <span className="text-xs text-muted-foreground">about $0.05–0.10 per run</span>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
      {result && (
        <>
          <DryRunBanner show={result.dry_run} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-[13px]">
              <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                <th className="py-2 pr-4 font-medium">Domain</th><th className="py-2 pr-4 font-medium">DataForSEO rank</th>
                <th className="py-2 pr-4 font-medium">Links to</th><th className="py-2 font-medium">Backlinks per competitor</th></tr></thead>
              <tbody className="divide-y">{result.rows.map((r) => (
                <tr key={r.domain} className="align-top">
                  <td className="break-all py-2 pr-4">{r.domain}</td><td className="py-2 pr-4 tabular-nums">{r.rank ?? "—"}</td>
                  <td className="whitespace-nowrap py-2 pr-4">{r.linked_count} of {result.competitors.length}</td>
                  <td className="py-2 text-muted-foreground">{Object.entries(r.backlinks_by_competitor).map(([c, n]) => `${c}: ${n}`).join(", ")}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
```

`app/projects/[id]/backlinks/page.tsx`:

```tsx
"use client";

import { useState } from "react";

import { AsyncState } from "@/components/platform/async-state";
import { LinksTable, RefDomainsTable } from "@/components/platform/backlink-tables";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { KpiTile } from "@/components/platform/kpi-tile";
import { LinkGap } from "@/components/platform/link-gap";
import { MetricTrendChart } from "@/components/platform/metric-trend-chart";
import { PageHeader } from "@/components/platform/page-header";
import { change, formatCount } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function BacklinksPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const overview = useApi(() => Platform.backlinksOverview(projectId), [projectId]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    setBusy(true); setMessage(null);
    try {
      const r = await Platform.refreshBacklinks(projectId);
      setMessage(r.status === "refreshed" ? `Refreshed${r.history_months ? `, with ${r.history_months} months of history` : ""}.` : r.message ?? "Refresh failed");
      overview.reload();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.detail : "Refresh failed");
    } finally {
      setBusy(false);
    }
  };

  const toggleWeekly = async (on: boolean) => {
    await Platform.updateProject(projectId, { backlink_schedule: on ? "weekly" : null });
    overview.reload();
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Backlinks" description="Who links to this site, how that's changing, and who links to your competitors instead. Data from DataForSEO." />
      <AsyncState state={overview}>
        {(o) => {
          const l = o.latest, p = o.previous;
          const label = (d: string, source: string) => ({ label: d, note: source === "history" ? "from DataForSEO history" : undefined });
          return (
            <div className="space-y-6">
              <DryRunBanner show={o.dry_run_provider || !!l?.dry_run} message="Preview data. DataForSEO is not live, so these backlink numbers are made up." />
              <section className="flex flex-wrap items-center gap-4 rounded-[18px] border bg-card p-5 text-sm">
                <button type="button" onClick={refresh} disabled={busy} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
                  {busy ? "Refreshing…" : "Refresh now"}
                </button>
                <span className="text-xs text-muted-foreground">about $0.25 per refresh · last: {o.last_refresh_at ? new Date(o.last_refresh_at).toLocaleString() : "never"}</span>
                <label className="ml-auto flex items-center gap-2">
                  <button type="button" role="switch" aria-checked={o.schedule === "weekly"} aria-label="Weekly refresh" onClick={() => toggleWeekly(o.schedule !== "weekly")}
                          className={`relative h-6 w-11 rounded-full transition-colors ${o.schedule === "weekly" ? "bg-primary" : "bg-muted"}`}>
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-background transition-all ${o.schedule === "weekly" ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                  Weekly refresh
                </label>
                {message && <p className="w-full text-muted-foreground">{message}</p>}
              </section>
              {!l ? (
                <p className="rounded-[18px] border bg-card p-5 text-sm text-muted-foreground">No backlink data yet. Press <strong>Refresh now</strong>.</p>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <KpiTile label="Authority" value={l.authority ?? "—"} hint="DataForSEO rank, 0–1000" delta={<DeltaBadge value={change(l.authority, p?.authority)} />} />
                    <KpiTile label="Referring domains" value={formatCount(l.referring_domains)} delta={<DeltaBadge value={change(l.referring_domains, p?.referring_domains)} />} />
                    <KpiTile label="Backlinks" value={formatCount(l.backlinks)} delta={<DeltaBadge value={change(l.backlinks, p?.backlinks)} />} />
                    <KpiTile label="Broken backlinks" value={formatCount(l.broken_backlinks)} delta={<DeltaBadge value={change(l.broken_backlinks, p?.broken_backlinks)} lowerIsBetter />} />
                  </div>
                  <div className="grid gap-4 lg:grid-cols-3">
                    <MetricTrendChart title="Referring domains" data={o.history.map((h) => ({ ...label(h.date, h.source), value: h.referring_domains }))} />
                    <MetricTrendChart title="Backlinks" data={o.history.map((h) => ({ ...label(h.date, h.source), value: h.backlinks }))} />
                    <MetricTrendChart title="Authority" data={o.history.map((h) => ({ ...label(h.date, h.source), value: h.authority }))} />
                  </div>
                  <div className="grid gap-4 xl:grid-cols-2">
                    <RefDomainsTable projectId={projectId} />
                    <LinksTable projectId={projectId} kind="broken" />
                    <LinksTable projectId={projectId} kind="new" />
                    <LinksTable projectId={projectId} kind="lost" />
                  </div>
                </>
              )}
              <LinkGap projectId={projectId} />
            </div>
          );
        }}
      </AsyncState>
    </div>
  );
}
```

Check `KpiTile` renders `hint` as visible text, so the test's "DataForSEO rank, 0–1000" is on screen. It does in Phase 4. Check `Platform.listCompetitors` returns `{items: [{id, domain}]}` (Phase 4). The test's `findAllByText(/Redirect this URL/)` is satisfied by the broken table's note.

`components/platform/project-tabs.tsx`: add `{ suffix: "/backlinks", label: "Backlinks" },` after Content Gap.

- [ ] **Step 5: Run and pass, gated, then commit**

```bash
npx vitest run > /tmp/fe.txt 2>&1; echo "vitest exit=$?"; grep -E "Tests " /tmp/fe.txt
npx tsc --noEmit; echo "tsc exit=$?"
(cd ../backend && python -m pytest -q > /tmp/t.txt 2>&1; echo "pytest exit=$?")
git add packages/shared/src apps/frontend
git commit -m "feat(frontend): Backlinks tab (authority, growth, referring domains, new/lost/broken links, link gap)"
```

---

### Task 7: Docs and the dry-run live check

- [ ] **Step 1: Env, compose, docs**

`apps/backend/.env.example`, after `DATAFORSEO_LABS_DAILY_CAP=20`:

```
# Hard daily cap on DataForSEO Backlinks API requests (~$0.024 each plus
# $0.000036 a row; one backlink snapshot is 5 requests, about $0.25).
DATAFORSEO_BACKLINKS_DAILY_CAP=20
```

- `deploy/oracle/docker-compose.yml` backend env: `DATAFORSEO_BACKLINKS_DAILY_CAP: ${DATAFORSEO_BACKLINKS_DAILY_CAP:-20}` after the Labs cap line.
- `docs/env.md`: a row for `DATAFORSEO_BACKLINKS_DAILY_CAP`.
- `docs/api.md`: a "Backlinks" section covering:
  - what's fetched per snapshot, and its cost
  - that authority is DataForSEO's rank
  - the opt-in weekly schedule (never on dry run)
  - each endpoint (with the overview example from Task 5)
  - the link gap (1–5 competitors; 400/429/502)
  - `BACKLINK_TO_BROKEN_PAGE`
  - that a DataForSEO account may need Backlinks activated (a 40104-style error says so)
- `README.md`: a "Backlinks (Phase 6)" section with **How to verify (no money spent)**:

```bash
cd apps/backend
python -m pytest tests/test_backlinks_provider.py tests/test_backlinks_storage.py tests/test_backlinks_snapshot.py tests/test_backlinks_gap_audit.py tests/test_backlinks_api.py -q
export SESSION_DIR=/tmp/seo-backlinks          # DataForSEO not configured = dry run
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links   # creates project 1
python -m uvicorn app.main:app --port 5000 &
curl -s -X POST localhost:5000/api/projects/1/backlinks/refresh
curl -s localhost:5000/api/projects/1/backlinks | python -c "import sys,json; d=json.load(sys.stdin); print(d['dry_run_provider'], d['latest'])"
curl -s -X POST -H 'Content-Type: application/json' -d '{"domain":"amazon.com"}' localhost:5000/api/projects/1/competitors
curl -s -X POST -H 'Content-Type: application/json' -d '{}' localhost:5000/api/projects/1/backlinks/gap | python -c "import sys,json; print(json.load(sys.stdin)['rows'][:2])"
```

Commit the docs (with the suite gated).

- [ ] **Step 2: Live check (dry run)**

1. Run the README block. Expect `refreshed`, the overview with `latest`, 12 history months, and the gap rows.
2. Check the audit join. Run a second audit after the refresh. The dry run's broken targets are `https://books.toscrape.com/old-page-N`, which don't exist, so the crawl won't fetch them. Confirm `BACKLINK_TO_BROKEN_PAGE` doesn't misfire, and that the broken table's `crawled_status` is empty. (The issue path itself is covered by Task 4's test.)
3. UI at 1440 and 390 px (Playwright screenshots if the Chrome extension isn't connected):
   - the Backlinks tab: banner, KPIs, three charts with table toggles, tables, weekly switch, Refresh now, link gap run
   - no sideways scroll
4. Fix anything found (with a test when it's behaviour), commit, and stop the servers.
5. Report: no DataForSEO credentials are set, so the sandbox parser check and the first paid call wait for them and the owner's go-ahead.
