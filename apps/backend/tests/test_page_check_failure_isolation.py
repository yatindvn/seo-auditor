"""One page whose checks raise must not destroy the whole audit.

The bug this file exists for: `_build_audit_result` runs ~20 checks per page in
a bare loop (`app/services/audit_service.py:125`). Any exception from any check
on any page propagated out of the loop, so a single malformed page discarded the
entire crawl — after the crawl had already been paid for. On a 1000-page audit
that is minutes of fetching thrown away because one page's markup tripped a
parser, and the dashboard shows nothing at all rather than 999 good pages.

Real crashes of this shape come from markup a check did not anticipate: a tag
BeautifulSoup returns as None, an attribute that is a list where a string was
expected, a malformed header value. They are impossible to enumerate in advance,
which is why the loop needs a boundary rather than each check needing a fix.
"""

import logging

from unittest.mock import patch

from app.auditor import checks
from app.crawler.crawler import PageResult
from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler

HEALTHY_URL = "https://example.com/"
BROKEN_URL = "https://example.com/broken"


class TwoPageCrawler(FakeCrawler):
    """FakeCrawler plus a second page, so a failure on one can be shown not to
    affect the other. One page alone cannot distinguish "isolated the failure"
    from "swallowed the audit"."""

    def __init__(self):
        super().__init__()
        self.results[BROKEN_URL] = PageResult(
            url=BROKEN_URL,
            final_url=BROKEN_URL,
            status_code=200,
            html="<html><head><title>Grinders</title></head><body><h1>Grinders</h1></body></html>",
            headers={},
            depth=1,
        )
        self.link_graph[BROKEN_URL] = set()
        self.inbound_links[BROKEN_URL] = {HEALTHY_URL}


def _raising_check_title(url_to_fail):
    """Make `check_title` blow up on one page and behave normally on every
    other, imitating a check meeting markup it cannot handle."""
    real_check_title = checks.check_title

    def side_effect(page, *args, **kwargs):
        if page.url == url_to_fail:
            raise AttributeError("'NoneType' object has no attribute 'get_text'")
        return real_check_title(page, *args, **kwargs)

    return side_effect


def _row_for(result, url):
    return next(row for row in result["pages"] if row["url"] == url)


def test_audit_completes_when_one_pages_checks_raise():
    crawler = TwoPageCrawler()

    with patch.object(audit_service.checks, "check_title", side_effect=_raising_check_title(BROKEN_URL)):
        result = audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
        )

    assert {row["url"] for row in result["pages"]} == {HEALTHY_URL, BROKEN_URL}


def test_healthy_pages_keep_their_full_data_when_another_page_fails():
    """Isolation has to be per-page. A boundary that caught the exception but
    abandoned the rest of the loop would still pass the test above."""
    crawler = TwoPageCrawler()

    with patch.object(audit_service.checks, "check_title", side_effect=_raising_check_title(BROKEN_URL)):
        result = audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
        )

    healthy = _row_for(result, HEALTHY_URL)
    assert healthy["title"] == "Espresso Machines"
    assert healthy["word_count"] > 0
    assert healthy["keyword_analysis"]["top_keywords"]


def test_the_failed_page_is_reported_as_an_error_not_silently_blank():
    """A page that could not be audited must say so. Returning an empty row
    would read as "audited, nothing wrong" — worse than the crash, because it is
    wrong quietly."""
    crawler = TwoPageCrawler()

    with patch.object(audit_service.checks, "check_title", side_effect=_raising_check_title(BROKEN_URL)):
        result = audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
        )

    broken_issues = result["page_issues_detail"][BROKEN_URL]
    assert [issue for issue in broken_issues if issue["code"] == "AUDIT_ERROR"], (
        f"expected an AUDIT_ERROR issue for {BROKEN_URL}, got {broken_issues}"
    )
    assert "AUDIT_ERROR" in _row_for(result, BROKEN_URL)["issue_codes"]


def test_the_failure_is_logged_with_the_url_and_traceback(caplog):
    """The whole point of catching is that the cause stays diagnosable. A bare
    except that logged nothing would turn a loud bug into an invisible one."""
    crawler = TwoPageCrawler()

    with caplog.at_level(logging.ERROR, logger="seo_auditor"):
        with patch.object(audit_service.checks, "check_title", side_effect=_raising_check_title(BROKEN_URL)):
            audit_service._build_audit_result(
                "https://example.com/", crawler, progress_callback=None, event_callback=None,
            )

    matching = [record for record in caplog.records if BROKEN_URL in record.getMessage()]
    assert matching, f"no ERROR log mentioning {BROKEN_URL}; got {[r.getMessage() for r in caplog.records]}"
    assert matching[0].exc_info is not None, "the traceback must be preserved, not just the message"
