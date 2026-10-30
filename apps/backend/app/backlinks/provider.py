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
SUMMARY = "/v3/backlinks/summary/live"
REFERRING_DOMAINS = "/v3/backlinks/referring_domains/live"
BACKLINKS = "/v3/backlinks/backlinks/live"
HISTORY = "/v3/backlinks/history/live"
INTERSECTION = "/v3/backlinks/domain_intersection/live"


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
