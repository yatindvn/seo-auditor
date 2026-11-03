"""Every issue the audit can raise comes with advice, not "Review and resolve: CODE"."""

import re
from pathlib import Path
from types import SimpleNamespace

from app.ai.ai_suggestions import generate_recommendations, recommendation_text
from app.auditor import checks

APP = Path(__file__).resolve().parents[1] / "app"
HAS_OWN_TEXT = {"ORPHAN_PAGES"}          # built with its text in generate_recommendations


def _literal_codes():
    codes = set()
    for f in APP.rglob("*.py"):
        s = f.read_text(encoding="utf-8")
        codes |= set(re.findall(r'issue\(\s*[a-z_"]+\s*,\s*"([A-Z0-9_]+)"', s))
        codes |= set(re.findall(r'"code":\s*"([A-Z][A-Z0-9_]+)"', s))
    return codes - HAS_OWN_TEXT


def _built_codes():
    # Codes made from lists inside the checks (Open Graph tags, security headers).
    page = SimpleNamespace(html="<html><head></head><body></body></html>", headers={"server": "x"})
    return {i["code"] for i in checks.check_open_graph_twitter(page) + checks.check_security_headers(page)}


def test_every_issue_code_has_advice():
    codes = _literal_codes() | _built_codes()
    assert len(codes) > 60
    assert sorted(c for c in codes if not recommendation_text(c)) == []


def test_unknown_codes_fall_back_to_the_issue_message():
    recs = generate_recommendations({"https://a.com/": [
        {"severity": "warning", "code": "CUSTOM_3", "message": "Product pages need a price"}]}, {})
    assert recs[0]["recommendation"] == "Product pages need a price"
    assert "Review and resolve" not in str(recs)
