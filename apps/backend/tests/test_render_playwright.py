"""The Playwright renderer, with Playwright itself faked: no browser runs in
tests."""

from unittest.mock import MagicMock

import pytest

from app.rendering import playwright_renderer as pr


class FakeTimeout(Exception):
    pass


def _fake_playwright(pages):
    """pages: url -> (html, status) or an Exception to raise from goto."""
    browser = MagicMock(name="browser")
    contexts = []

    def new_context(**kwargs):
        ctx = MagicMock(name="context")
        ctx.kwargs = kwargs
        page = MagicMock(name="page")
        state = {}

        def goto(url, **kw):
            state["url"] = url
            outcome = pages[url]
            if isinstance(outcome, Exception):
                raise outcome
            page.url = url
            return MagicMock(status=outcome[1])

        page.goto.side_effect = goto
        page.wait_for_load_state.side_effect = FakeTimeout("network never idle")
        page.content.side_effect = lambda: pages[state["url"]][0]
        ctx.new_page.return_value = page
        contexts.append(ctx)
        return ctx

    browser.new_context.side_effect = new_context
    pw = MagicMock(name="pw")
    pw.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.__enter__.return_value = pw
    sync_playwright = MagicMock(return_value=manager)
    return sync_playwright, browser, contexts


def test_renders_each_url_in_a_locked_down_context(monkeypatch):
    sync, browser, contexts = _fake_playwright({"https://a.com/": ("<html>A</html>", 200),
                                                "https://a.com/b": ("<html>B</html>", 200)})
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    seen = []
    results = pr.PlaywrightRenderer(5000).render(["https://a.com/", "https://a.com/b"],
                                                 on_progress=lambda d, t, u: seen.append((d, t, u)))
    assert [(r.url, r.html, r.status, r.error) for r in results] == [
        ("https://a.com/", "<html>A</html>", 200, None), ("https://a.com/b", "<html>B</html>", 200, None)]
    assert all(r.render_ms is not None for r in results)
    assert contexts[0].kwargs == {"java_script_enabled": True, "accept_downloads": False, "service_workers": "block"}
    page = contexts[0].new_page.return_value
    assert page.goto.call_args.kwargs == {"wait_until": "load", "timeout": 5000}
    assert page.route.call_args.args[0] == "**/*"
    assert all(c.close.called for c in contexts) and browser.close.called
    assert seen == [(1, 2, "https://a.com/"), (2, 2, "https://a.com/b")]


def test_heavy_resources_are_blocked():
    for kind, aborted in (("image", True), ("media", True), ("font", True), ("script", False), ("xhr", False)):
        route = MagicMock()
        route.request.resource_type = kind
        pr._block_heavy(route)
        assert route.abort.called is aborted and route.continue_.called is (not aborted)


def test_one_failing_page_does_not_stop_the_rest(monkeypatch):
    boom = RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://a.com/x\nCall log:\n  - navigating")
    sync, browser, contexts = _fake_playwright({"https://a.com/x": boom, "https://a.com/": ("<p>ok</p>", 200)})
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    results = pr.PlaywrightRenderer(5000).render(["https://a.com/x", "https://a.com/"])
    assert results[0].error == "RuntimeError: net::ERR_NAME_NOT_RESOLVED at https://a.com/x"
    assert results[1].html == "<p>ok</p>"
    assert contexts[0].close.called and browser.close.called


def test_the_browser_is_closed_when_something_unexpected_happens(monkeypatch):
    sync, browser, _ = _fake_playwright({"https://a.com/": ("<p/>", 200)})
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    with pytest.raises(ValueError):
        pr.PlaywrightRenderer(5000).render(["https://a.com/"], on_progress=MagicMock(side_effect=ValueError("x")))
    assert browser.close.called


def test_unavailable_without_playwright(monkeypatch):
    def missing():
        raise ImportError("No module named 'playwright'")
    monkeypatch.setattr(pr, "_load_playwright", missing)
    assert pr.renderer_available() == (False, "Playwright is not installed")
    assert pr.playwright_chromium() is None


def test_unavailable_without_chromium(monkeypatch, tmp_path):
    sync, _, _ = _fake_playwright({})
    sync.return_value.__enter__.return_value.chromium.executable_path = str(tmp_path / "missing" / "chrome")
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    ok, reason = pr.renderer_available()
    assert ok is False and reason.startswith("Chromium is not installed")


def test_available_when_chromium_exists(monkeypatch, tmp_path):
    chrome = tmp_path / "chrome"; chrome.write_text("")
    sync, _, _ = _fake_playwright({})
    sync.return_value.__enter__.return_value.chromium.executable_path = str(chrome)
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    assert pr.renderer_available() == (True, "")
    assert pr.playwright_chromium() == str(chrome)
