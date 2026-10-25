"""Comparing two runs of a project: what broke, what got fixed, what moved."""

from datetime import timedelta

import pytest

from app.db.diff import diff_audits, previous_audit_id
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditIssue, AuditPage, Project, utcnow


def _audit(s, project, session_id, pages, issues, score, minutes):
    audit = Audit(project_id=project.id, session_id=session_id, start_url="https://example.com/",
                  status="completed", trigger="manual",
                  started_at=utcnow() + timedelta(minutes=minutes),
                  finished_at=utcnow() + timedelta(minutes=minutes),
                  page_count=len(pages), health_score=score, summary_json={})
    s.add(audit)
    s.flush()
    for url, status in pages.items():
        s.add(AuditPage(audit_id=audit.id, url=url, status=status, issue_count=0))
    for url, code in issues:
        s.add(AuditIssue(audit_id=audit.id, url=url, code=code, severity="warning", message=code))
    s.flush()
    return audit.id


@pytest.fixture
def two_runs():
    factory = get_session_factory()
    with factory.begin() as s:
        project = Project(name="example.com", domain="example.com", audit_options_json={})
        other = Project(name="other.org", domain="other.org", audit_options_json={})
        s.add_all([project, other])
        s.flush()
        old = _audit(s, project, "old",
                     {"/a": 200, "/b": 200, "/gone": 200},
                     [("/a", "MISSING_H1"), ("/b", "THIN_CONTENT"), ("/b", "MISSING_ALT")],
                     score=60.0, minutes=0)
        new = _audit(s, project, "new",
                     {"/a": 200, "/b": 404, "/fresh": 200},
                     [("/a", "MISSING_H1"), ("/b", "STATUS_404"), ("/fresh", "MISSING_ALT")],
                     score=55.5, minutes=10)
        foreign = _audit(s, other, "foreign", {"/x": 200}, [], score=90.0, minutes=5)
    return factory, old, new, foreign


def test_new_fixed_and_persisting_issues(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        diff = diff_audits(s, old, new)

    assert {(i["url"], i["code"]) for i in diff["issues"]["new"]} == {("/b", "STATUS_404"), ("/fresh", "MISSING_ALT")}
    assert {(i["url"], i["code"]) for i in diff["issues"]["fixed"]} == {("/b", "THIN_CONTENT"), ("/b", "MISSING_ALT")}
    assert diff["issues"]["persisting_count"] == 1
    assert diff["health_score_change"] == pytest.approx(-4.5)


def test_page_changes(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        pages = diff_audits(s, old, new)["pages"]

    assert pages["added"] == ["/fresh"]
    assert pages["removed"] == ["/gone"]
    assert pages["status_changed"] == [{"url": "/b", "old_status": 200, "new_status": 404}]


def test_lists_truncate_but_counts_stay_exact(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        diff = diff_audits(s, old, new, limit=1)

    assert len(diff["issues"]["new"]) == 1 and diff["issues"]["new_count"] == 2


def test_audits_of_different_projects_cannot_be_diffed(two_runs):
    factory, old, _, foreign = two_runs
    with factory() as s, pytest.raises(ValueError):
        diff_audits(s, old, foreign)


def test_unknown_audit_is_a_lookup_error(two_runs):
    factory, old, _, _ = two_runs
    with factory() as s, pytest.raises(LookupError):
        diff_audits(s, old, 999_999)


def test_previous_audit_is_the_latest_earlier_one_in_the_project(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        assert previous_audit_id(s, new) == old
        assert previous_audit_id(s, old) is None
