"""One Chromium load per page feeds both rendering and accessibility."""

from types import SimpleNamespace as NS

from app.rendering.model import RenderResult
from app.rendering.runner import run_browser_pass
from app.services.page_pipeline import HtmlAnalysis

URL = "https://a.com/"
RAW_AXE = {"violations": [{"id": "color-contrast", "impact": "serious", "help": "Contrast",
                           "helpUrl": "https://dequeuniversity.com/x", "tags": ["wcag2aa"], "nodes": [{"target": ["#b"]}]}]}


class Renderer:
    name = "fake"

    def __init__(self, result):
        self.calls, self.result = [], result

    def render(self, urls, on_progress=None, run_axe=False):
        self.calls.append((list(urls), run_axe))
        return [self.result]


def _inputs():
    part = HtmlAnalysis(meta={"title": "Shop", "word_count": 10}, internal_links=[])
    return ({URL: NS(status_code=200, depth=0, content_type="text/html")},
            {URL: NS(failed=False, html_part=part)})


def _run(result, render_js, accessibility):
    results, analyses = _inputs()
    renderer = Renderer(result)
    out = run_browser_pass(renderer, URL, [], results, analyses, 5,
                           render_js=render_js, accessibility=accessibility)
    return renderer, out


def _loaded(**over):
    return RenderResult(url=URL, html="<title>Shop!</title>", final_url=URL, status=200, render_ms=10, **over)


def test_rendering_only():
    renderer, (comparisons, scans) = _run(_loaded(), True, False)
    assert renderer.calls == [([URL], False)]
    assert comparisons[0].changes["title"]["rendered"] == "Shop!" and scans == []


def test_accessibility_only():
    renderer, (comparisons, scans) = _run(_loaded(axe=RAW_AXE), False, True)
    assert renderer.calls == [([URL], True)]
    assert comparisons == [] and scans[0].score == 93 and scans[0].violations[0]["id"] == "color-contrast"


def test_both_share_one_load():
    renderer, (comparisons, scans) = _run(_loaded(axe=RAW_AXE), True, True)
    assert len(renderer.calls) == 1 and len(comparisons) == 1 and len(scans) == 1


def test_failures_are_per_feature():
    _, (comparisons, scans) = _run(_loaded(axe_error="RuntimeError: axe is not defined"), True, True)
    assert comparisons[0].status == "rendered"
    assert (scans[0].status, scans[0].error) == ("failed", "RuntimeError: axe is not defined")
    _, (comparisons, scans) = _run(RenderResult(url=URL, error="TimeoutError: 20000ms"), True, True)
    assert comparisons[0].status == "failed" and scans[0].status == "failed"
    assert scans[0].error == "TimeoutError: 20000ms"
    _, (_, scans) = _run(_loaded(), False, True)
    assert (scans[0].status, scans[0].error) == ("failed", "axe returned no result")
