"""Each page is parsed once; the content text is unchanged by not mutating."""

from bs4 import BeautifulSoup

from app.auditor import checks
from app.services import page_pipeline
from app.services.page_pipeline import PagePayload

TRICKY = (
    "<!DOCTYPE html><html><head><title>T</title>"
    "<script>var x = 'not text';</script><style>p { color: red }</style></head>"
    "<body><!-- a comment --><p>Hello <b>bold</b><i>italic</i> world</p>"
    "<noscript><p>enable <em>JS</em></p></noscript>"
    "<template><p>templated</p></template>"
    "<svg><![CDATA[ cdata text ]]></svg>"
    "<div>  spaced\n\n   out  </div><script type='application/ld+json'>{\"a\":1}</script>"
    "<p>tail</p></body></html>"
)


def _old_text(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def test_visible_text_matches_decompose_then_get_text():
    soup = BeautifulSoup(TRICKY, "lxml")
    assert checks._visible_text(soup) == _old_text(TRICKY)


def test_visible_text_leaves_the_tree_intact():
    soup = BeautifulSoup(TRICKY, "lxml")
    checks._visible_text(soup)
    assert len(soup.find_all("script")) == 2
    assert soup.find("noscript") is not None


def test_a_page_is_parsed_once(monkeypatch):
    checks._parse.cache_clear()
    parses = []
    original = checks.BeautifulSoup

    def counting(*args, **kwargs):
        parses.append(1)
        return original(*args, **kwargs)

    # Every parse goes through checks: html_weight reads checks' shared tree.
    monkeypatch.setattr(checks, "BeautifulSoup", counting)

    page_pipeline.analyze_page(PagePayload(
        url="https://example.com/", final_url="https://example.com/", status_code=200,
        headers={}, html=TRICKY + "<!-- unique 1 -->", content_type="text/html",
    ))

    assert len(parses) == 1
