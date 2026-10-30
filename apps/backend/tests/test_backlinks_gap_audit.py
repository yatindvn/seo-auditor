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
