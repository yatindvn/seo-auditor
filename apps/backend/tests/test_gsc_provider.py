"""Search Console provider: request shapes, parsing, errors, caps, dry run."""

import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.config import config
from app.gsc import provider as gp
from app.gsc.provider import (DryRunGsc, GscError, Inspection, ServiceAccountGsc, build_gsc_provider,
                              parse_inspection, site_domain)


class FakeSession:
    def __init__(self, responses):
        self.calls, self.responses = [], list(responses)

    def request(self, method, url, json=None, timeout=None):
        self.calls.append((method, url, json))
        status, body = self.responses.pop(0)
        resp = MagicMock(status_code=status, text=str(body))
        resp.json.return_value = body
        return resp


@pytest.fixture
def key_file(tmp_path):
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"client_email": "auditor@proj.iam.gserviceaccount.com",
                                "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----"}))
    return str(path)


def test_sites_and_client_email(key_file):
    session = FakeSession([(200, {"siteEntry": [{"siteUrl": "sc-domain:shop.com", "permissionLevel": "siteFullUser"}]})])
    gsc = ServiceAccountGsc(key_file, session=session)
    assert gsc.client_email == "auditor@proj.iam.gserviceaccount.com"
    assert [(s.site_url, s.permission) for s in gsc.sites()] == [("sc-domain:shop.com", "siteFullUser")]
    assert session.calls == [("GET", "https://www.googleapis.com/webmasters/v3/sites", None)]


def test_search_analytics_request_and_rows(key_file):
    session = FakeSession([(200, {"rows": [{"keys": ["https://shop.com/a"], "clicks": 12, "impressions": 340,
                                            "ctr": 0.035, "position": 7.2}]})])
    rows = ServiceAccountGsc(key_file, session=session).search_analytics(
        "sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 28), ["page"], 1000)
    method, url, body = session.calls[0]
    assert url == "https://www.googleapis.com/webmasters/v3/sites/sc-domain%3Ashop.com/searchAnalytics/query"
    assert body == {"startDate": "2026-10-01", "endDate": "2026-10-28", "dimensions": ["page"], "rowLimit": 1000}
    assert rows[0].keys == ("https://shop.com/a",) and rows[0].clicks == 12.0 and rows[0].position == 7.2


def test_inspection_request_and_parsing(key_file):
    result = {"inspectionResult": {"indexStatusResult": {
        "verdict": "NEUTRAL", "coverageState": "Crawled - currently not indexed", "indexingState": "INDEXING_ALLOWED",
        "robotsTxtState": "ALLOWED", "pageFetchState": "SUCCESSFUL", "googleCanonical": "https://shop.com/a",
        "userCanonical": "https://shop.com/a/", "lastCrawlTime": "2026-10-20T08:00:00Z"}}}
    session = FakeSession([(200, result)])
    insp = ServiceAccountGsc(key_file, session=session).inspect("sc-domain:shop.com", "https://shop.com/a")
    assert session.calls[0] == ("POST", "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                                {"inspectionUrl": "https://shop.com/a", "siteUrl": "sc-domain:shop.com"})
    assert (insp.verdict, insp.coverage_state, insp.google_canonical, insp.last_crawl) == (
        "NEUTRAL", "Crawled - currently not indexed", "https://shop.com/a", "2026-10-20T08:00:00Z")
    assert parse_inspection("u", {}) == Inspection(url="u")


def test_errors_carry_googles_message_and_never_the_key(key_file):
    session = FakeSession([(403, {"error": {"message": "User does not have sufficient permission"}})])
    with pytest.raises(GscError) as err:
        ServiceAccountGsc(key_file, session=session).sites()
    assert err.value.status == 403
    assert err.value.message == "the service account has no access to this property (User does not have sufficient permission)"
    assert "SECRET" not in err.value.message


def test_inspection_errors_and_caps_are_per_url(key_file, monkeypatch):
    session = FakeSession([(500, {"error": {"message": "Backend Error"}})])
    insp = ServiceAccountGsc(key_file, session=session).inspect("sc-domain:shop.com", "https://shop.com/a")
    assert insp.error == "Backend Error" and insp.verdict is None
    monkeypatch.setattr(config, "GSC_INSPECT_DAILY_CAP", 0)
    capped = ServiceAccountGsc(key_file, session=FakeSession([])).inspect("sc-domain:shop.com", "https://shop.com/b")
    assert capped.error == "daily cap of 0 gsc_inspect calls reached"
    monkeypatch.setattr(config, "GSC_DAILY_CAP", 0)
    with pytest.raises(GscError) as err:
        ServiceAccountGsc(key_file, session=FakeSession([])).search_analytics("p", date(2026, 1, 1), date(2026, 1, 2), ["date"])
    assert err.value.status == 429


def test_network_errors_name_the_type_only(key_file):
    class Boom:
        def request(self, *a, **k):
            raise ConnectionError("https://...?access_token=SECRET")
    with pytest.raises(GscError) as err:
        ServiceAccountGsc(key_file, session=Boom()).sites()
    assert err.value.message == "Search Console request failed: ConnectionError"


def test_dry_run_is_deterministic_and_well_formed():
    a, b = DryRunGsc(), DryRunGsc()
    days = a.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 3), ["date"])
    assert [r.keys[0] for r in days] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert days == b.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 3), ["date"])
    pages = a.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 28), ["page"])
    assert pages[0].keys[0] == "https://shop.com/" and all(r.keys[0].startswith("https://shop.com/") for r in pages)
    assert len(a.search_analytics("sc-domain:shop.com", date(2026, 10, 1), date(2026, 10, 28), ["query"])) > 5
    verdicts = {a.inspect("sc-domain:shop.com", f"https://shop.com/p{i}").verdict for i in range(20)}
    assert verdicts == {"PASS", "NEUTRAL"} and a.dry_run is True


def test_site_domain():
    assert site_domain("sc-domain:shop.com") == "shop.com"
    assert site_domain("https://www.shop.com/") == "shop.com"


def test_build_modes(monkeypatch, key_file):
    assert build_gsc_provider() is None
    monkeypatch.setattr(config, "GSC_SERVICE_ACCOUNT_FILE", key_file)
    assert isinstance(build_gsc_provider(), ServiceAccountGsc)
    monkeypatch.setattr(config, "GSC_SERVICE_ACCOUNT_FILE", key_file + ".missing")
    assert build_gsc_provider() is None
    monkeypatch.setattr(config, "GSC_DRY_RUN", True)
    assert isinstance(build_gsc_provider(), DryRunGsc)
