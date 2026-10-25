"""analyze_page splits into a cacheable HTML half and an always-fresh response half.

The golden file was generated from analyze_page *before* the split, so these
tests prove the split changed nothing a caller can see except issue order, which
was never part of the contract and is compared sorted.
"""

import json
from pathlib import Path

import pytest

from app.auditor import checks
from app.services import page_pipeline
from app.services.page_pipeline import PagePayload

GOLDEN = Path(__file__).parent / "fixtures" / "analyze_page_golden.json"

HTML = (
    "<html lang='en'><head><title>Espresso Machines</title>"
    "<meta name='description' content='Reviews of espresso machines'>"
    "<meta name='ROBOTS' content='NoIndex'>"
    "<meta property='og:title' content='Espresso'>"
    "<script src='/a.js'></script><link rel='stylesheet' href='/s.css'></head>"
    "<body><h1>Best Espresso Machines</h1><h2>Reviews</h2>"
    "<p>espresso machine reviews and buying guide with plenty of words to "
    "satisfy the word count checks in this pipeline test fixture.</p>"
    "<img src='/a.png'><img src='/b.png' alt='b'>"
    "<a href='/grinders'>Grinders</a><a href='https://other.example/x'>Off</a>"
    "<a href='http://example.com/insecure'>Insecure</a>"
    "</body></html>"
)

CASES = {
    "plain": dict(headers={}, response_time_ms=10.0),
    "headers_and_slow": dict(
        headers={"X-Robots-Tag": "noindex, nofollow", "Content-Security-Policy": "default-src 'self'",
                 "Strict-Transport-Security": "max-age=1", "Content-Encoding": "gzip",
                 "Cache-Control": "max-age=60", "Content-Length": "1234"},
        response_time_ms=1500.0,
    ),
    "redirected": dict(
        headers={}, response_time_ms=20.0,
        redirect_chain=[{"from": "https://example.com/old", "to": "https://example.com/", "status": 302}],
    ),
    "empty_body": dict(headers={}, html="", response_time_ms=5.0),
}


def _payload(case):
    base = dict(
        url="https://example.com/", final_url="https://example.com/", status_code=200,
        headers={}, html=HTML, depth=0, redirect_chain=[], response_time_ms=10.0,
        content_type="text/html", error=None, compute_signature=True,
    )
    base.update(CASES[case])
    return PagePayload(**base)


def _normalise(analysis):
    data = {
        "issues": sorted(analysis.issues, key=lambda i: (i["code"], i["severity"], i["message"])),
        "meta": analysis.meta,
        "dupe_row": analysis.dupe_row,
        "keyword_data": analysis.keyword_data,
        "internal_links": analysis.internal_links,
        "external_links": analysis.external_links,
        "signature": analysis.signature.hex() if analysis.signature else None,
    }
    return json.loads(json.dumps(data, sort_keys=True, default=str))


def write_golden():
    """Run once, before the split, to capture today's behaviour."""
    GOLDEN.parent.mkdir(exist_ok=True)
    golden = {case: _normalise(page_pipeline.analyze_page(_payload(case))) for case in CASES}
    GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("case", list(CASES))
def test_analyze_page_output_is_unchanged_by_the_split(case):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _normalise(page_pipeline.analyze_page(_payload(case))) == golden[case]


@pytest.mark.parametrize("case", list(CASES))
def test_composing_the_halves_equals_analyze_page(case):
    payload = _payload(case)
    composed = page_pipeline.analyze_response(payload, page_pipeline.analyze_html(payload))
    assert _normalise(composed) == _normalise(page_pipeline.analyze_page(payload))


def test_the_html_half_survives_a_json_round_trip():
    payload = _payload("headers_and_slow")
    part = page_pipeline.analyze_html(payload)
    restored = page_pipeline.HtmlAnalysis.from_json(json.loads(json.dumps(part.to_json())), signature=part.signature)
    assert _normalise(page_pipeline.analyze_response(payload, restored)) == _normalise(
        page_pipeline.analyze_page(payload)
    )


def test_the_response_half_needs_no_html_and_never_parses(monkeypatch):
    """A 304 brings no body. analyze_response must give the full result from the
    cached half plus the new response alone. The expected value is computed
    before parsing is disabled."""
    full = _payload("headers_and_slow")
    expected = _normalise(page_pipeline.analyze_page(full))
    part = page_pipeline.analyze_html(full)

    def no_parsing(*args, **kwargs):
        raise AssertionError("analyze_response parsed HTML")

    monkeypatch.setattr(checks, "_soup", no_parsing)
    monkeypatch.setattr(checks, "_parse", no_parsing)
    bodyless = _payload("headers_and_slow")
    bodyless.html = ""

    assert _normalise(page_pipeline.analyze_response(bodyless, part)) == expected


def test_both_robots_sources_saying_noindex_report_it_once():
    payload = _payload("headers_and_slow")
    analysis = page_pipeline.analyze_page(payload)
    assert [i["code"] for i in analysis.issues].count("NOINDEX") == 1
