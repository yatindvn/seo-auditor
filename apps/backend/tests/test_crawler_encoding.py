"""Decoding a page's bytes. requests assumes ISO-8859-1 for any text/* response
without a charset (RFC 2616), which turned "Loading…" into "Loadingâ€¦" for
UTF-8 pages served without one -- and made the rendered page look like
JavaScript had changed the title."""

from requests import Response
from requests.structures import CaseInsensitiveDict

from app.crawler.crawler import decode_html


def _response(body: bytes, content_type: str) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = body
    resp.headers = CaseInsensitiveDict({"Content-Type": content_type})
    resp.encoding = "ISO-8859-1" if "charset" not in content_type else content_type.split("charset=")[1]
    return resp


def test_no_charset_defaults_to_utf8():
    html = "<html><head><title>Loading…</title></head></html>"
    assert "Loading…" in decode_html(_response(html.encode("utf-8"), "text/html"))


def test_meta_charset_is_honoured_when_the_header_has_none():
    html = '<html><head><meta charset="windows-1252"><title>Café</title></head></html>'
    assert "Café" in decode_html(_response(html.encode("cp1252"), "text/html"))
    html = '<html><head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1"><title>Café</title></head></html>'
    assert "Café" in decode_html(_response(html.encode("latin-1"), "text/html"))


def test_the_header_charset_wins():
    html = "<html><head><title>Café</title></head></html>"
    assert "Café" in decode_html(_response(html.encode("latin-1"), "text/html; charset=ISO-8859-1"))


def test_an_unknown_meta_charset_falls_back_to_utf8():
    html = '<html><head><meta charset="no-such-codec"><title>Loading…</title></head></html>'
    assert "Loading…" in decode_html(_response(html.encode("utf-8"), "text/html"))
