"""max_pages must be capped at what the backend can actually finish.

The cap was 1000 for two measured reasons, both now addressed: 5000 pages never
returned, because the per-page checks ran for over 20 minutes at 98% CPU after
the crawl had already finished; and the response would have been ~110 MB, which
no browser tab handles. The checks now overlap the crawl in a process pool, and
the response is a summary with the rows behind paginated endpoints.

So the cap rises to 5000 -- provisionally. It is configurable because the 1 GB
E2.1.Micro shape documented as an alternative in docs/deployment-oracle.md
cannot hold a crawl this size, and because a 5000-page run has not yet been
measured end to end. What is pinned here is that the boundary is enforced at
all: an out-of-range request must fail immediately with a 422 rather than hang.
"""

import pytest
from pydantic import ValidationError

from app.schemas.schemas import AuditRequestParams, MAX_PAGES_LIMIT


def test_limit_is_five_thousand():
    assert MAX_PAGES_LIMIT == 5000


def test_the_limit_is_configurable(monkeypatch):
    """A 1 GB shape cannot hold a 5000-page crawl, so the ceiling has to move
    with the deployment rather than being a constant in the source."""
    monkeypatch.setenv("MAX_PAGES_LIMIT", "250")
    import importlib
    from app.schemas import schemas

    reloaded = importlib.reload(schemas)
    try:
        assert reloaded.MAX_PAGES_LIMIT == 250
    finally:
        monkeypatch.delenv("MAX_PAGES_LIMIT")
        importlib.reload(schemas)


def test_the_limit_itself_is_accepted():
    assert AuditRequestParams(url="https://example.com", max_pages=MAX_PAGES_LIMIT).max_pages == 5000


def test_above_the_limit_is_rejected():
    with pytest.raises(ValidationError):
        AuditRequestParams(url="https://example.com", max_pages=MAX_PAGES_LIMIT + 1)


def test_five_thousand_is_now_accepted():
    """5000 is exactly what used to hang the audit, and is now the ceiling.

    Inverted deliberately rather than deleted: the number that was the failure
    is the number the pipeline work exists to make survivable, so it stays
    named here.
    """
    assert AuditRequestParams(url="https://example.com", max_pages=5000).max_pages == 5000


def test_beyond_the_new_ceiling_is_still_rejected():
    with pytest.raises(ValidationError):
        AuditRequestParams(url="https://example.com", max_pages=5001)


def test_deep_audit_preset_still_fits():
    """The largest preset the UI offers is 500 and must remain valid."""
    assert AuditRequestParams(url="https://example.com", max_pages=500).max_pages == 500


def test_lower_bound_unchanged():
    assert AuditRequestParams(url="https://example.com", max_pages=1).max_pages == 1
    with pytest.raises(ValidationError):
        AuditRequestParams(url="https://example.com", max_pages=0)
