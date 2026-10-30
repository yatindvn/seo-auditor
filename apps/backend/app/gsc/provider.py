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
