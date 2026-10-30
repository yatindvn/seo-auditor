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
