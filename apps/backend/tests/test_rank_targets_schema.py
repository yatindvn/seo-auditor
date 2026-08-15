import pytest
from pydantic import ValidationError

from app.schemas.schemas import AuditRequestParams, RankTarget


def test_rank_target_accepts_url_and_keywords():
    t = RankTarget(url="https://example.com/services", keywords=["cloud consulting"])
    assert t.url == "https://example.com/services"
    assert t.keywords == ["cloud consulting"]


def test_rank_target_rejects_empty_keyword_list():
    with pytest.raises(ValidationError):
        RankTarget(url="https://example.com/", keywords=[])


def test_rank_target_rejects_more_than_ten_keywords():
    with pytest.raises(ValidationError):
        RankTarget(url="https://example.com/", keywords=[f"kw{i}" for i in range(11)])


def test_audit_params_default_rank_targets_to_none():
    params = AuditRequestParams(url="https://example.com")
    assert params.rank_targets is None


def test_audit_params_accepts_rank_targets():
    params = AuditRequestParams(
        url="https://example.com",
        rank_targets=[{"url": "https://example.com/a", "keywords": ["x", "y"]}],
    )
    assert len(params.rank_targets) == 1
    assert params.rank_targets[0].keywords == ["x", "y"]
