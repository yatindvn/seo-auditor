"""JavaScript rendering inside an audit: opt-in, compared against the raw
analysis, issues added and stored, never fatal."""

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import RenderedPage
from app.rendering.model import RenderResult
from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler

JS_HTML = ("<html><head><title>Espresso machines</title><meta name='robots' content='noindex'></head>"
           "<body><h1>Best Espresso Machines</h1><p>" + "espresso " * 400 + "</p>"
           "<a href='/js-only'>more</a></body></html>")


class FakeRenderer:
    name = "fake"

    def __init__(self, html=JS_HTML, error=None, raises=None):
        self.calls, self.html, self.error, self.raises = [], html, error, raises

    def render(self, urls, on_progress=None, run_axe=False):
        self.calls.append(list(urls))
        if self.raises:
            raise self.raises
        out = []
        for i, url in enumerate(urls, 1):
            out.append(RenderResult(url=url, error=self.error) if self.error
                       else RenderResult(url=url, html=self.html, final_url=url, status=200, render_ms=50))
            if on_progress:
                on_progress(i, len(urls), url)
        return out


def _run(**kwargs):
    events = []
    result = audit_service._build_audit_result(
        "https://example.com/", FakeCrawler(), progress_callback=None,
        event_callback=lambda kind, payload: events.append((kind, payload)), **kwargs)
    return result, events


def test_off_by_default_and_nothing_launched(monkeypatch):
    monkeypatch.setattr(audit_service, "renderer_available", lambda: (_ for _ in ()).throw(AssertionError("checked")))
    result, _ = _run()
    assert result["render_status"] == "disabled" and result["rendering"] == []


def test_renders_compares_and_adds_issues():
    renderer = FakeRenderer()
    result, events = _run(render_js=True, renderer=renderer)
    assert renderer.calls == [["https://example.com/"]]
    assert result["render_status"] == "rendered"
    row = result["rendering"][0]
    assert row["changes"]["title"] == {"raw": "Espresso Machines", "rendered": "Espresso machines"}
    assert row["changes"]["meta_robots"]["rendered"] == "noindex"
    assert row["js_only_links"] == ["https://example.com/js-only"]
    codes = [i["code"] for i in result["page_issues_detail"]["https://example.com/"]]
    assert {"JS_TITLE_CHANGED", "JS_ROBOTS_CHANGED", "JS_CONTENT_DEPENDENT", "JS_ONLY_LINKS"} <= set(codes)
    assert ("rendering", {"done": 1, "total": 1, "url": "https://example.com/"}) in events
    with get_session_factory()() as session:
        stored = session.scalars(select(RenderedPage).where(RenderedPage.audit_id == result["audit_id"])).all()
        assert [r.url for r in stored] == ["https://example.com/"]


def test_a_failed_page_is_recorded_without_issues():
    result, _ = _run(render_js=True, renderer=FakeRenderer(error="TimeoutError: 20000ms"))
    assert result["rendering"][0]["status"] == "failed"
    assert not [i for i in result["page_issues_detail"]["https://example.com/"] if i["code"].startswith("JS_")]


def test_unavailable_browser_does_not_fail_the_audit(monkeypatch):
    monkeypatch.setattr(audit_service, "renderer_available", lambda: (False, "Playwright is not installed"))
    result, _ = _run(render_js=True)
    assert result["render_status"] == "unavailable"
    assert result["render_unavailable_reason"] == "Playwright is not installed"
    assert result["persisted"] is True


def test_a_crashing_renderer_is_unavailable_not_fatal():
    result, _ = _run(render_js=True, renderer=FakeRenderer(raises=RuntimeError("browser crashed")))
    assert result["render_status"] == "unavailable"
    assert result["render_unavailable_reason"] == "RuntimeError: browser crashed"


def test_the_page_limit_is_respected():
    renderer = FakeRenderer()
    _run(render_js=True, renderer=renderer, render_max_pages=0)
    assert renderer.calls == []
