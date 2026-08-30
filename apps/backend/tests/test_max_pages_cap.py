"""max_pages must be capped at what the backend can actually finish.

Measured on the deployed VM: 500 pages completes in ~127s and returns an 11 MB
payload. 5000 pages never returned -- the crawl finished but the per-page checks
ran for over 20 minutes at 98% CPU, and the payload would have been ~110 MB,
which no browser tab handles.

Disabling the Full Site Crawl preset closed one door; the Advanced Overrides
slider still reached 5000, and that is the route a user actually took. The API
must refuse it too, so an out-of-range request fails immediately with a clear
422 instead of hanging for half an hour.
"""

import pytest
from pydantic import ValidationError

from app.schemas.schemas import AuditRequestParams, MAX_PAGES_LIMIT


def test_limit_is_one_thousand():
    assert MAX_PAGES_LIMIT == 1000


def test_the_limit_itself_is_accepted():
    assert AuditRequestParams(url="https://example.com", max_pages=MAX_PAGES_LIMIT).max_pages == 1000


def test_above_the_limit_is_rejected():
    with pytest.raises(ValidationError):
        AuditRequestParams(url="https://example.com", max_pages=MAX_PAGES_LIMIT + 1)


def test_the_old_ceiling_is_now_rejected():
    """5000 was the previous ceiling and is exactly what hung the audit."""
    with pytest.raises(ValidationError):
        AuditRequestParams(url="https://example.com", max_pages=5000)


def test_deep_audit_preset_still_fits():
    """The largest preset the UI offers is 500 and must remain valid."""
    assert AuditRequestParams(url="https://example.com", max_pages=500).max_pages == 500


def test_lower_bound_unchanged():
    assert AuditRequestParams(url="https://example.com", max_pages=1).max_pages == 1
    with pytest.raises(ValidationError):
        AuditRequestParams(url="https://example.com", max_pages=0)
