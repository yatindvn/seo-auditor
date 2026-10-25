"""An audit is saved under the site it audited, however its analyses finished.

Analyses still pending when the crawl ends are resolved in a loop that used to
bind its loop variable to the function's own `url` parameter, so any audit large
enough to use the process pool was saved under its last-resolved page. The
history panel then listed it as an audit of that page.
"""

import concurrent.futures
from unittest.mock import patch

from app.crawler.crawler import Crawler, PageResult
from app.services import audit_service, page_pipeline

HOME = "https://example.com/"


def _finished(payload):
    """A pool result: a Future, so the audit queues it as pending rather than
    resolving it on the spot."""
    future = concurrent.futures.Future()
    future.set_result(page_pipeline.analyze_page(payload))
    return future


def test_an_audit_with_pending_analyses_is_saved_under_the_audited_site(isolated_session_dir):
    pages = {HOME: "<a href='/a'>a</a><a href='/b'>b</a>",
             "https://example.com/a": "<p>a</p>", "https://example.com/b": "<p>b</p>"}
    crawler = Crawler(HOME, max_pages=5, max_depth=1, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler._fetch = lambda url: PageResult(url=url, final_url=url, status_code=200,
                                            html=pages[url], headers={})

    with patch.object(audit_service, "_submit_analysis", side_effect=lambda pool, p: _finished(p)):
        audit_service._build_audit_result(
            HOME, crawler, progress_callback=None, event_callback=None,
            external_link_check_limit=0, session_id="sess_url",
        )

    assert isolated_session_dir.get_session("sess_url")["url"] == HOME
