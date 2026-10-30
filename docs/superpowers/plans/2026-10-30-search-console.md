# Google Search Console (Phase 5.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Projects connect to Google Search Console through a service account
(or dry run). A daily sync stores performance (daily totals, top pages, top
queries). Audits inspect important pages' index status, raising issues. A
Search Console tab and audit sections show it all, joined to crawled pages.

**Architecture:**
- `app/gsc/` holds:
  - `provider.py`: the interface, `ServiceAccountGsc` (google-auth + REST), `DryRunGsc` and `build_gsc_provider`
  - `sync.py`: property resolution and the daily sync
  - `inspect.py`: audit-time inspection and its issues
- New tables come in migration 0008.
- A `gsc` API router, a scheduler job, and a pipeline step after the browser
  pass.
- Frontend: a Search Console tab, plus an audit section reused on the Site
  Audit tab and in the report.

**Tech Stack:** Python, google-auth 2.62 (installed), requests, SQLAlchemy/Alembic, APScheduler, FastAPI, pytest; Next.js 14, Recharts, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-search-console-design.md`

## Global Constraints

- **Auth:** a service account key at `GSC_SERVICE_ACCOUNT_FILE`, scope `https://www.googleapis.com/auth/webmasters.readonly`. `GSC_DRY_RUN=true` uses deterministic fake data. Neither configured means not configured.
- **Endpoints:**
  - `GET https://www.googleapis.com/webmasters/v3/sites`
  - `POST https://www.googleapis.com/webmasters/v3/sites/{quote(site,safe='')}/searchAnalytics/query`
  - `POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`
- **Caps** via `reserve()`: `gsc` with `GSC_DAILY_CAP` (default 100), `gsc_inspect` with `GSC_INSPECT_DAILY_CAP` (default 200). `GSC_INSPECT_MAX_PAGES` defaults to 20.
- **Sync:** data ends at today − 2 days. Daily totals cover 90 days (upserted). Pages and queries cover 28 days, up to 1,000 rows each (replaced). Three calls finish before one write transaction.
- **Property match:** `sc-domain:<domain>` first, then a URL-prefix property with the same `project_domain` (`https` before `www`). `siteUnverifiedUser` is ignored. Dry run uses `sc-domain:<domain>`.
- **Issues:**
  - `GSC_NOT_INDEXED` (warning): verdict FAIL or NEUTRAL, unless meta robots or X-Robots-Tag has `noindex`
  - `GSC_CANONICAL_MISMATCH` (info): both canonicals present and different after `normalize_url`
- **Never fatal.** Key file contents never appear in errors or logs. No real Google call in tests or the live check (the owner gives the go for the first one).
- **Commits:** the full backend suite must pass, judged by pytest's exit code, before each commit.

---

### Task 1: Provider layer, config, dependency

**Files:**
- Create: `apps/backend/app/gsc/__init__.py`, `apps/backend/app/gsc/provider.py`, `apps/backend/tests/test_gsc_provider.py`
- Modify: `apps/backend/app/config/config.py`, `apps/backend/tests/conftest.py`, `apps/backend/requirements.txt`

**Interfaces:**
- Produces:
  - `GscError(status, message)` with `.status` and `.message`
  - `SiteEntry(site_url, permission)`
  - `AnalyticsRow(keys, clicks, impressions, ctr, position)`
  - `Inspection(url, verdict=None, coverage_state=None, indexing_state=None, robots_state=None, fetch_state=None, google_canonical=None, user_canonical=None, last_crawl=None, error=None)` with `.to_dict()`
  - `parse_inspection(url, data) -> Inspection`
  - `ServiceAccountGsc(key_file, session=None)` with `.client_email`
  - `DryRunGsc()`
  - `build_gsc_provider() -> Optional[provider]`
  - `site_domain(site_url) -> str`
  - Config: `GSC_SERVICE_ACCOUNT_FILE, GSC_DRY_RUN, GSC_DAILY_CAP, GSC_INSPECT_DAILY_CAP, GSC_INSPECT_MAX_PAGES`

- [ ] **Step 1: Config, isolation, dependency**

Append to `app/config/config.py` (after `RENDER_TIMEOUT_MS`):

```python
# Google Search Console (Phase 5.5): a service account's JSON key, with its
# email added as a user on each property. Free API, but quota'd, so capped.
GSC_SERVICE_ACCOUNT_FILE = os.getenv("GSC_SERVICE_ACCOUNT_FILE", "")
GSC_DRY_RUN = os.getenv("GSC_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
GSC_DAILY_CAP = int(os.getenv("GSC_DAILY_CAP", "100"))
GSC_INSPECT_DAILY_CAP = int(os.getenv("GSC_INSPECT_DAILY_CAP", "200"))
GSC_INSPECT_MAX_PAGES = int(os.getenv("GSC_INSPECT_MAX_PAGES", "20"))
```

Append to the `no_live_web_vitals` fixture in `tests/conftest.py` (same function, so every test is isolated):

```python
    monkeypatch.setattr(app_config, "GSC_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setattr(app_config, "GSC_DRY_RUN", False)
```

Append to `requirements.txt`:

```
# Google Search Console (Phase 5.5): service-account auth for the read-only
# Search Console API. Only used when GSC_SERVICE_ACCOUNT_FILE is set.
google-auth>=2.20
```

- [ ] **Step 2: Write the failing test**

```python
"""Search Console provider: request shapes, parsing, errors, caps, dry run."""

import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.config import config
from app.gsc import provider as gp
from app.gsc.provider import (DryRunGsc, GscError, Inspection, ServiceAccountGsc, build_gsc_provider,
                              parse_inspection, site_domain)


class FakeSession:
    def __init__(self, responses):
        self.calls, self.responses = [], list(responses)

    def request(self, method, url, json=None, timeout=None):
        self.calls.append((method, url, json))
        status, body = self.responses.pop(0)
        resp = MagicMock(status_code=status, text=str(body))
        resp.json.return_value = body
        return resp


@pytest.fixture
def key_file(tmp_path):
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"client_email": "auditor@proj.iam.gserviceaccount.com",
                                "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----"}))
    return str(path)


def test_sites_and_client_email(key_file):
    session = FakeSession([(200, {"siteEntry": [{"siteUrl": "sc-domain:shop.com", "permissionLevel": "siteFullUser"}]})])
    gsc = ServiceAccountGsc(key_file, session=session)
    assert gsc.client_email == "auditor@proj.iam.gserviceaccount.com"
    assert [(s.site_url, s.permission) for s in gsc.sites()] == [("sc-domain:shop.com", "siteFullUser")]
    assert session.calls == [("GET", "https://www.googleapis.com/webmasters/v3/sites", None)]


def test_search_analytics_request_and_rows(key_file):
    session = FakeSession([(200, {"rows": [{"keys": ["https://shop.com/a"], "clicks": 12, "impressions": 340,
                                            "ctr": 0.035, "position": 7.2}]})])
    rows = ServiceAccountGsc(key_file, session=session).search_analytics(
        "sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 28), ["page"], 1000)
    method, url, body = session.calls[0]
    assert url == "https://www.googleapis.com/webmasters/v3/sites/sc-domain%3Ashop.com/searchAnalytics/query"
    assert body == {"startDate": "2026-10-01", "endDate": "2026-10-28", "dimensions": ["page"], "rowLimit": 1000}
    assert rows[0].keys == ("https://shop.com/a",) and rows[0].clicks == 12.0 and rows[0].position == 7.2


def test_inspection_request_and_parsing(key_file):
    result = {"inspectionResult": {"indexStatusResult": {
        "verdict": "NEUTRAL", "coverageState": "Crawled - currently not indexed", "indexingState": "INDEXING_ALLOWED",
        "robotsTxtState": "ALLOWED", "pageFetchState": "SUCCESSFUL", "googleCanonical": "https://shop.com/a",
        "userCanonical": "https://shop.com/a/", "lastCrawlTime": "2026-10-20T08:00:00Z"}}}
    session = FakeSession([(200, result)])
    insp = ServiceAccountGsc(key_file, session=session).inspect("sc-domain:shop.com", "https://shop.com/a")
    assert session.calls[0] == ("POST", "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                                {"inspectionUrl": "https://shop.com/a", "siteUrl": "sc-domain:shop.com"})
    assert (insp.verdict, insp.coverage_state, insp.google_canonical, insp.last_crawl) == (
        "NEUTRAL", "Crawled - currently not indexed", "https://shop.com/a", "2026-10-20T08:00:00Z")
    assert parse_inspection("u", {}) == Inspection(url="u")


def test_errors_carry_googles_message_and_never_the_key(key_file):
    session = FakeSession([(403, {"error": {"message": "User does not have sufficient permission"}})])
    with pytest.raises(GscError) as err:
        ServiceAccountGsc(key_file, session=session).sites()
    assert err.value.status == 403
    assert err.value.message == "the service account has no access to this property (User does not have sufficient permission)"
    assert "SECRET" not in err.value.message


def test_inspection_errors_and_caps_are_per_url(key_file, monkeypatch):
    session = FakeSession([(500, {"error": {"message": "Backend Error"}})])
    insp = ServiceAccountGsc(key_file, session=session).inspect("sc-domain:shop.com", "https://shop.com/a")
    assert insp.error == "Backend Error" and insp.verdict is None
    monkeypatch.setattr(config, "GSC_INSPECT_DAILY_CAP", 0)
    capped = ServiceAccountGsc(key_file, session=FakeSession([])).inspect("sc-domain:shop.com", "https://shop.com/b")
    assert capped.error == "daily cap of 0 gsc_inspect calls reached"
    monkeypatch.setattr(config, "GSC_DAILY_CAP", 0)
    with pytest.raises(GscError) as err:
        ServiceAccountGsc(key_file, session=FakeSession([])).search_analytics("p", date(2026, 1, 1), date(2026, 1, 2), ["date"])
    assert err.value.status == 429


def test_network_errors_name_the_type_only(key_file):
    class Boom:
        def request(self, *a, **k):
            raise ConnectionError("https://...?access_token=SECRET")
    with pytest.raises(GscError) as err:
        ServiceAccountGsc(key_file, session=Boom()).sites()
    assert err.value.message == "Search Console request failed: ConnectionError"


def test_dry_run_is_deterministic_and_well_formed():
    a, b = DryRunGsc(), DryRunGsc()
    days = a.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 3), ["date"])
    assert [r.keys[0] for r in days] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert days == b.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 3), ["date"])
    pages = a.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 28), ["page"])
    assert pages[0].keys[0] == "https://shop.com/" and all(r.keys[0].startswith("https://shop.com/") for r in pages)
    assert len(a.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 28), ["query"])) > 5
    verdicts = {a.inspect("sc-domain:shop.com", f"https://shop.com/p{i}").verdict for i in range(20)}
    assert verdicts == {"PASS", "NEUTRAL"} and a.dry_run is True


def test_site_domain():
    assert site_domain("sc-domain:shop.com") == "shop.com"
    assert site_domain("https://www.shop.com/") == "shop.com"


def test_build_modes(monkeypatch, key_file):
    assert build_gsc_provider() is None
    monkeypatch.setattr(config, "GSC_SERVICE_ACCOUNT_FILE", key_file)
    assert isinstance(build_gsc_provider(), ServiceAccountGsc)
    monkeypatch.setattr(config, "GSC_SERVICE_ACCOUNT_FILE", key_file + ".missing")
    assert build_gsc_provider() is None
    monkeypatch.setattr(config, "GSC_DRY_RUN", True)
    assert isinstance(build_gsc_provider(), DryRunGsc)
```

- [ ] **Step 3: Run and watch it fail**

Run: `cd apps/backend && python -m pytest tests/test_gsc_provider.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.gsc'`

- [ ] **Step 4: Implement**

`app/gsc/__init__.py`:

```python
"""Google Search Console: index status and search performance (Phase 5.5)."""
```

`app/gsc/provider.py`:

```python
"""Search Console behind a provider interface: the service-account client,
a deterministic dry run, and the factory that picks one."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Protocol, Tuple
from urllib.parse import quote, urlsplit

from app.config import config
from app.providers.serp import ProviderSkipped
from app.providers.spend import reserve

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
WEBMASTERS = "https://www.googleapis.com/webmasters/v3"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"


class GscError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class SiteEntry:
    site_url: str
    permission: str


@dataclass(frozen=True)
class AnalyticsRow:
    keys: Tuple[str, ...]
    clicks: float
    impressions: float
    ctr: float
    position: float


@dataclass
class Inspection:
    url: str
    verdict: Optional[str] = None
    coverage_state: Optional[str] = None
    indexing_state: Optional[str] = None
    robots_state: Optional[str] = None
    fetch_state: Optional[str] = None
    google_canonical: Optional[str] = None
    user_canonical: Optional[str] = None
    last_crawl: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GscProvider(Protocol):
    name: str
    dry_run: bool
    client_email: Optional[str]

    def sites(self) -> List[SiteEntry]: ...

    def search_analytics(self, site_url: str, start: date, end: date, dimensions: List[str],
                         row_limit: int = 1000) -> List[AnalyticsRow]: ...

    def inspect(self, site_url: str, url: str) -> Inspection: ...


def site_domain(site_url: str) -> str:
    """The bare domain a property covers: sc-domain:x -> x, https://www.x/ -> x."""
    if site_url.startswith("sc-domain:"):
        return site_url[len("sc-domain:"):].lower()
    host = (urlsplit(site_url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def parse_inspection(url: str, data: Dict[str, Any]) -> Inspection:
    r = (data.get("inspectionResult") or {}).get("indexStatusResult") or {}
    return Inspection(url=url, verdict=r.get("verdict"), coverage_state=r.get("coverageState"),
                      indexing_state=r.get("indexingState"), robots_state=r.get("robotsTxtState"),
                      fetch_state=r.get("pageFetchState"), google_canonical=r.get("googleCanonical"),
                      user_canonical=r.get("userCanonical"), last_crawl=r.get("lastCrawlTime"))


def _client_email(key_file: str) -> Optional[str]:
    try:
        with open(key_file, encoding="utf-8") as fh:
            return json.load(fh).get("client_email")
    except (OSError, ValueError):
        return None


def _message(resp) -> str:
    try:
        detail = ((resp.json() or {}).get("error") or {}).get("message") or ""
    except ValueError:
        detail = (resp.text or "")[:200]
    if resp.status_code == 403:
        base = "the service account has no access to this property"
        return f"{base} ({detail})" if detail else base
    return detail[:300] or f"HTTP {resp.status_code}"


class ServiceAccountGsc:
    name = "gsc"
    dry_run = False

    def __init__(self, key_file: str, session=None) -> None:
        self.key_file = key_file
        self._session = session
        self.client_email = _client_email(key_file)

    def _http(self):
        if self._session is None:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(self.key_file, scopes=[SCOPE])
            self._session = AuthorizedSession(credentials)
        return self._session

    def _call(self, method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            resp = self._http().request(method, url, json=body, timeout=60)
        except Exception as exc:
            # The type only: messages can carry tokens or the key path.
            raise GscError(0, f"Search Console request failed: {type(exc).__name__}")
        if resp.status_code >= 300:
            raise GscError(resp.status_code, _message(resp))
        try:
            return resp.json() or {}
        except ValueError:
            raise GscError(resp.status_code, "Search Console returned invalid JSON")

    def sites(self) -> List[SiteEntry]:
        data = self._call("GET", f"{WEBMASTERS}/sites")
        return [SiteEntry(e.get("siteUrl", ""), e.get("permissionLevel", "")) for e in data.get("siteEntry") or []]

    def search_analytics(self, site_url, start, end, dimensions, row_limit=1000):
        try:
            reserve("gsc", config.GSC_DAILY_CAP)
        except ProviderSkipped as exc:
            raise GscError(429, str(exc))
        data = self._call("POST", f"{WEBMASTERS}/sites/{quote(site_url, safe='')}/searchAnalytics/query", {
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": list(dimensions), "rowLimit": row_limit,
        })
        return [AnalyticsRow(tuple(r.get("keys") or ()), float(r.get("clicks", 0)), float(r.get("impressions", 0)),
                             float(r.get("ctr", 0)), float(r.get("position", 0))) for r in data.get("rows") or []]

    def inspect(self, site_url: str, url: str) -> Inspection:
        try:
            reserve("gsc_inspect", config.GSC_INSPECT_DAILY_CAP)
        except ProviderSkipped as exc:
            return Inspection(url=url, error=str(exc))
        try:
            data = self._call("POST", INSPECT_URL, {"inspectionUrl": url, "siteUrl": site_url})
        except GscError as exc:
            return Inspection(url=url, error=exc.message)
        return parse_inspection(url, data)


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


class DryRunGsc:
    """Made-up but stable data, so the UI and the pipeline can be tried
    without Google. Every row it writes is marked dry_run."""

    name = "gsc_dry_run"
    dry_run = True
    client_email = "dry-run@example.iam.gserviceaccount.com"

    def sites(self) -> List[SiteEntry]:
        return []

    def search_analytics(self, site_url, start, end, dimensions, row_limit=1000):
        domain = site_domain(site_url) or "example.com"
        base = _seed(site_url) % 40 + 20
        dim = dimensions[0] if dimensions else "date"
        if dim == "date":
            out, day, i = [], start, 0
            while day <= end:
                clicks = base + (i * 7) % 13 + (8 if day.weekday() < 5 else 0)
                impressions = clicks * 38 + (i * 11) % 90
                out.append(AnalyticsRow((day.isoformat(),), float(clicks), float(impressions),
                                        round(clicks / impressions, 4), round(11.5 - (i % 30) * 0.05, 2)))
                day, i = day + timedelta(days=1), i + 1
            return out[:row_limit]
        if dim == "page":
            paths = [""] + [f"catalogue/category/books/page-{n}/index.html" for n in range(1, 30)]
            keys = [f"https://{domain}/{p}" for p in paths]
        else:
            words = domain.split(".")[0]
            keys = [f"{words} {w}" for w in ("books", "online", "shop", "cheap books", "best sellers", "classics",
                                               "poetry", "travel books", "mystery novels", "free delivery")]
        rows = []
        for n, key in enumerate(keys):
            clicks = max(0, base * 6 // (n + 1) - n)
            impressions = clicks * 30 + 200 // (n + 1) + (_seed(key) % 50)
            rows.append(AnalyticsRow((key,), float(clicks), float(impressions),
                                     round(clicks / impressions, 4) if impressions else 0.0,
                                     round(3 + n * 1.7 + (_seed(key) % 10) / 10, 2)))
        return rows[:row_limit]

    def inspect(self, site_url: str, url: str) -> Inspection:
        not_indexed = _seed(url) % 5 == 0
        return Inspection(
            url=url, verdict="NEUTRAL" if not_indexed else "PASS",
            coverage_state="Crawled - currently not indexed" if not_indexed else "Submitted and indexed",
            indexing_state="INDEXING_ALLOWED", robots_state="ALLOWED", fetch_state="SUCCESSFUL",
            google_canonical=url, user_canonical=url, last_crawl="2026-10-20T08:00:00Z")


def build_gsc_provider():
    """Dry run when GSC_DRY_RUN; the service account when its key file exists;
    otherwise None (not configured)."""
    if config.GSC_DRY_RUN:
        return DryRunGsc()
    path = config.GSC_SERVICE_ACCOUNT_FILE
    if path and os.path.isfile(path):
        return ServiceAccountGsc(path)
    if path:
        logger.warning("GSC_SERVICE_ACCOUNT_FILE is set but no file is there")
    return None
```

The dry-run test expects both `PASS` and `NEUTRAL` among 20 URLs with `_seed(url) % 5 == 0`. If a run shows only `PASS` for that set, check the seed rather than weakening the test.

- [ ] **Step 5: Run and pass, full suite gated, then commit**

```bash
python -m pytest tests/test_gsc_provider.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt   # commit only on exit=0
git add apps/backend/app/gsc apps/backend/app/config/config.py apps/backend/tests/conftest.py apps/backend/requirements.txt apps/backend/tests/test_gsc_provider.py
git commit -m "feat(gsc): Search Console provider (service account, dry run) with caps"
```

---

### Task 2: Storage and the project property

**Files:**
- Create: `apps/backend/alembic/versions/0008_search_console.py`, `apps/backend/tests/test_gsc_storage.py`
- Modify: `apps/backend/app/db/models.py`, `apps/backend/app/api/projects.py`, `apps/backend/tests/test_db_schema.py`

**Interfaces:**
- Produces:
  - `Project.gsc_property`, `Project.last_gsc_sync_at`
  - models `GscDaily`, `GscPage`, `GscQuery`, `GscInspection`
  - the project JSON gains `gsc_property` and `last_gsc_sync_at`
  - `PATCH /projects/{id}` accepts `gsc_property` (an empty string → `None`)

- [ ] **Step 1: Write the failing test**

```python
"""Search Console tables and the project's property setting."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session_factory
from app.db.models import GscDaily, Project
from app.main import app


def test_daily_rows_are_unique_per_project_and_date():
    with get_session_factory().begin() as s:
        p = Project(name="a.com", domain="a.com"); s.add(p); s.flush()
        s.add(GscDaily(project_id=p.id, date=date(2026, 10, 1), clicks=1, impressions=10, ctr=0.1, position=5))
    with pytest.raises(IntegrityError):
        with get_session_factory().begin() as s:
            s.add(GscDaily(project_id=p.id, date=date(2026, 10, 1), clicks=2, impressions=10, ctr=0.2, position=4))


def test_property_is_set_and_cleared_through_patch():
    client = TestClient(app)
    pid = client.post("/api/projects", json={"domain": "shop.com"}).json()["id"]
    body = client.patch(f"/api/projects/{pid}", json={"gsc_property": "sc-domain:shop.com"}).json()
    assert body["gsc_property"] == "sc-domain:shop.com" and body["last_gsc_sync_at"] is None
    assert client.patch(f"/api/projects/{pid}", json={"gsc_property": ""}).json()["gsc_property"] is None
```

Add `"gsc_daily", "gsc_pages", "gsc_queries", "gsc_inspections"` to `TABLES` in `tests/test_db_schema.py`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_gsc_storage.py tests/test_db_schema.py -q`
Expected: FAIL with `ImportError: cannot import name 'GscDaily'`

- [ ] **Step 3: Models**

In `app/db/models.py`, in `class Project`, add after `alert_settings_json`:

```python
    gsc_property: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_gsc_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

Append:

```python
class GscDaily(Base):
    """One day of a project's Search Console totals (Phase 5.5), kept past
    Google's 16-month window."""
    __tablename__ = "gsc_daily"
    __table_args__ = (UniqueConstraint("project_id", "date", name="uq_gsc_daily_project_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    clicks: Mapped[float] = mapped_column(Float)
    impressions: Mapped[float] = mapped_column(Float)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class GscPage(Base):
    """The latest 28-day Search Console numbers per page (replaced on each sync)."""
    __tablename__ = "gsc_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    clicks: Mapped[float] = mapped_column(Float)
    impressions: Mapped[float] = mapped_column(Float)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class GscQuery(Base):
    """The latest 28-day Search Console numbers per query (replaced on each sync)."""
    __tablename__ = "gsc_queries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text)
    clicks: Mapped[float] = mapped_column(Float)
    impressions: Mapped[float] = mapped_column(Float)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class GscInspection(Base):
    """One page's URL Inspection result in one audit."""
    __tablename__ = "gsc_inspections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    verdict: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    coverage_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indexing_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    robots_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    fetch_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    google_canonical: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_canonical: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_crawl: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
```

`GscDaily.date` shadows the `date` type inside the class body. That's fine
here because `Mapped[date]` resolves `date` from the module, but run the
schema test to be sure. If SQLAlchemy complains, annotate it as
`Mapped[datetime_date]` with `from datetime import date as datetime_date`
at the top.

- [ ] **Step 4: Migration `alembic/versions/0008_search_console.py`**

```python
"""search console

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def _stats(table):
    return [sa.Column('clicks', sa.Float(), nullable=False), sa.Column('impressions', sa.Float(), nullable=False),
            sa.Column('ctr', sa.Float(), nullable=False), sa.Column('position', sa.Float(), nullable=False)]


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('gsc_property', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('last_gsc_sync_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('gsc_daily',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    *_stats('gsc_daily'),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'date', name='uq_gsc_daily_project_date')
    )
    op.create_index(op.f('ix_gsc_daily_project_id'), 'gsc_daily', ['project_id'], unique=False)

    for table, key in (('gsc_pages', 'url'), ('gsc_queries', 'query')):
        op.create_table(table,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column(key, sa.Text(), nullable=False),
        *_stats(table),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dry_run', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f(f'ix_{table}_project_id'), table, ['project_id'], unique=False)

    op.create_table('gsc_inspections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('verdict', sa.String(length=16), nullable=True),
    sa.Column('coverage_state', sa.Text(), nullable=True),
    sa.Column('indexing_state', sa.String(length=64), nullable=True),
    sa.Column('robots_state', sa.String(length=32), nullable=True),
    sa.Column('fetch_state', sa.String(length=64), nullable=True),
    sa.Column('google_canonical', sa.Text(), nullable=True),
    sa.Column('user_canonical', sa.Text(), nullable=True),
    sa.Column('last_crawl', sa.String(length=40), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gsc_inspections_audit_id'), 'gsc_inspections', ['audit_id'], unique=False)


def downgrade() -> None:
    for table in ('gsc_inspections', 'gsc_queries', 'gsc_pages', 'gsc_daily'):
        op.drop_index(op.f(f'ix_{table}_{"audit_id" if table == "gsc_inspections" else "project_id"}'), table_name=table)
        op.drop_table(table)
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('last_gsc_sync_at')
        batch_op.drop_column('gsc_property')
```

- [ ] **Step 5: Project API**

In `app/api/projects.py`:
- Add `gsc_property: Optional[str] = None` to `ProjectUpdate`.
- In `update_project`, add:

```python
        if "gsc_property" in fields:
            project.gsc_property = (fields["gsc_property"] or "").strip() or None
```

- In `_project_json`, add these to the returned dict:

```python
        "gsc_property": project.gsc_property,
        "last_gsc_sync_at": as_utc(project.last_gsc_sync_at).isoformat() if project.last_gsc_sync_at else None,
```

- [ ] **Step 6: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_gsc_storage.py tests/test_db_schema.py tests/test_projects_api.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/db/models.py apps/backend/alembic/versions/0008_search_console.py apps/backend/app/api/projects.py apps/backend/tests/test_gsc_storage.py apps/backend/tests/test_db_schema.py
git commit -m "feat(gsc): Search Console tables (migration 0008) and project property"
```

---

### Task 3: Property resolution, sync, scheduler

**Files:**
- Create: `apps/backend/app/gsc/sync.py`, `apps/backend/tests/test_gsc_sync.py`
- Modify: `apps/backend/app/scheduler/jobs.py`

**Interfaces:**
- Produces:
  - `match_property(domain, sites) -> Optional[str]`
  - `resolve_property(domain, provider, factory=None) -> Optional[str]` (saves a match onto the project when one exists; raises `GscError`)
  - `sync_project(project_id, provider, today=None, factory=None) -> dict`
  - `jobs.run_due_gsc_syncs(now=None, provider=None) -> List[int]`

- [ ] **Step 1: Write the failing test**

```python
"""Search Console sync: which property, what's stored, and the daily job."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.engine import get_session_factory
from app.db.models import GscDaily, GscPage, GscQuery, Project
from app.gsc.provider import AnalyticsRow, DryRunGsc, GscError, SiteEntry
from app.gsc.sync import match_property, resolve_property, sync_project
from app.scheduler import jobs


def test_match_prefers_domain_property_then_https_prefix():
    sites = [SiteEntry("http://shop.com/", "siteOwner"), SiteEntry("https://www.shop.com/", "siteFullUser"),
             SiteEntry("https://shop.com/", "siteUnverifiedUser"), SiteEntry("sc-domain:other.com", "siteOwner")]
    assert match_property("shop.com", sites) == "https://www.shop.com/"
    assert match_property("shop.com", sites + [SiteEntry("sc-domain:shop.com", "siteRestrictedUser")]) == "sc-domain:shop.com"
    assert match_property("nope.com", sites) is None


def _project(domain="shop.com", prop=None):
    with get_session_factory().begin() as s:
        p = Project(name=domain, domain=domain, gsc_property=prop); s.add(p); s.flush()
        return p.id


class Recording:
    name, dry_run, client_email = "rec", False, "sa@x.iam.gserviceaccount.com"

    def __init__(self, sites=(), fail_on=None):
        self.calls, self._sites, self.fail_on = [], list(sites), fail_on

    def sites(self):
        return self._sites

    def search_analytics(self, site, start, end, dims, row_limit=1000):
        self.calls.append((site, start, end, tuple(dims), row_limit))
        if self.fail_on == dims[0]:
            raise GscError(500, "Backend Error")
        if dims == ["date"]:
            return [AnalyticsRow((d.isoformat(),), 5, 100, 0.05, 8.0)
                    for d in (start, start + timedelta(days=1))]
        key = "https://shop.com/a" if dims == ["page"] else "buy books"
        return [AnalyticsRow((key,), 3, 50, 0.06, 4.0)]


def test_sync_resolves_saves_and_stores():
    pid = _project()
    provider = Recording([SiteEntry("sc-domain:shop.com", "siteOwner")])
    result = sync_project(pid, provider, today=date(2026, 10, 30))
    assert result == {"status": "synced", "property": "sc-domain:shop.com", "days": 2, "pages": 1, "queries": 1,
                      "dry_run": False}
    end = date(2026, 10, 28)
    assert [(c[1], c[2], c[3]) for c in provider.calls] == [
        (end - timedelta(days=89), end, ("date",)), (end - timedelta(days=27), end, ("page",)),
        (end - timedelta(days=27), end, ("query",))]
    with get_session_factory()() as s:
        project = s.get(Project, pid)
        assert project.gsc_property == "sc-domain:shop.com" and project.last_gsc_sync_at is not None
        assert s.scalar(select(func.count()).select_from(GscDaily)) == 2
        assert s.scalar(select(GscPage.url)) == "https://shop.com/a" and s.scalar(select(GscQuery.query)) == "buy books"


def test_resync_upserts_days_and_replaces_snapshots():
    pid = _project(prop="sc-domain:shop.com")
    sync_project(pid, Recording(), today=date(2026, 10, 30))
    sync_project(pid, Recording(), today=date(2026, 10, 30))
    with get_session_factory()() as s:
        assert s.scalar(select(func.count()).select_from(GscDaily)) == 2
        assert s.scalar(select(func.count()).select_from(GscPage)) == 1


def test_no_access_and_errors_write_nothing():
    pid = _project()
    result = sync_project(pid, Recording(sites=[]), today=date(2026, 10, 30))
    assert result["status"] == "no_access" and result["client_email"] == "sa@x.iam.gserviceaccount.com"
    pid2 = _project("b.com", prop="sc-domain:b.com")
    result = sync_project(pid2, Recording(fail_on="query"), today=date(2026, 10, 30))
    assert result == {"status": "error", "property": "sc-domain:b.com", "message": "Backend Error", "dry_run": False}
    with get_session_factory()() as s:
        assert s.scalar(select(func.count()).select_from(GscDaily)) == 0


def test_dry_run_uses_the_domain_property():
    pid = _project("books.example")
    assert sync_project(pid, DryRunGsc(), today=date(2026, 10, 30))["property"] == "sc-domain:books.example"
    with get_session_factory()() as s:
        assert all(r.dry_run for r in s.scalars(select(GscDaily)))


def test_resolve_property_without_a_project():
    assert resolve_property("new.com", Recording([SiteEntry("sc-domain:new.com", "siteOwner")])) == "sc-domain:new.com"


def test_scheduler_syncs_due_projects_only():
    now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    due = _project("due.com", prop="sc-domain:due.com")
    fresh = _project("fresh.com", prop="sc-domain:fresh.com")
    with get_session_factory().begin() as s:
        s.get(Project, fresh).last_gsc_sync_at = now - timedelta(hours=2)
    assert jobs.run_due_gsc_syncs(now=now, provider=Recording()) == [due]
    assert jobs.run_due_gsc_syncs(now=now) == []          # not configured: nothing runs
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_gsc_sync.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.gsc.sync'`

- [ ] **Step 3: Implement `app/gsc/sync.py`**

```python
"""Which Search Console property a project uses, and the daily sync."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, insert, select

from app.db.engine import get_session_factory
from app.db.models import GscDaily, GscPage, GscQuery, Project, utcnow
from app.db.projects import project_domain
from app.gsc.provider import GscError, SiteEntry

logger = logging.getLogger(__name__)
LAG_DAYS = 2


def match_property(domain: str, sites: List[SiteEntry]) -> Optional[str]:
    usable = [s.site_url for s in sites if s.permission != "siteUnverifiedUser"]
    if f"sc-domain:{domain}" in usable:
        return f"sc-domain:{domain}"
    prefixes = [u for u in usable if not u.startswith("sc-domain:") and project_domain(u) == domain]
    prefixes.sort(key=lambda u: (not u.startswith("https://"), "://www." not in u))
    return prefixes[0] if prefixes else None


def resolve_property(domain: str, provider, factory=None) -> Optional[str]:
    """The project's saved property, else a match from what the service account
    can see (saved onto the project when there is one). Raises GscError."""
    factory = factory or get_session_factory()
    with factory() as session:
        project = session.scalar(select(Project).where(Project.domain == domain))
        if project is not None and project.gsc_property:
            return project.gsc_property
    found = f"sc-domain:{domain}" if provider.dry_run else match_property(domain, provider.sites())
    if found:
        with factory.begin() as session:
            project = session.scalar(select(Project).where(Project.domain == domain))
            if project is not None and not project.gsc_property:
                project.gsc_property = found
    return found


def _stats(row) -> Dict[str, float]:
    return {"clicks": row.clicks, "impressions": row.impressions, "ctr": row.ctr, "position": row.position}


def sync_project(project_id: int, provider, today: Optional[date] = None, factory=None) -> Dict[str, Any]:
    factory = factory or get_session_factory()
    today = today or utcnow().date()
    with factory() as session:
        domain = session.get(Project, project_id).domain
    try:
        prop = resolve_property(domain, provider, factory)
    except GscError as exc:
        return {"status": "error", "property": None, "message": exc.message, "dry_run": provider.dry_run}
    if not prop:
        return {"status": "no_access", "property": None, "client_email": provider.client_email,
                "dry_run": provider.dry_run}
    end = today - timedelta(days=LAG_DAYS)
    try:
        daily = provider.search_analytics(prop, end - timedelta(days=89), end, ["date"], 1000)
        pages = provider.search_analytics(prop, end - timedelta(days=27), end, ["page"], 1000)
        queries = provider.search_analytics(prop, end - timedelta(days=27), end, ["query"], 1000)
    except GscError as exc:
        return {"status": "error", "property": prop, "message": exc.message, "dry_run": provider.dry_run}

    now, dry = utcnow(), provider.dry_run
    with factory.begin() as session:
        project = session.get(Project, project_id)
        project.gsc_property, project.last_gsc_sync_at = prop, now
        by_date = {date.fromisoformat(r.keys[0]): r for r in daily if r.keys}
        existing = {row.date: row for row in session.scalars(select(GscDaily).where(
            GscDaily.project_id == project_id, GscDaily.date.in_(list(by_date))))}
        for day, r in by_date.items():
            if day in existing:
                for key, value in _stats(r).items():
                    setattr(existing[day], key, value)
                existing[day].dry_run = dry
            else:
                session.add(GscDaily(project_id=project_id, date=day, dry_run=dry, **_stats(r)))
        session.execute(delete(GscPage).where(GscPage.project_id == project_id))
        session.execute(delete(GscQuery).where(GscQuery.project_id == project_id))
        if pages:
            session.execute(insert(GscPage), [{"project_id": project_id, "url": r.keys[0], "synced_at": now,
                                               "dry_run": dry, **_stats(r)} for r in pages if r.keys])
        if queries:
            session.execute(insert(GscQuery), [{"project_id": project_id, "query": r.keys[0], "synced_at": now,
                                                "dry_run": dry, **_stats(r)} for r in queries if r.keys])
    return {"status": "synced", "property": prop, "days": len(by_date), "pages": len(pages),
            "queries": len(queries), "dry_run": dry}
```

- [ ] **Step 4: Scheduler** (`app/scheduler/jobs.py`)

Add, after `run_due_rank_checks`:

```python
def run_due_gsc_syncs(now: Optional[datetime] = None, provider=None) -> List[int]:
    """Daily Search Console sync for every project. Only when a provider is
    configured; a failure on one project doesn't stop the others."""
    from app.gsc.provider import build_gsc_provider
    from app.gsc.sync import sync_project

    provider = provider if provider is not None else build_gsc_provider()
    if provider is None:
        return []
    now = now or utcnow()
    factory = get_session_factory()
    with factory() as session:
        due = [(p.id, p.last_gsc_sync_at) for p in session.scalars(select(Project)).all()
               if p.last_gsc_sync_at is None or now - as_utc(p.last_gsc_sync_at) >= timedelta(days=1)]
    synced: List[int] = []
    for project_id, previous in due:
        with factory() as session:
            if not claim(session, project_id, previous, now, column=Project.last_gsc_sync_at):
                continue
        try:
            result = sync_project(project_id, provider, today=now.date())
            if result["status"] == "synced":
                synced.append(project_id)
            else:
                logger.warning("Search Console sync of project %s: %s %s", project_id, result["status"],
                               result.get("message", ""))
        except Exception as exc:
            logger.error("Search Console sync of project %s failed: %s", project_id, exc, exc_info=exc)
    return synced
```

In `start_scheduler`, add:

```python
    scheduler.add_job(run_due_gsc_syncs, "interval", minutes=60, id="run_due_gsc_syncs",
                      max_instances=1, coalesce=True)
```

Check `select`, `timedelta`, `as_utc` and `logger` are already imported in `jobs.py`, and add any that aren't.

- [ ] **Step 5: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_gsc_sync.py tests/test_scheduler.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/gsc/sync.py apps/backend/app/scheduler/jobs.py apps/backend/tests/test_gsc_sync.py
git commit -m "feat(gsc): property matching, daily sync (90d totals, 28d pages/queries), scheduler job"
```

---

### Task 4: Index status during audits

**Files:**
- Create: `apps/backend/app/gsc/inspect.py`, `apps/backend/tests/test_gsc_audit.py`
- Modify:
  - `apps/backend/app/services/audit_service.py`
  - `apps/backend/app/db/audit_store.py`
  - `apps/backend/app/services/summary_fields.py`
  - `apps/backend/app/ai/ai_suggestions.py`
  - `apps/backend/app/schemas/schemas.py`
  - `apps/backend/app/api/routes.py`
  - `apps/backend/app/cli.py`
  - `apps/backend/app/scheduler/jobs.py`
  - `apps/backend/tests/test_cli.py`

**Interfaces:**
- Produces:
  - `inspect_for_audit(audit_url, start_page, top_pages, results, limit, provider=None) -> (status, property, dry_run, List[Inspection])`
  - `gsc_issues(inspection, meta_robots, x_robots) -> List[issue]`
  - Result keys: `gsc_inspections`, `gsc_status`, `gsc_property`, `gsc_dry_run`
  - `enable_gsc` on the request, `--no-gsc` on the CLI, `enable_gsc` from the scheduler

- [ ] **Step 1: Write the failing test**

```python
"""URL Inspection during audits: issues, storage, statuses, never fatal."""

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import GscInspection, Project
from app.gsc.inspect import gsc_issues
from app.gsc.provider import Inspection
from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler


def test_issue_rules():
    nope = Inspection(url="u", verdict="NEUTRAL", coverage_state="Crawled - currently not indexed")
    assert gsc_issues(nope, "", "") == [{"severity": "warning", "code": "GSC_NOT_INDEXED",
                                         "message": "Not indexed by Google: Crawled - currently not indexed"}]
    assert gsc_issues(nope, "noindex, follow", "") == []
    assert gsc_issues(nope, "", "NOINDEX") == []
    assert gsc_issues(Inspection(url="u", verdict="PASS"), "", "") == []
    moved = Inspection(url="u", verdict="PASS", google_canonical="https://a.com/x", user_canonical="https://a.com/y")
    assert [i["code"] for i in gsc_issues(moved, "", "")] == ["GSC_CANONICAL_MISMATCH"]
    same = Inspection(url="u", verdict="PASS", google_canonical="https://a.com/x", user_canonical="https://a.com/x")
    assert gsc_issues(same, "", "") == []
    assert gsc_issues(Inspection(url="u", error="cap"), "", "") == []


class Fake:
    name, dry_run, client_email = "fake", False, "sa@x"

    def __init__(self, verdict="NEUTRAL"):
        self.inspected, self.verdict = [], verdict

    def sites(self):
        return []

    def inspect(self, site, url):
        self.inspected.append((site, url))
        return Inspection(url=url, verdict=self.verdict, coverage_state="Discovered - currently not indexed")


def _run(**kwargs):
    return audit_service._build_audit_result("https://example.com/", FakeCrawler(), progress_callback=None,
                                             event_callback=None, **kwargs)


def test_inspects_issues_and_stores():
    with get_session_factory().begin() as s:
        s.add(Project(name="example.com", domain="example.com", gsc_property="sc-domain:example.com"))
    provider = Fake()
    result = _run(gsc_provider=provider)
    assert provider.inspected == [("sc-domain:example.com", "https://example.com/")]
    assert result["gsc_status"] == "inspected" and result["gsc_property"] == "sc-domain:example.com"
    codes = [i["code"] for i in result["page_issues_detail"]["https://example.com/"]]
    assert "GSC_NOT_INDEXED" in codes
    with get_session_factory()() as s:
        rows = s.scalars(select(GscInspection).where(GscInspection.audit_id == result["audit_id"])).all()
        assert [(r.url, r.verdict) for r in rows] == [("https://example.com/", "NEUTRAL")]


def test_statuses():
    assert _run()["gsc_status"] == "not_configured"
    assert _run(gsc_provider=Fake(), enable_gsc=False)["gsc_status"] == "disabled"
    assert _run(gsc_provider=Fake())["gsc_status"] == "no_property"


def test_a_crash_is_an_error_not_a_failed_audit():
    class Broken(Fake):
        def sites(self):
            raise RuntimeError("boom")
    result = _run(gsc_provider=Broken())
    assert result["gsc_status"] == "error" and result["persisted"] is True
```

Append to `tests/test_cli.py`:

```python
def test_no_gsc_flag():
    from unittest.mock import patch

    from app import cli

    for argv, expected in ((["https://example.com/", "--no-gsc"], False), (["https://example.com/"], True)):
        with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
            cli._run_audit(cli.build_parser().parse_args(argv))
        assert build.call_args.kwargs["enable_gsc"] is expected
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_gsc_audit.py tests/test_cli.py -q`
Expected: FAIL (`ModuleNotFoundError: app.gsc.inspect`).

- [ ] **Step 3: `app/gsc/inspect.py`**

```python
"""URL Inspection of an audit's most important pages, and the issues it raises."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.analysis.sampling import select_pages
from app.auditor.checks import issue
from app.crawler.crawler import normalize_url
from app.db.projects import project_domain
from app.gsc.provider import GscError, Inspection, build_gsc_provider
from app.gsc.sync import resolve_property

logger = logging.getLogger(__name__)


def gsc_issues(insp: Inspection, meta_robots: Optional[str], x_robots: Optional[str]) -> List[Dict[str, str]]:
    if insp.error:
        return []
    out = []
    deliberate = "noindex" in (meta_robots or "").lower() or "noindex" in (x_robots or "").lower()
    if insp.verdict in ("FAIL", "NEUTRAL") and not deliberate:
        out.append(issue("warning", "GSC_NOT_INDEXED", f"Not indexed by Google: {insp.coverage_state or insp.verdict}"))
    g, u = insp.google_canonical, insp.user_canonical
    if g and u and normalize_url(g) != normalize_url(u):
        out.append(issue("info", "GSC_CANONICAL_MISMATCH", f"Google chose {g} over your canonical {u}"))
    return out


def inspect_for_audit(audit_url: str, start_page: str, top_pages: List[Dict[str, Any]], results: Dict[str, Any],
                      limit: int, provider=None) -> Tuple[str, Optional[str], bool, List[Inspection]]:
    provider = provider if provider is not None else build_gsc_provider()
    if provider is None:
        return "not_configured", None, False, []
    try:
        prop = resolve_property(project_domain(audit_url), provider)
    except GscError as exc:
        logger.warning("Search Console property lookup failed: %s", exc.message)
        return "error", None, provider.dry_run, []
    if not prop:
        return "no_property", None, provider.dry_run, []
    return "inspected", prop, provider.dry_run, [provider.inspect(prop, url)
                                                for url in select_pages(start_page, top_pages, results, limit)]
```

- [ ] **Step 4: Pipeline, storage, flags**

`app/services/audit_service.py`:
1. Import `from app.gsc.inspect import gsc_issues, inspect_for_audit`.
2. `run_full_audit`: add the parameter `enable_gsc: bool = True` (after `accessibility`) and pass it through.
3. `_build_audit_result`: add the parameters `enable_gsc: bool = True, gsc_provider=None` after `accessibility`.
4. After the browser-pass block (before the custom-rules summary), add:

```python
    # Search Console: is Google indexing the pages that matter? Only with a
    # configured provider and a property; never fatal.
    gsc_status, gsc_property, gsc_dry_run, gsc_results = "disabled", None, False, []
    if enable_gsc:
        try:
            gsc_status, gsc_property, gsc_dry_run, gsc_results = inspect_for_audit(
                url, start_page, site_wide.get("top_pages_by_importance") or [], crawler.results,
                config.GSC_INSPECT_MAX_PAGES, provider=gsc_provider)
        except Exception as exc:
            logger.error("Search Console inspection failed: %s", exc, exc_info=exc)
            gsc_status = "error"
        for insp in gsc_results:
            page = crawler.results.get(insp.url)
            headers = {k.lower(): v for k, v in ((getattr(page, "headers", None) or {}).items())}
            found = gsc_issues(insp, (page_meta.get(insp.url) or {}).get("meta_robots"), headers.get("x-robots-tag"))
            if found:
                all_page_issues.setdefault(insp.url, []).extend(found)
                db.add_issues(insp.url, found)
```

5. In `result_data`, after `"custom_rules": rules_summary,`, add:

```python
        "gsc_inspections": [i.to_dict() for i in gsc_results],
        "gsc_status": gsc_status,
        "gsc_property": gsc_property,
        "gsc_dry_run": gsc_dry_run,
```

`app/services/summary_fields.py`: add `"gsc_status", "gsc_property", "gsc_dry_run", "gsc_inspections",` before `"note",`.

`app/db/audit_store.py`:
- Import `GscInspection`.
- Add the helper below, and call `_record_gsc(session, audit.id, result.get("gsc_inspections") or [], bool(result.get("gsc_dry_run")))` after `_record_accessibility(...)`.

```python
_GSC_COLUMNS = ("url", "verdict", "coverage_state", "indexing_state", "robots_state", "fetch_state",
                "google_canonical", "user_canonical", "last_crawl", "error")


def _record_gsc(session: Session, audit_id: int, rows: List[Dict[str, Any]], dry_run: bool) -> None:
    if rows:
        session.execute(insert(GscInspection), [
            {**{c: r.get(c) for c in _GSC_COLUMNS}, "audit_id": audit_id, "dry_run": dry_run} for r in rows])
```

`app/ai/ai_suggestions.py`:
- `IMPACT_WEIGHTS`: add `"GSC_NOT_INDEXED": 8, "GSC_CANONICAL_MISMATCH": 4,`.
- `RECOMMENDATION_TEXT`: add `"GSC_NOT_INDEXED": "Google isn't indexing this page: check its content quality, internal links and canonical, then request indexing in Search Console."` and `"GSC_CANONICAL_MISMATCH": "Google picked a different canonical: make the canonical, internal links and sitemap agree on one URL."`.

Request, routes, CLI and scheduler:
- `app/schemas/schemas.py`: add `enable_gsc: Optional[bool] = True` after `accessibility`, with a one-line comment.
- `app/api/routes.py`: add `enable_gsc=params.enable_gsc is not False,` to the `run_full_audit(` call.
- `app/cli.py`: add `p.add_argument("--no-gsc", dest="enable_gsc", action="store_false", help="Skip Search Console URL inspection")`. In `_run_audit`, pass `enable_gsc=args.enable_gsc,`.
- `app/scheduler/jobs.py`: in the audit `runner(` call, add `enable_gsc=bool(options.get("enable_gsc", True)),`.

- [ ] **Step 5: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_gsc_audit.py tests/test_cli.py tests/test_scheduler.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app apps/backend/tests
git commit -m "feat(gsc): inspect important pages during audits; GSC_NOT_INDEXED and canonical mismatch issues"
```

---

### Task 5: Search Console API

**Files:**
- Create: `apps/backend/app/api/gsc.py`, `apps/backend/tests/test_gsc_api.py`
- Modify: `apps/backend/app/main.py`

**Interfaces:**
- Produces (all under `/api`):
  - `GET /gsc/sites`
  - `GET /projects/{id}/gsc`
  - `GET /projects/{id}/gsc/pages`
  - `GET /projects/{id}/gsc/queries`
  - `POST /projects/{id}/gsc/sync`
  - `GET /audits/{id}/gsc`
  - `kpis(rows) -> {clicks, impressions, ctr, position}`

- [ ] **Step 1: Write the failing test**

```python
"""Search Console over HTTP."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import gsc as gsc_api
from app.config import config
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditPage, GscDaily, GscInspection, GscPage, GscQuery, Project
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _seed():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com", gsc_property="sc-domain:shop.com"); s.add(p); s.flush()
        start = date(2026, 9, 1)
        for i in range(56):   # previous 28 days, then the latest 28
            clicks = 10 if i < 28 else 20
            s.add(GscDaily(project_id=p.id, date=start + timedelta(days=i), clicks=clicks, impressions=100,
                           ctr=clicks / 100, position=10 if i < 28 else 5))
        t = datetime(2026, 10, 28, tzinfo=timezone.utc)
        for n, (url, clicks, impr) in enumerate([("https://shop.com/", 50, 900), ("https://shop.com/a", 9, 300),
                                                  ("https://shop.com/hidden", 2, 120)]):
            s.add(GscPage(project_id=p.id, url=url, clicks=clicks, impressions=impr, ctr=clicks / impr,
                          position=3 + n, synced_at=t))
        s.add(GscQuery(project_id=p.id, query="buy books", clicks=30, impressions=500, ctr=0.06, position=4, synced_at=t))
        audit = Audit(project_id=p.id, session_id="s1", start_url="https://shop.com/", status="completed",
                      trigger="manual", started_at=t, finished_at=t, page_count=2,
                      summary_json={"gsc_status": "inspected", "gsc_property": "sc-domain:shop.com", "gsc_dry_run": False})
        s.add(audit); s.flush()
        s.add_all([AuditPage(audit_id=audit.id, url="https://shop.com/", status=200),
                   AuditPage(audit_id=audit.id, url="https://shop.com/a", status=200),
                   GscInspection(audit_id=audit.id, url="https://shop.com/a", verdict="NEUTRAL",
                                 coverage_state="Crawled - currently not indexed")])
        return p.id, audit.id


def test_overview_kpis_compare_the_last_28_days(client, monkeypatch):
    monkeypatch.setattr(config, "GSC_DRY_RUN", True)
    pid, _ = _seed()
    body = client.get(f"/api/projects/{pid}/gsc").json()
    assert body["configured"] is True and body["property"] == "sc-domain:shop.com"
    assert body["kpis"] == {"clicks": 560, "impressions": 2800, "ctr": 0.2, "position": 5.0}
    assert body["previous_kpis"] == {"clicks": 280, "impressions": 2800, "ctr": 0.1, "position": 10.0}
    assert len(body["daily"]) == 56 and body["daily"][0]["date"] == "2026-09-01"


def test_overview_when_not_configured(client):
    pid, _ = _seed()
    body = client.get(f"/api/projects/{pid}/gsc").json()
    assert body["configured"] is False


def test_pages_and_queries_sort_and_page(client):
    pid, _ = _seed()
    pages = client.get(f"/api/projects/{pid}/gsc/pages?sort=impressions&limit=2").json()
    assert pages["total"] == 3 and [r["key"] for r in pages["items"]] == ["https://shop.com/", "https://shop.com/a"]
    by_position = client.get(f"/api/projects/{pid}/gsc/pages?sort=position").json()["items"]
    assert by_position[0]["position"] == 3       # best (lowest) position first
    assert client.get(f"/api/projects/{pid}/gsc/queries").json()["items"][0]["key"] == "buy books"
    assert client.get(f"/api/projects/{pid}/gsc/pages?sort=evil").status_code == 422


def test_audit_join(client):
    _, audit_id = _seed()
    body = client.get(f"/api/audits/{audit_id}/gsc").json()
    assert body["status"] == "inspected" and body["inspections"][0]["verdict"] == "NEUTRAL"
    assert [(p["url"], p["clicks"], p["inspection_verdict"]) for p in body["pages"]] == [
        ("https://shop.com/", 50, None), ("https://shop.com/a", 9, "NEUTRAL")]
    assert [p["url"] for p in body["not_crawled"]] == ["https://shop.com/hidden"]
    assert client.get("/api/audits/9999/gsc").status_code == 404


def test_sync_and_sites(client, monkeypatch):
    pid, _ = _seed()
    assert client.post(f"/api/projects/{pid}/gsc/sync").status_code == 409
    assert client.get("/api/gsc/sites").json() == {"configured": False, "dry_run": False, "client_email": None, "sites": []}
    monkeypatch.setattr(config, "GSC_DRY_RUN", True)
    result = client.post(f"/api/projects/{pid}/gsc/sync").json()
    assert result["status"] == "synced" and result["dry_run"] is True
    assert client.get("/api/gsc/sites").json()["dry_run"] is True
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_gsc_api.py -q`
Expected: FAIL (404s).

- [ ] **Step 3: Implement `app/api/gsc.py`**

```python
"""Search Console (Phase 5.5): status, performance, sync, and the audit join."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import asc, desc, func, select

from app.api.projects import _factory
from app.crawler.crawler import normalize_url
from app.db.models import Audit, AuditPage, GscDaily, GscInspection, GscPage, GscQuery, Project, as_utc
from app.gsc.provider import GscError, build_gsc_provider
from app.gsc.sync import sync_project

router = APIRouter()
Sort = Literal["clicks", "impressions", "ctr", "position"]


def kpis(rows) -> Dict[str, Any]:
    clicks = sum(r.clicks for r in rows)
    impressions = sum(r.impressions for r in rows)
    return {"clicks": round(clicks), "impressions": round(impressions),
            "ctr": round(clicks / impressions, 4) if impressions else None,
            "position": round(sum(r.position * r.impressions for r in rows) / impressions, 2) if impressions else None}


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/gsc/sites")
def gsc_sites():
    provider = build_gsc_provider()
    if provider is None:
        return {"configured": False, "dry_run": False, "client_email": None, "sites": []}
    try:
        sites = provider.sites()
    except GscError as exc:
        raise HTTPException(status_code=502, detail=exc.message)
    return {"configured": True, "dry_run": provider.dry_run, "client_email": provider.client_email,
            "sites": [{"site_url": s.site_url, "permission": s.permission} for s in sites]}


@router.get("/projects/{project_id}/gsc")
def gsc_overview(project_id: int):
    provider = build_gsc_provider()
    with _factory()() as session:
        project = _project(session, project_id)
        rows = session.scalars(select(GscDaily).where(GscDaily.project_id == project_id)
                               .order_by(desc(GscDaily.date)).limit(90)).all()[::-1]
        latest, previous = rows[-28:], rows[-56:-28]
        return {
            "configured": provider is not None,
            "dry_run": bool((provider is not None and provider.dry_run) or any(r.dry_run for r in latest)),
            "client_email": provider.client_email if provider is not None else None,
            "property": project.gsc_property,
            "last_sync_at": as_utc(project.last_gsc_sync_at).isoformat() if project.last_gsc_sync_at else None,
            "kpis": kpis(latest) if latest else None,
            "previous_kpis": kpis(previous) if previous else None,
            "daily": [{"date": r.date.isoformat(), "clicks": r.clicks, "impressions": r.impressions,
                       "ctr": r.ctr, "position": r.position} for r in rows],
        }


def _listing(model, key_column, project_id: int, sort: str, limit: int, offset: int) -> Dict[str, Any]:
    with _factory()() as session:
        _project(session, project_id)
        column = getattr(model, sort)
        order = asc(column) if sort == "position" else desc(column)
        query = select(model).where(model.project_id == project_id).order_by(order, model.id)
        total = session.scalar(select(func.count()).select_from(model).where(model.project_id == project_id))
        items = session.scalars(query.offset(offset).limit(limit)).all()
        return {"total": total, "items": [{"key": getattr(r, key_column), "clicks": r.clicks, "impressions": r.impressions,
                                           "ctr": r.ctr, "position": r.position} for r in items]}


@router.get("/projects/{project_id}/gsc/pages")
def gsc_pages(project_id: int, sort: Sort = "clicks", limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return _listing(GscPage, "url", project_id, sort, limit, offset)


@router.get("/projects/{project_id}/gsc/queries")
def gsc_queries(project_id: int, sort: Sort = "clicks", limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return _listing(GscQuery, "query", project_id, sort, limit, offset)


@router.post("/projects/{project_id}/gsc/sync")
def gsc_sync(project_id: int):
    provider = build_gsc_provider()
    if provider is None:
        raise HTTPException(status_code=409, detail="Search Console is not configured (set GSC_SERVICE_ACCOUNT_FILE)")
    with _factory()() as session:
        _project(session, project_id)
    return sync_project(project_id, provider)


_INSPECTION_FIELDS = ("url", "verdict", "coverage_state", "indexing_state", "robots_state", "fetch_state",
                      "google_canonical", "user_canonical", "last_crawl", "error")


@router.get("/audits/{audit_id}/gsc")
def audit_gsc(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        summary = audit.summary_json or {}
        inspections = session.scalars(select(GscInspection).where(GscInspection.audit_id == audit_id)
                                      .order_by(GscInspection.id)).all()
        verdicts = {normalize_url(i.url): i.verdict for i in inspections}
        crawled = {normalize_url(u) for u in session.scalars(select(AuditPage.url).where(AuditPage.audit_id == audit_id))}
        gsc_rows = session.scalars(select(GscPage).where(GscPage.project_id == audit.project_id)).all()
        joined: List[Dict[str, Any]] = []
        not_crawled: List[Dict[str, Any]] = []
        for row in gsc_rows:
            key = normalize_url(row.url)
            if key in crawled:
                joined.append({"url": row.url, "clicks": row.clicks, "impressions": row.impressions, "ctr": row.ctr,
                               "position": row.position, "inspection_verdict": verdicts.get(key)})
            elif row.impressions > 0:
                not_crawled.append({"url": row.url, "clicks": row.clicks, "impressions": row.impressions})
        joined.sort(key=lambda r: (-r["clicks"], r["url"]))
        not_crawled.sort(key=lambda r: (-r["impressions"], r["url"]))
        return {"audit_id": audit_id, "status": summary.get("gsc_status") or "disabled",
                "property": summary.get("gsc_property"), "dry_run": bool(summary.get("gsc_dry_run")),
                "inspections": [{f: getattr(i, f) for f in _INSPECTION_FIELDS} for i in inspections],
                "pages": joined[:200], "not_crawled": not_crawled[:50]}
```

In `app/main.py`, after the rules router lines:

```python
from app.api.gsc import router as gsc_router  # noqa: E402
app.include_router(gsc_router, prefix="/api")
```

The spec said `/gsc/sites` returns 503 on a Google error. It's 502 here, matching the other upstream-provider errors (DataForSEO). Note this in the docs.

- [ ] **Step 4: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_gsc_api.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/api/gsc.py apps/backend/app/main.py apps/backend/tests/test_gsc_api.py
git commit -m "feat(gsc): Search Console API (overview + KPIs, pages, queries, sync, audit join)"
```

---

### Task 6: Frontend

**Files:**
- Modify:
  - `packages/shared/src/types/platform.ts`
  - `apps/frontend/services/platform.ts`
  - `components/platform/project-tabs.tsx`
  - `app/projects/[id]/audits/page.tsx`
  - `app/dashboard/page.tsx`
  - `components/__tests__/site-audit-page.test.tsx`
- Create:
  - `apps/frontend/lib/gsc.ts` (+ `lib/__tests__/gsc.test.ts`)
  - Modify `components/platform/dry-run-banner.tsx` (optional `message`)
  - `components/platform/gsc-trend-chart.tsx`
  - `components/platform/gsc-table.tsx`
  - `components/platform/gsc-audit-section.tsx`
  - `app/projects/[id]/search-console/page.tsx`
  - `components/__tests__/search-console-page.test.tsx`

**Interfaces:**
- Produces:
  - Types `GscKpis, GscDailyPoint, GscOverview, GscRow, GscList, GscSyncResult, GscSites, GscInspectionRow, AuditGsc`
  - `Platform.gscSites()`, `gscOverview(id)`, `gscPages(id, sort, offset)`, `gscQueries(id, sort, offset)`, `gscSync(id)`, `auditGsc(auditId)`
  - `ProjectSummary.gsc_property`, `last_gsc_sync_at`
  - `updateProject` accepts `gsc_property`

- [ ] **Step 1: Types, service and helpers**

Append to `packages/shared/src/types/platform.ts`:

```ts
// Google Search Console (backend Phase 5.5).
export interface GscKpis { clicks: number; impressions: number; ctr: number | null; position: number | null }
export interface GscDailyPoint { date: string; clicks: number; impressions: number; ctr: number; position: number }
export interface GscOverview {
  configured: boolean; dry_run: boolean; client_email: string | null; property: string | null;
  last_sync_at: string | null; kpis: GscKpis | null; previous_kpis: GscKpis | null; daily: GscDailyPoint[];
}
export interface GscRow { key: string; clicks: number; impressions: number; ctr: number; position: number }
export interface GscList { total: number; items: GscRow[] }
export type GscSort = "clicks" | "impressions" | "ctr" | "position";
export interface GscSyncResult {
  status: "synced" | "no_access" | "error"; property: string | null; message?: string; client_email?: string | null;
  days?: number; pages?: number; queries?: number; dry_run: boolean;
}
export interface GscSites { configured: boolean; dry_run: boolean; client_email: string | null; sites: { site_url: string; permission: string }[] }
export interface GscInspectionRow {
  url: string; verdict: string | null; coverage_state: string | null; indexing_state: string | null; robots_state: string | null;
  fetch_state: string | null; google_canonical: string | null; user_canonical: string | null; last_crawl: string | null; error: string | null;
}
export interface AuditGsc {
  audit_id: number; status: "inspected" | "disabled" | "not_configured" | "no_property" | "error";
  property: string | null; dry_run: boolean; inspections: GscInspectionRow[];
  pages: { url: string; clicks: number; impressions: number; ctr: number; position: number; inspection_verdict: string | null }[];
  not_crawled: { url: string; clicks: number; impressions: number }[];
}
```

In `ProjectSummary`, add `gsc_property?: string | null; last_gsc_sync_at?: string | null;`.

In `apps/frontend/services/platform.ts`:
- Import `AuditGsc, GscList, GscOverview, GscSites, GscSort, GscSyncResult`.
- Widen `updateProject`'s body type with `gsc_property: string`.
- Add:

```ts
  gscSites: () => request<GscSites>("/gsc/sites"),
  gscOverview: (id: number) => request<GscOverview>(`/projects/${id}/gsc`),
  gscPages: (id: number, sort: GscSort = "clicks", offset = 0) => request<GscList>(`/projects/${id}/gsc/pages?sort=${sort}&offset=${offset}&limit=50`),
  gscQueries: (id: number, sort: GscSort = "clicks", offset = 0) => request<GscList>(`/projects/${id}/gsc/queries?sort=${sort}&offset=${offset}&limit=50`),
  gscSync: (id: number) => request<GscSyncResult>(`/projects/${id}/gsc/sync`, post()),
  auditGsc: (auditId: number) => request<AuditGsc>(`/audits/${auditId}/gsc`),
```

`apps/frontend/lib/gsc.ts`:

```ts
import type { GscDailyPoint } from "@seo-auditor/shared";

export const formatCount = (n: number | null | undefined) => (n == null ? "—" : Math.round(n).toLocaleString("en-US"));
export const formatCtr = (ctr: number | null | undefined) => (ctr == null ? "—" : `${(ctr * 100).toFixed(1)}%`);
export const formatPosition = (p: number | null | undefined) => (p == null ? "—" : p.toFixed(1));

/** new − old, rounded for display; null when either side is missing. */
export function change(now: number | null | undefined, before: number | null | undefined, digits = 0): number | null {
  if (now == null || before == null) return null;
  const f = 10 ** digits;
  return Math.round((now - before) * f) / f;
}

export function trendData(daily: GscDailyPoint[]) {
  return daily.map((d) => ({ label: new Date(`${d.date}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }),
                             clicks: d.clicks, impressions: d.impressions }));
}
```

`lib/__tests__/gsc.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { change, formatCount, formatCtr, formatPosition, trendData } from "@/lib/gsc";

describe("gsc helpers", () => {
  it("formats numbers for people", () => {
    expect(formatCount(1234.4)).toBe("1,234");
    expect(formatCtr(0.0345)).toBe("3.5%");
    expect(formatPosition(7.26)).toBe("7.3");
    expect(formatCtr(null)).toBe("—");
  });
  it("computes changes", () => {
    expect(change(560, 280)).toBe(280);
    expect(change(5, 10, 1)).toBe(-5);
    expect(change(null, 3)).toBeNull();
  });
  it("labels the trend by UTC day", () => {
    expect(trendData([{ date: "2026-10-01", clicks: 3, impressions: 40, ctr: 0.075, position: 8 }])).toEqual([
      { label: "Oct 1", clicks: 3, impressions: 40 }]);
  });
});
```

Rebuild shared: `cd packages/shared && npx tsc`.

- [ ] **Step 2: Write the failing page test** (`components/__tests__/search-console-page.test.tsx`)

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SearchConsolePage from "@/app/projects/[id]/search-console/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/search-console" }));

const overview = (over: object = {}) => ({
  configured: true, dry_run: false, client_email: "sa@proj.iam.gserviceaccount.com", property: "sc-domain:shop.com",
  last_sync_at: "2026-10-29T06:00:00+00:00",
  kpis: { clicks: 560, impressions: 2800, ctr: 0.2, position: 5 },
  previous_kpis: { clicks: 280, impressions: 2800, ctr: 0.1, position: 10 },
  daily: [{ date: "2026-10-01", clicks: 20, impressions: 100, ctr: 0.2, position: 5 }],
  ...over,
});
const list = { total: 1, items: [{ key: "https://shop.com/", clicks: 50, impressions: 900, ctr: 0.055, position: 3 }] };

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "gscPages").mockResolvedValue(list);
  vi.spyOn(Platform, "gscQueries").mockResolvedValue({ total: 1, items: [{ key: "buy books", clicks: 30, impressions: 500, ctr: 0.06, position: 4 }] });
  vi.spyOn(Platform, "gscSites").mockResolvedValue({ configured: true, dry_run: false, client_email: "sa@proj.iam.gserviceaccount.com",
    sites: [{ site_url: "sc-domain:shop.com", permission: "siteOwner" }] });
});

describe("Search Console tab", () => {
  it("explains setup when not configured", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ configured: false, property: null, kpis: null, previous_kpis: null, daily: [] }) as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByText(/GSC_SERVICE_ACCOUNT_FILE/)).toBeInTheDocument();
  });

  it("asks to add the service account when no property is set", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ property: null, kpis: null, previous_kpis: null, daily: [] }) as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByText(/sa@proj.iam.gserviceaccount.com/)).toBeInTheDocument();
  });

  it("shows KPIs with changes (position: lower is better)", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview() as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByText("560")).toBeInTheDocument();
    expect(screen.getByText("20.0%")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 280")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 5")).toBeInTheDocument();   // position 10 → 5
    expect(await screen.findByText("buy books")).toBeInTheDocument();
  });

  it("shows the preview banner in dry run", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ dry_run: true }) as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    expect(await screen.findByRole("note")).toBeInTheDocument();
  });

  it("syncs on demand and re-sorts tables", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview() as any);
    const sync = vi.spyOn(Platform, "gscSync").mockResolvedValue({ status: "synced", property: "sc-domain:shop.com", days: 90, pages: 10, queries: 10, dry_run: false });
    render(<SearchConsolePage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /sync now/i }));
    expect(sync).toHaveBeenCalledWith(7);
    expect(await screen.findByText(/synced 90 days, 10 pages, 10 queries/i)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /^impressions$/i })[0]);
    await waitFor(() => expect(Platform.gscPages).toHaveBeenLastCalledWith(7, "impressions", 0));
  });

  it("charts have a table view", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview() as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    const toggles = await screen.findAllByRole("button", { name: /show as table/i });
    await userEvent.click(toggles[0]);
    expect(screen.getByRole("cell", { name: "Oct 1" })).toBeInTheDocument();
  });

  it("lets you pick the property", async () => {
    vi.spyOn(Platform, "gscOverview").mockResolvedValue(overview({ property: null, kpis: null, previous_kpis: null, daily: [] }) as any);
    const update = vi.spyOn(Platform, "updateProject").mockResolvedValue({} as any);
    render(<SearchConsolePage params={{ id: "7" }} />);
    await userEvent.selectOptions(await screen.findByLabelText(/property/i), "sc-domain:shop.com");
    expect(update).toHaveBeenCalledWith(7, { gsc_property: "sc-domain:shop.com" });
  });
});
```

In `components/__tests__/site-audit-page.test.tsx`:
- In `beforeEach`, add `vi.spyOn(Platform, "auditGsc").mockResolvedValue({ audit_id: 3, status: "not_configured", property: null, dry_run: false, inspections: [], pages: [], not_crawled: [] });`.
- Add this test:

```tsx
  it("shows Search Console for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/Search Console isn't connected/)).toBeInTheDocument();
    expect(Platform.auditGsc).toHaveBeenCalledWith(3);
  });
```

- [ ] **Step 3: Run and watch them fail**

Run: `cd apps/frontend && npx vitest run lib/__tests__/gsc.test.ts components/__tests__/search-console-page.test.tsx components/__tests__/site-audit-page.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Components**

`components/platform/gsc-trend-chart.tsx` (one measure per chart, never a dual axis):

```tsx
"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatCount } from "@/lib/gsc";
import { SERIES_LIGHT } from "@/lib/platform-charts";

export function GscTrendChart({ title, data, dataKey }: {
  title: string; data: { label: string; clicks: number; impressions: number }[]; dataKey: "clicks" | "impressions";
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="rounded-[18px] border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        <button type="button" onClick={() => setAsTable((v) => !v)} className="rounded-full border px-3 py-1 text-xs active:scale-95">
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-[13px]">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Day</th><th className="py-1">{title}</th></tr></thead>
            <tbody>{data.map((d) => <tr key={d.label}><td className="py-1">{d.label}</td><td className="py-1 tabular-nums">{formatCount(d[dataKey])}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="h-48 w-full" role="img" aria-label={`${title} per day`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Line type="monotone" dataKey={dataKey} name={title} stroke={SERIES_LIGHT[0]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
```

`components/platform/gsc-table.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { GscSort } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { formatCount, formatCtr, formatPosition } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

const COLUMNS: { key: GscSort; label: string }[] = [
  { key: "clicks", label: "Clicks" }, { key: "impressions", label: "Impressions" },
  { key: "ctr", label: "CTR" }, { key: "position", label: "Position" },
];

export function GscTable({ projectId, kind }: { projectId: number; kind: "pages" | "queries" }) {
  const [sort, setSort] = useState<GscSort>("clicks");
  const [offset, setOffset] = useState(0);
  const fetcher = kind === "pages" ? Platform.gscPages : Platform.gscQueries;
  const state = useApi(() => fetcher(projectId, sort, offset), [projectId, kind, sort, offset]);
  return (
    <section className="rounded-[18px] border bg-card p-5">
      <h2 className="mb-3 font-semibold tracking-tight">{kind === "pages" ? "Top pages" : "Top queries"} <span className="text-xs font-normal text-muted-foreground">(28 days)</span></h2>
      <AsyncState state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No data yet" emptyText="Run a sync to load Search Console data.">
        {(d) => (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[13px]">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="sticky left-0 bg-card py-2 pr-4 font-medium">{kind === "pages" ? "Page" : "Query"}</th>
                    {COLUMNS.map((c) => (
                      <th key={c.key} className="py-2 pr-4 font-medium">
                        <button type="button" onClick={() => { setSort(c.key); setOffset(0); }}
                                aria-pressed={sort === c.key} className={sort === c.key ? "text-foreground underline" : "hover:text-foreground"}>{c.label}</button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {d.items.map((r) => (
                    <tr key={r.key}>
                      <td className="sticky left-0 max-w-[160px] break-all bg-card py-2 pr-4 sm:max-w-[360px]">{r.key}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatCount(r.clicks)}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatCount(r.impressions)}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatCtr(r.ctr)}</td>
                      <td className="py-2 pr-4 tabular-nums">{formatPosition(r.position)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.total > 50 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))} className="rounded-full border px-3 py-1 disabled:opacity-50">Previous</button>
                <span>{offset + 1}–{Math.min(offset + 50, d.total)} of {d.total}</span>
                <button type="button" disabled={offset + 50 >= d.total} onClick={() => setOffset(offset + 50)} className="rounded-full border px-3 py-1 disabled:opacity-50">Next</button>
              </div>
            )}
          </>
        )}
      </AsyncState>
    </section>
  );
}
```

`components/platform/gsc-audit-section.tsx`:

```tsx
import { CheckCircle2, XCircle } from "lucide-react";
import type { AuditGsc } from "@seo-auditor/shared";

import { formatCount, formatPosition } from "@/lib/gsc";

function IndexPill({ verdict }: { verdict: string | null }) {
  if (verdict === "PASS") return <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400"><CheckCircle2 className="h-3 w-3" aria-hidden />Indexed</span>;
  if (!verdict) return <span className="text-muted-foreground">—</span>;
  return <span className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400"><XCircle className="h-3 w-3" aria-hidden />Not indexed</span>;
}

const MESSAGES: Record<string, string> = {
  disabled: "Search Console inspection was turned off for this audit.",
  not_configured: "Search Console isn't connected. Set it up in the project's Search Console tab.",
  no_property: "No Search Console property for this site yet. Pick one in the Search Console tab.",
  error: "Search Console couldn't be reached during this audit.",
};

export function GscAuditSection({ data }: { data: AuditGsc }) {
  if (data.status !== "inspected") return <p className="text-sm text-muted-foreground">{MESSAGES[data.status] ?? MESSAGES.error}</p>;
  return (
    <div className="space-y-5">
      {data.dry_run && <p className="text-xs text-amber-800 dark:text-amber-400">Preview data — Search Console is in dry-run mode.</p>}
      <div>
        <h3 className="mb-2 text-sm font-semibold">Index status</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-[13px]">
            <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
              <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th><th className="py-2 pr-4 font-medium">Google</th>
              <th className="py-2 pr-4 font-medium">Reason</th><th className="py-2 font-medium">Last crawl</th></tr></thead>
            <tbody className="divide-y">
              {data.inspections.map((i) => (
                <tr key={i.url} className="align-top">
                  <td className="sticky left-0 max-w-[140px] break-all bg-card py-2 pr-4 sm:max-w-[300px]">{i.url}</td>
                  <td className="py-2 pr-4">{i.error ? <span className="text-muted-foreground">Couldn&apos;t inspect: {i.error}</span> : <IndexPill verdict={i.verdict} />}</td>
                  <td className="py-2 pr-4 text-muted-foreground">
                    {i.coverage_state ?? "—"}
                    {i.google_canonical && i.user_canonical && i.google_canonical !== i.user_canonical && (
                      <p className="break-all text-xs">Google&apos;s canonical: {i.google_canonical}</p>)}
                  </td>
                  <td className="whitespace-nowrap py-2 text-muted-foreground">{i.last_crawl ? new Date(i.last_crawl).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Crawled pages by clicks <span className="font-normal text-muted-foreground">(28 days)</span></h3>
          {data.pages.length === 0 ? <p className="text-sm text-muted-foreground">No Search Console data for the crawled pages yet.</p> : (
            <ul className="divide-y text-[13px]">{data.pages.slice(0, 20).map((p) => (
              <li key={p.url} className="flex items-start justify-between gap-3 py-1.5">
                <span className="min-w-0 break-all">{p.url}</span>
                <span className="whitespace-nowrap tabular-nums text-muted-foreground">{formatCount(p.clicks)} clicks · pos {formatPosition(p.position)}</span>
              </li>))}</ul>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Pages Google shows that the crawl didn&apos;t reach</h3>
          {data.not_crawled.length === 0 ? <p className="text-sm text-muted-foreground">None. Every page with impressions was crawled.</p> : (
            <ul className="divide-y text-[13px]">{data.not_crawled.slice(0, 20).map((p) => (
              <li key={p.url} className="flex items-start justify-between gap-3 py-1.5">
                <span className="min-w-0 break-all">{p.url}</span>
                <span className="whitespace-nowrap tabular-nums text-muted-foreground">{formatCount(p.impressions)} impr.</span>
              </li>))}</ul>
          )}
        </div>
      </div>
    </div>
  );
}
```

`app/projects/[id]/search-console/page.tsx`:

```tsx
"use client";

import { useState } from "react";

import { AsyncState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { GscTable } from "@/components/platform/gsc-table";
import { GscTrendChart } from "@/components/platform/gsc-trend-chart";
import { KpiTile } from "@/components/platform/kpi-tile";
import { PageHeader } from "@/components/platform/page-header";
import { change, formatCount, formatCtr, formatPosition, trendData } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function SearchConsolePage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const overview = useApi(() => Platform.gscOverview(projectId), [projectId]);
  const sites = useApi(overview.data?.configured ? () => Platform.gscSites() : null, [overview.data?.configured]);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const sync = async () => {
    setSyncing(true); setSyncMessage(null);
    try {
      const r = await Platform.gscSync(projectId);
      setSyncMessage(r.status === "synced" ? `Synced ${r.days} days, ${r.pages} pages, ${r.queries} queries.`
        : r.status === "no_access" ? `No access yet: add ${r.client_email} as a user on this site's Search Console property.`
        : `Sync failed: ${r.message}`);
      overview.reload();
    } catch (e) {
      setSyncMessage(e instanceof ApiError ? e.detail : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const pickProperty = async (value: string) => {
    await Platform.updateProject(projectId, { gsc_property: value });
    overview.reload();
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Search Console" description="How Google sees this site: clicks, impressions and positions, from Google Search Console." />
      <AsyncState state={overview}>
        {(o) => !o.configured ? (
          <section className="space-y-2 rounded-[18px] border bg-card p-5 text-sm">
            <h2 className="font-semibold tracking-tight">Connect Search Console</h2>
            <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
              <li>In Google Cloud, create a service account and enable the "Google Search Console API".</li>
              <li>Create a JSON key for it and put the file on the backend server.</li>
              <li>Set <code className="rounded bg-muted px-1">GSC_SERVICE_ACCOUNT_FILE</code> to that file's path and restart the backend.</li>
              <li>In Search Console → Settings → Users and permissions, add the service account's email as a user.</li>
            </ol>
          </section>
        ) : (
          <div className="space-y-6">
            <DryRunBanner show={o.dry_run} message="Preview data. Search Console is in dry-run mode, so these numbers are made up." />
            <section className="flex flex-wrap items-end gap-4 rounded-[18px] border bg-card p-5 text-sm">
              <label className="space-y-1 text-xs font-medium text-muted-foreground">Property
                <select aria-label="Property" className="block h-9 min-w-[220px] rounded-lg border bg-background px-3 text-sm"
                        value={o.property ?? ""} onChange={(e) => pickProperty(e.target.value)}>
                  <option value="">{o.property ? "" : "Choose…"}</option>
                  {(sites.data?.sites ?? []).map((s) => <option key={s.site_url} value={s.site_url}>{s.site_url}</option>)}
                  {o.property && !(sites.data?.sites ?? []).some((s) => s.site_url === o.property) && <option value={o.property}>{o.property}</option>}
                </select>
              </label>
              <div className="text-xs text-muted-foreground">Last sync: {o.last_sync_at ? new Date(o.last_sync_at).toLocaleString() : "never"}</div>
              <button type="button" onClick={sync} disabled={syncing} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
                {syncing ? "Syncing…" : "Sync now"}
              </button>
              {!o.property && <p className="w-full text-muted-foreground">Add <strong>{o.client_email}</strong> as a user on this site&apos;s Search Console property, then pick it here or sync.</p>}
              {syncMessage && <p className="w-full text-muted-foreground">{syncMessage}</p>}
            </section>
            {o.kpis && (
              <>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <KpiTile label="Clicks (28 days)" value={formatCount(o.kpis.clicks)} delta={<DeltaBadge value={change(o.kpis.clicks, o.previous_kpis?.clicks)} />} />
                  <KpiTile label="Impressions" value={formatCount(o.kpis.impressions)} delta={<DeltaBadge value={change(o.kpis.impressions, o.previous_kpis?.impressions)} />} />
                  <KpiTile label="CTR" value={formatCtr(o.kpis.ctr)} />
                  <KpiTile label="Avg. position" value={formatPosition(o.kpis.position)}
                           delta={<DeltaBadge value={change(o.kpis.position, o.previous_kpis?.position, 1)} lowerIsBetter />} />
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  <GscTrendChart title="Clicks" data={trendData(o.daily)} dataKey="clicks" />
                  <GscTrendChart title="Impressions" data={trendData(o.daily)} dataKey="impressions" />
                </div>
              </>
            )}
            <div className="grid gap-4 xl:grid-cols-2">
              <GscTable projectId={projectId} kind="pages" />
              <GscTable projectId={projectId} kind="queries" />
            </div>
          </div>
        )}
      </AsyncState>
    </div>
  );
}
```

`DryRunBanner` takes `show` and hard-codes the DataForSEO text. Give it an optional `message` prop that defaults to the current text, so existing uses are unchanged:

```tsx
export function DryRunBanner({ show, message = "Preview data. DataForSEO is not live, so these numbers are made up." }: { show: boolean; message?: string }) {
```

and render `{message}` in place of the literal sentence.

Wiring:
- `components/platform/project-tabs.tsx`: add `{ suffix: "/search-console", label: "Search Console" },` before Custom Rules.
- `app/projects/[id]/audits/page.tsx`:
  - import `GscAuditSection`
  - add `const gsc = useApi(selected !== null ? () => Platform.auditGsc(selected) : null, [selected]);`
  - add a section after "Custom rules": `<section className="rounded-[18px] border bg-card p-5"><h2 className="mb-3 font-semibold tracking-tight">Search Console</h2><AsyncState state={gsc}>{(g) => <GscAuditSection data={g} />}</AsyncState></section>`
- `components/platform/gsc-report-panel.tsx` (the report needs its own fetch, because `/api/audit/latest` carries only the summary):

```tsx
"use client";

import { AsyncState } from "@/components/platform/async-state";
import { GscAuditSection } from "@/components/platform/gsc-audit-section";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export function GscReportPanel({ auditId }: { auditId: number }) {
  const gsc = useApi(() => Platform.auditGsc(auditId), [auditId]);
  return (
    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-base">Search Console</CardTitle></CardHeader>
      <CardContent><AsyncState state={gsc}>{(g) => <GscAuditSection data={g} />}</AsyncState></CardContent>
    </Card>
  );
}
```

- `app/dashboard/page.tsx`:
  - import `GscReportPanel`
  - add `{ id: "search-console", width: "full", visible: true },` to `DEFAULT_LAYOUT` after `accessibility`
  - add the widget below:

```tsx
    "search-console": auditData.gsc_status && auditData.audit_id ? <GscReportPanel auditId={auditData.audit_id} /> : null,
```

- In `packages/shared/src/types/index.ts`, add `gsc_status?: string | null;` to `AuditResponse` after `axe_version`.

- [ ] **Step 5: Run and pass, gated, then commit**

```bash
npx vitest run > /tmp/fe.txt 2>&1; echo "vitest exit=$?"; grep -E "Tests " /tmp/fe.txt
npx tsc --noEmit; echo "tsc exit=$?"
(cd ../backend && python -m pytest -q > /tmp/t.txt 2>&1; echo "pytest exit=$?")
git add packages/shared/src apps/frontend
git commit -m "feat(frontend): Search Console tab (KPIs, trends, top pages/queries, sync, property) and audit section"
```

---

### Task 7: Docs, env and the dry-run live check

- [ ] **Step 1: Env, compose, docs**

`apps/backend/.env.example`, after `RENDER_TIMEOUT_MS=20000`:

```
# Google Search Console (read-only). Path to a service account's JSON key; add
# the service account's email as a user on each property. Empty = not used.
GSC_SERVICE_ACCOUNT_FILE=
# true = made-up Search Console data, to try the UI without Google.
GSC_DRY_RUN=false
# Hard daily caps (analytics calls, URL inspections) and pages inspected per audit.
GSC_DAILY_CAP=100
GSC_INSPECT_DAILY_CAP=200
GSC_INSPECT_MAX_PAGES=20
```

`deploy/oracle/docker-compose.yml`, backend env (after `RENDER_TIMEOUT_MS`):

```yaml
      GSC_SERVICE_ACCOUNT_FILE: ${GSC_SERVICE_ACCOUNT_FILE:-}
      GSC_DRY_RUN: ${GSC_DRY_RUN:-false}
      GSC_DAILY_CAP: ${GSC_DAILY_CAP:-100}
      GSC_INSPECT_DAILY_CAP: ${GSC_INSPECT_DAILY_CAP:-200}
      GSC_INSPECT_MAX_PAGES: ${GSC_INSPECT_MAX_PAGES:-20}
```

Also note in `docs/deployment-oracle.md` how to mount the key file read-only, e.g. `./secrets/gsc.json:/run/secrets/gsc.json:ro` with `GSC_SERVICE_ACCOUNT_FILE=/run/secrets/gsc.json`.

`docs/env.md`: add rows for the five variables.

`docs/api.md`: append a "Google Search Console" section covering:
- setup (the four steps from the UI)
- the sync (what's fetched, ranges, lag)
- each endpoint, with a short example (the KPI and audit-join JSON from Task 5's tests)
- the issue codes
- errors (409 not configured; 502 from Google on `/gsc/sites`; sync statuses)

`README.md`: append a "Google Search Console (Phase 5.5)" section with what it does, the setup steps and a **How to verify (no Google account needed)** block:

```bash
cd apps/backend
python -m pytest tests/test_gsc_provider.py tests/test_gsc_storage.py tests/test_gsc_sync.py tests/test_gsc_audit.py tests/test_gsc_api.py -q
export SESSION_DIR=/tmp/seo-gsc GSC_DRY_RUN=true
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links --json \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['gsc_status'], d['gsc_property'], [(i['url'], i['verdict']) for i in d['gsc_inspections']][:3])"
python -m uvicorn app.main:app --port 5000 &
curl -s -X POST localhost:5000/api/projects/1/gsc/sync
curl -s localhost:5000/api/projects/1/gsc | python -c "import sys,json; d=json.load(sys.stdin); print(d['dry_run'], d['kpis'])"
```

Commit the docs (with the suite gated).

- [ ] **Step 2: Live check (dry run only)**

1. Run the README block. Expect `inspected sc-domain:books.toscrape.com`, a sync with `"status": "synced"` and `dry_run: true`, and KPIs.
2. Run a second audit after the sync. `/api/audits/2/gsc` should list crawled pages with clicks, and `not_crawled` URLs (the dry run's made-up catalogue pages aren't on the crawled list).
3. Start `next dev`. Screenshot at 1440 and 390 px (Playwright if the Chrome extension isn't connected):
   - the Search Console tab: banner, KPIs, both charts and table toggles, tables, sort, Sync now
   - the Site Audit section
   - the report panel
   - no sideways page scroll
4. Fix anything found (with a test when it's behaviour), commit, and stop the servers.
5. Report: real Google calls need the owner's key, and the owner's go-ahead before the first one.
