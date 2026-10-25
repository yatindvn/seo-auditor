"""normalize_url merges only spellings that cannot change what the server serves.

Anything that *can* serve different content -- trailing slash, path case, www,
scheme -- is left alone; redirects and identical bodies decide those instead.
"""

import pytest

from app.crawler.crawler import normalize_url


@pytest.mark.parametrize("raw, expected", [
    # tracking params dropped
    ("https://example.com/shoes?utm_source=fb", "https://example.com/shoes"),
    ("https://example.com/shoes?UTM_Medium=x&gclid=1&fbclid=2", "https://example.com/shoes"),
    ("https://example.com/s?msclkid=a&dclid=b&yclid=c&mc_cid=d&mc_eid=e&_ga=f&_gl=g&ref_src=h",
     "https://example.com/s"),
    # real params kept and sorted by name, repeated keys keep their order
    ("https://example.com/s?b=2&a=1", "https://example.com/s?a=1&b=2"),
    ("https://example.com/s?tag=z&tag=a", "https://example.com/s?tag=z&tag=a"),
    ("https://example.com/s?q=1&utm_campaign=x", "https://example.com/s?q=1"),
    # valueless params are not rewritten to "name="
    ("https://example.com/s?print", "https://example.com/s?print"),
    # default ports dropped, others kept
    ("https://example.com:443/a", "https://example.com/a"),
    ("http://example.com:80/a", "http://example.com/a"),
    ("https://example.com:8443/a", "https://example.com:8443/a"),
    # existing behaviour preserved
    ("HTTPS://Example.COM/a#frag", "https://example.com/a"),
    ("https://example.com", "https://example.com/"),
    ("https://example.com//a//b", "https://example.com/a/b"),
])
def test_lossless_spellings_are_merged(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "https://example.com/about/",
    "https://example.com/About",
    "https://www.example.com/a",
    "http://example.com/a",
    "https://example.com/index.html",
])
def test_spellings_that_can_serve_different_content_are_kept(raw):
    assert normalize_url(raw) == raw
