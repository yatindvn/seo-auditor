"""Loading a project's rules for an audit."""

from app.db.engine import get_session_factory
from app.db.models import CustomRule, Project
from app.rules import store


def _seed():
    with get_session_factory().begin() as s:
        project = Project(name="shop.com", domain="shop.com"); s.add(project); s.flush()
        s.add_all([
            CustomRule(project_id=project.id, name="b", severity="info", message="", url_pattern=None,
                       check_json={"type": "field", "field": "title", "op": "is_empty"}),
            CustomRule(project_id=project.id, name="off", enabled=False, severity="info", message="",
                       check_json={"type": "field", "field": "h1", "op": "is_empty"}),
            CustomRule(project_id=project.id, name="a", severity="critical", message="m", url_pattern="/p/*",
                       check_json={"type": "selector", "selector": "h1", "op": "exists"}),
        ])


def test_loads_enabled_rules_for_the_audited_site_in_id_order():
    _seed()
    rules = store.load_enabled_rules("https://www.shop.com/start")
    assert [r["name"] for r in rules] == ["b", "a"]
    assert rules[1] == {"id": rules[1]["id"], "name": "a", "severity": "critical", "message": "m",
                        "url_pattern": "/p/*", "check": {"type": "selector", "selector": "h1", "op": "exists"}}


def test_no_project_means_no_rules():
    assert store.load_enabled_rules("https://unknown.example/") == []


def test_a_database_failure_means_no_rules():
    def broken():
        raise RuntimeError("db down")
    assert store.load_enabled_rules("https://shop.com/", factory=broken) == []
