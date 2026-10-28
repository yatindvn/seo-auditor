"""PageSpeed Insights: raw-number parsing, field before lab, the daily cap,
and errors that never leak the key."""

from unittest.mock import MagicMock, patch

import requests

from app.vitals import psi
from app.vitals.psi import PsiProvider, parse_field, parse_lab, parse_psi

LAB = {
    "categories": {"performance": {"score": 0.42}},
    "audits": {
        "largest-contentful-paint": {"numericValue": 4810.5, "displayValue": "4.8 s"},
        "cumulative-layout-shift": {"numericValue": 0.12},
        "first-contentful-paint": {"numericValue": 1900},
        "total-blocking-time": {"numericValue": 350},
        "server-response-time": {"numericValue": 420},
    },
}
FIELD = {"metrics": {
    "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300},
    "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5},     # PSI sends CLS x100
    "FIRST_CONTENTFUL_PAINT_MS": {"percentile": 1200},
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": {"percentile": 600},
}}


def _response(status=200, body=None, text=""):
    resp = MagicMock(status_code=status, text=text)
    resp.json.return_value = body
    return resp


def test_parse_lab_reads_raw_numbers_not_display_strings():
    assert parse_lab(LAB) == {"performance_score": 42.0, "lcp_ms": 4810.5, "cls": 0.12,
                              "fcp_ms": 1900.0, "tbt_ms": 350.0, "ttfb_ms": 420.0}


def test_parse_field_divides_cls_and_ignores_origin_fallback():
    assert parse_field(FIELD) == {"lcp_ms": 2300.0, "inp_ms": 180.0, "cls": 0.05,
                                  "fcp_ms": 1200.0, "ttfb_ms": 600.0}
    assert parse_field({**FIELD, "origin_fallback": True}) == {}
    assert parse_field(None) == {}


def test_field_data_wins_and_lab_keeps_score_and_tbt():
    r = parse_psi("https://a.com/", "mobile", {"lighthouseResult": LAB, "loadingExperience": FIELD})
    assert (r.source, r.data_kind) == ("psi", "field")
    assert (r.lcp_ms, r.inp_ms, r.cls) == (2300.0, 180.0, 0.05)
    assert (r.performance_score, r.tbt_ms) == (42.0, 350.0)
    assert r.rating == "good"


def test_lab_only_is_rated_on_lab_numbers():
    r = parse_psi("https://a.com/", "mobile", {"lighthouseResult": LAB})
    assert r.data_kind == "lab" and r.inp_ms is None and r.rating == "poor"


def test_a_lighthouse_runtime_error_is_an_error():
    r = parse_psi("https://a.com/", "mobile", {"lighthouseResult": {"runtimeError": {"code": "NO_FCP", "message": "No content"}}})
    assert r.error == "PSI: No content"


def test_measure_calls_psi_and_parses():
    with patch.object(psi.requests, "get", return_value=_response(body={"lighthouseResult": LAB})) as get:
        r = PsiProvider("k-123", cap=5).measure("https://a.com/")
    assert get.call_args.kwargs["params"] == {"url": "https://a.com/", "key": "k-123",
                                              "strategy": "mobile", "category": "performance"}
    assert r.lcp_ms == 4810.5 and r.error is None


def test_http_errors_are_reported_without_the_key():
    body = {"error": {"message": "API key k-123 not valid"}}
    with patch.object(psi.requests, "get", return_value=_response(400, body)):
        r = PsiProvider("k-123", cap=5).measure("https://a.com/")
    assert r.error == "PSI returned 400: API key *** not valid"


def test_network_errors_name_the_type_only():
    """str() of a requests exception contains the request URL, key included."""
    boom = requests.ConnectionError("https://www.googleapis.com/...?key=k-123")
    with patch.object(psi.requests, "get", side_effect=boom):
        r = PsiProvider("k-123", cap=5).measure("https://a.com/")
    assert r.error == "PSI request failed: ConnectionError" and "k-123" not in r.error


def test_the_daily_cap_stops_calls():
    with patch.object(psi.requests, "get", return_value=_response(body={"lighthouseResult": LAB})) as get:
        provider = PsiProvider("k", cap=1)
        first, second = provider.measure("https://a.com/"), provider.measure("https://a.com/b")
    assert first.error is None
    assert second.error == "daily cap of 1 psi calls reached"
    assert get.call_count == 1
