"""Accessibility inside an audit: opt-in, shares the browser pass, damped
issues, stored, never fatal."""

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import AccessibilityScan
from app.rendering.model import RenderResult
from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler

AXE = {"violations": [
    {"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds",
     "helpUrl": "https://dequeuniversity.com/rules/axe/4.14/color-contrast", "tags": ["wcag2aa"],
     "nodes": [{"target": ["#a"]}, {"target": ["#b"]}]},
    {"id": "image-alt", "impact": "critical", "help": "Images must have alternative text",
     "helpUrl": "https://dequeuniversity.com/rules/axe/4.14/image-alt", "tags": ["wcag2a"], "nodes": [{"target": ["img"]}]},
]}


class FakeRenderer:
    name = "fake"

    def __init__(self, axe=AXE):
        self.calls, self.axe = [], axe

    def render(self, urls, on_progress=None, run_axe=False):
        self.calls.append((list(urls), run_axe))
        out = []
        for i, url in enumerate(urls, 1):
            out.append(RenderResult(url=url, html="<html><head><title>Espresso Machines</title></head><body></body></html>",
                                    final_url=url, status=200, render_ms=5, axe=self.axe if run_axe else None))
            if on_progress:
                on_progress(i, len(urls), url)
        return out


def _run(**kwargs):
    events = []
    result = audit_service._build_audit_result(
        "https://example.com/", FakeCrawler(), progress_callback=None,
        event_callback=lambda kind, payload: events.append((kind, payload)), **kwargs)
    return result, events


def test_off_by_default():
    result, _ = _run()
    assert result["accessibility_status"] == "disabled" and result["accessibility"] == []
    assert result["axe_version"] is None


def test_scans_scores_and_adds_damped_issues():
    renderer = FakeRenderer()
    result, events = _run(accessibility=True, renderer=renderer)
    assert renderer.calls == [(["https://example.com/"], True)]
    assert result["accessibility_status"] == "scanned" and result["axe_version"] == "4.14.0"
    row = result["accessibility"][0]
    assert row["score"] == 100 - 7 - 10 and row["counts"]["critical"] == 1
    issues = {i["code"]: i for i in result["page_issues_detail"]["https://example.com/"]}
    assert issues["A11Y_COLOR_CONTRAST"]["severity"] == "warning"
    assert "A11Y_IMAGE_ALT" not in issues
    assert result["render_status"] == "disabled" and result["rendering"] == []
    assert ("rendering", {"done": 1, "total": 1, "url": "https://example.com/", "kind": "a11y"}) in events
    with get_session_factory()() as session:
        rows = session.scalars(select(AccessibilityScan).where(AccessibilityScan.audit_id == result["audit_id"])).all()
        assert [r.score for r in rows] == [83]


def test_both_options_share_one_render_call():
    renderer = FakeRenderer()
    result, events = _run(accessibility=True, render_js=True, renderer=renderer)
    assert renderer.calls == [(["https://example.com/"], True)]
    assert result["render_status"] == "rendered" and result["accessibility_status"] == "scanned"
    assert events[-1][1]["kind"] == "render"


def test_no_browser_marks_both_unavailable(monkeypatch):
    monkeypatch.setattr(audit_service, "renderer_available", lambda: (False, "Playwright is not installed"))
    result, _ = _run(accessibility=True, render_js=True)
    assert result["accessibility_status"] == "unavailable" and result["render_status"] == "unavailable"
    assert result["accessibility_unavailable_reason"] == "Playwright is not installed"
    assert result["persisted"] is True


def test_missing_axe_only_disables_accessibility(monkeypatch):
    monkeypatch.setattr(audit_service, "axe_available", lambda: (False, "axe-core not found (app/accessibility/vendor/axe.min.js)"))
    renderer = FakeRenderer()
    result, _ = _run(accessibility=True, render_js=True, renderer=renderer)
    assert result["accessibility_status"] == "unavailable" and result["render_status"] == "rendered"
    assert renderer.calls == [(["https://example.com/"], False)]
