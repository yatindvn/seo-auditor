"""A fake HTTP site for tests that must exercise the crawler's real _fetch:
conditional requests, 304s, and headers -- which replacing _fetch would skip."""

import hashlib
from typing import Dict, List, Optional, Tuple

from requests.structures import CaseInsensitiveDict


class FakeResponse:
    def __init__(self, status_code: int, headers: Dict[str, str], text: str = ""):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers)
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"


class FakeSite:
    """`pages` maps URL -> HTML. Each page's ETag is derived from its HTML, so
    editing a page changes its ETag the way a real server's would."""

    BASE_HEADERS = {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": "default-src 'self'",
        "Strict-Transport-Security": "max-age=31536000",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }

    def __init__(self, pages: Dict[str, str], etags: bool = True,
                 extra_headers: Optional[Dict[str, str]] = None):
        self.pages = dict(pages)
        self.etags = etags
        self.extra_headers = dict(extra_headers or {})
        # What a 304 carries: per RFC 9110 only a few fields; tests can add more.
        self.not_modified_headers: Dict[str, str] = {}
        self.calls: List[Tuple[str, Dict[str, str]]] = []
        self.session = self

    def etag_of(self, url: str) -> str:
        return '"' + hashlib.md5(self.pages[url].encode()).hexdigest() + '"'

    def get(self, url, timeout=None, allow_redirects=False, headers=None, **_):
        self.calls.append((url, dict(headers or {})))
        if url not in self.pages:
            return FakeResponse(404, {"Content-Type": "text/html"}, "")
        response_headers = {**self.BASE_HEADERS, **self.extra_headers}
        if self.etags:
            etag = self.etag_of(url)
            response_headers["ETag"] = etag
            if headers and headers.get("If-None-Match") == etag:
                return FakeResponse(304, {"ETag": etag, **self.not_modified_headers})
        return FakeResponse(200, response_headers, self.pages[url])

    def conditional_calls(self) -> List[str]:
        return [url for url, sent in self.calls
                if "If-None-Match" in sent or "If-Modified-Since" in sent]
