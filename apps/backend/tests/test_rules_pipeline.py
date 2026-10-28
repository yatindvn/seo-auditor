"""Custom rules in an audit: loaded for the project, evaluated in the page
workers, counted in the summary, and part of the page-cache fingerprint."""

from app.db.engine import get_session_factory
from app.db.models import CustomRule, Project
from app.models import page_cache
from app.services import audit_service, page_pipeline

from test_audit_service_crawler_registry import FakeCrawler


def _rules(*checks):
    with get_session_factory().begin() as s:
        project = Project(name="example.com", domain="example.com"); s.add(project); s.flush()
        for i, (check, severity, pattern) in enumerate(checks):
            s.add(CustomRule(project_id=project.id, name=f"rule {i}", severity=severity, message="msg",
                             url_pattern=pattern, check_json=check))


def _run():
    return audit_service._build_audit_result("https://example.com/", FakeCrawler(),
                                             progress_callback=None, event_callback=None)


def test_failed_rules_are_issues_with_their_severity_and_a_summary():
    _rules(({"type": "field", "field": "word_count", "op": "gte", "value": 500}, "critical", None),
           ({"type": "text", "scope": "visible", "op": "contains", "value": "espresso"}, "warning", None),
           ({"type": "field", "field": "status", "op": "eq", "value": 404}, "info", None),
           ({"type": "selector", "selector": "h1", "op": "not_exists"}, "warning", "/blog/*"))
    result = _run()
    issues = [i for i in result["page_issues_detail"]["https://example.com/"] if i.get("source") == "custom"]
    assert sorted((i["severity"], i["message"]) for i in issues) == [
        ("critical", "rule 0: msg"), ("info", "rule 2: msg")]
    summary = {s["name"]: s for s in result["custom_rules"]}
    assert summary["rule 0"]["pages_failed"] == 1 and summary["rule 0"]["pages_checked"] == 1
    assert summary["rule 1"]["pages_failed"] == 0 and summary["rule 1"]["pages_checked"] == 1
    assert summary["rule 2"]["pages_checked"] == 1
    assert summary["rule 3"]["pages_checked"] == 0          # scoped to /blog/*
    assert result["executive_summary"]["health_score"]["critical_issues"] >= 1


def test_no_project_no_rules():
    result = _run()
    assert result["custom_rules"] == []


def test_the_fingerprint_follows_the_rules():
    base = page_cache.analyzer_fingerprint(True, None, False)
    assert page_cache.analyzer_fingerprint(True, None, False, rules_digest="") == base
    assert page_cache.analyzer_fingerprint(True, None, False, rules_digest="abc") != base


def test_workers_get_the_rules_in_the_payload():
    payload = page_pipeline.PagePayload(
        url="https://example.com/", final_url="https://example.com/", status_code=200, headers={},
        html="<html><head><title>T</title></head><body><h1>x</h1></body></html>",
        custom_rules=[{"id": 4, "name": "n", "severity": "warning", "message": "", "url_pattern": None,
                       "check": {"type": "selector", "selector": "h1", "op": "not_exists"}}])
    analysis = page_pipeline.analyze_page(payload)
    assert [i["code"] for i in analysis.issues if i.get("source") == "custom"] == ["CUSTOM_4"]
    assert analysis.meta["custom_rules_checked"] == [4]
