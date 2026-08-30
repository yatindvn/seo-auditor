"""Each page's HTML must be parsed once, not once per check.

py-spy on the deployed backend caught the audit stuck in BeautifulSoup:

    descendants (bs4/element.py)
    find_all (bs4/filter.py)
    check_accessibility (checks.py:384)
    _build_audit_result (audit_service.py:152)

`_soup` built a fresh BeautifulSoup on every call and checks.py called it 17
times, so a single page was re-parsed ~15 times. At 3530 pages that is ~53,000
full HTML parses, which is why a large crawl reached 100% and then never
produced a dashboard.

Caching is only safe because exactly one check mutates the tree:
`check_content` calls tag.decompose() on script/style/noscript. It therefore
gets its own private parse. `check_js_rendering_signal` counts <script> tags and
runs *after* check_content, so it is the canary for a cache that wrongly shares
a mutated tree.
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.auditor import checks

HTML = """
<html lang="en"><head><title>Test</title>
<script>var a = 1;</script><script>var b = 2;</script>
<script>var c = 3;</script><script>var d = 4;</script>
<style>body { color: red; }</style>
</head><body id="root">
<h1>Heading</h1><p>Some visible words here for the content check to count.</p>
<noscript>fallback text</noscript>
</body></html>
"""


def _page(html=HTML):
    return SimpleNamespace(html=html, url="https://example.com/", final_url="https://example.com/",
                           status_code=200, headers={}, redirect_chain=[], error=None, depth=0)


def test_repeated_soup_calls_reuse_one_parse():
    page = _page()
    checks._soup.cache_clear() if hasattr(checks._soup, "cache_clear") else None

    with patch.object(checks, "BeautifulSoup", wraps=checks.BeautifulSoup) as spy:
        for _ in range(10):
            checks._soup(page.html)

    assert spy.call_count == 1, f"parsed {spy.call_count} times, expected 1"


def test_mutating_caller_gets_its_own_parse():
    """check_content decomposes tags, so it must never receive a shared tree."""
    page = _page()

    shared_before = checks._soup(page.html)
    scripts_before = len(shared_before.find_all("script"))
    assert scripts_before == 4

    checks.check_content(page)

    shared_after = checks._soup(page.html)
    assert len(shared_after.find_all("script")) == scripts_before, (
        "check_content mutated the shared soup"
    )


def test_js_rendering_signal_still_sees_scripts_after_check_content():
    """The end-to-end canary: run the checks in the order the audit runs them."""
    page = _page()

    checks.check_content(page)
    soup = checks._soup(page.html)

    assert len(soup.find_all("script")) == 4
    assert soup.find("style") is not None
    assert soup.find("noscript") is not None


def test_check_content_still_excludes_script_and_style_text():
    page = _page()

    _, stats = checks.check_content(page)

    assert "var a = 1" not in stats["text"]
    assert "color: red" not in stats["text"]
    assert "visible words here" in stats["text"]
    assert stats["word_count"] > 0


def test_empty_html_returns_none():
    assert checks._soup("") is None
    assert checks._soup(None) is None
