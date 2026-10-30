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
