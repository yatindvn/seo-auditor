from app.services import audit_service


def test_get_crawler_returns_none_for_unknown_session():
    assert audit_service.get_crawler("unknown_session") is None


def test_registered_crawler_is_scoped_to_its_session():
    crawler_a = object()
    crawler_b = object()

    audit_service.register_crawler("session_a", crawler_a)
    audit_service.register_crawler("session_b", crawler_b)

    try:
        assert audit_service.get_crawler("session_a") is crawler_a
        assert audit_service.get_crawler("session_b") is crawler_b
    finally:
        audit_service.unregister_crawler("session_a")
        audit_service.unregister_crawler("session_b")


def test_unregister_crawler_removes_only_its_own_session():
    audit_service.register_crawler("session_a", object())
    audit_service.register_crawler("session_b", object())

    audit_service.unregister_crawler("session_a")

    assert audit_service.get_crawler("session_a") is None
    assert audit_service.get_crawler("session_b") is not None

    audit_service.unregister_crawler("session_b")


def test_resolve_keyword_data_disabled_and_no_target_keywords_returns_empty():
    page_meta_entry = {"title": "Espresso Machines", "h1": "Best Espresso Machines", "heading_hierarchy": []}
    content_stats = {"text": "espresso machine reviews and buying guide"}

    result = audit_service._resolve_keyword_data(
        target_keywords=None,
        enable_keyword_analysis=False,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert result == []


def test_resolve_keyword_data_enabled_and_no_target_keywords_extracts_keywords():
    page_meta_entry = {"title": "Espresso Machines", "h1": "Best Espresso Machines", "heading_hierarchy": []}
    content_stats = {"text": "espresso machine reviews and buying guide"}

    result = audit_service._resolve_keyword_data(
        target_keywords=None,
        enable_keyword_analysis=True,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert len(result) > 0
    assert any("espresso" in kw["phrase"] for kw in result)


def test_resolve_keyword_data_target_keywords_override_wins_even_when_disabled():
    page_meta_entry = {"title": "Espresso Machines", "h1": "Best Espresso Machines", "heading_hierarchy": []}
    content_stats = {"text": "espresso machine reviews and buying guide"}

    result = audit_service._resolve_keyword_data(
        target_keywords=["custom keyword"],
        enable_keyword_analysis=False,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert result == [{"phrase": "custom keyword", "score": None, "found_in": []}]
