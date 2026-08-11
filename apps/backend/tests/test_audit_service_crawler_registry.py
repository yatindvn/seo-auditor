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
