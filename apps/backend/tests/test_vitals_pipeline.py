"""Core Web Vitals inside an audit: measured once after the crawl, issues
added, stored, and never fatal."""

from unittest.mock import patch

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import WebVital
from app.services import audit_service
from app.vitals.model import VitalsResult

from test_audit_service_crawler_registry import FakeCrawler


class StubProvider:
    name = "stub"

    def __init__(self, result=None, raises=None):
        self.calls, self.result, self.raises = [], result, raises

    def measure(self, url, strategy="mobile"):
        self.calls.append((url, strategy))
        if self.raises:
            raise self.raises
        return self.result or VitalsResult(url=url, source="lighthouse", data_kind="lab",
                                           lcp_ms=4800, cls=0.01, tbt_ms=50, rating="poor")


def _run(**kwargs):
    events = []
    result = audit_service._build_audit_result(
        "https://example.com/", FakeCrawler(), progress_callback=None,
        event_callback=lambda kind, payload: events.append((kind, payload)), **kwargs)
    return result, events


def test_measures_after_the_crawl_and_adds_issues():
    provider = StubProvider()
    result, events = _run(vitals_provider=provider)
    assert provider.calls == [("https://example.com/", "mobile")]
    assert result["web_vitals_status"] == "measured"
    assert result["web_vitals"][0]["lcp_ms"] == 4800
    codes = [i["code"] for i in result["page_issues_detail"]["https://example.com/"]]
    assert "CWV_LCP_POOR" in codes
    assert ("web_vitals", {"done": 1, "total": 1, "url": "https://example.com/"}) in events
    assert result["psi_metrics"] == {}          # only PSI-sourced pages are listed there
    with get_session_factory()() as session:
        rows = session.scalars(select(WebVital).where(WebVital.audit_id == result["audit_id"])).all()
        assert [r.lcp_ms for r in rows] == [4800.0]


def test_psi_results_are_mirrored_in_psi_metrics():
    provider = StubProvider(VitalsResult(url="https://example.com/", source="psi", data_kind="lab",
                                         performance_score=91, lcp_ms=1200, rating="good"))
    result, _ = _run(vitals_provider=provider)
    assert result["psi_metrics"]["https://example.com/"]["lcp_ms"] == 1200


def test_disabled_and_not_configured():
    provider = StubProvider()
    result, _ = _run(vitals_provider=provider, enable_web_vitals=False)
    assert provider.calls == [] and result["web_vitals_status"] == "disabled" and result["web_vitals"] == []
    result, _ = _run()
    assert result["web_vitals_status"] == "not_configured" and result["web_vitals"] == []


def test_a_crashing_provider_never_fails_the_audit():
    result, _ = _run(vitals_provider=StubProvider(raises=RuntimeError("boom")))
    assert result["web_vitals"][0]["error"] == "unexpected error (RuntimeError)"
    assert result["persisted"] is True


def test_the_page_limit_is_respected():
    provider = StubProvider()
    _run(vitals_provider=provider, vitals_max_pages=0)
    assert provider.calls == []
