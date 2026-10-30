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
