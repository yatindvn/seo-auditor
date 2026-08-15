from types import SimpleNamespace
from unittest.mock import patch

from app.services import audit_service


def test_unnominated_page_spends_no_queries():
    targets = [SimpleNamespace(url="https://example.com/a", keywords=["alpha"])]

    with patch("app.seo.rank_checker.check_rankings") as mock_check:
        keywords = audit_service._match_rank_target("https://example.com/zzz", targets)

    assert keywords is None
    mock_check.assert_not_called()


def test_nominated_page_returns_exactly_its_keywords():
    targets = [SimpleNamespace(url="https://example.com/a", keywords=["alpha", "beta"])]
    assert audit_service._match_rank_target("https://example.com/a", targets) == ["alpha", "beta"]
