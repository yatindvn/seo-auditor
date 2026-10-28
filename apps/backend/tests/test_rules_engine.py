"""Custom rules: validation, evaluation, description and summary."""

import pytest
from bs4 import BeautifulSoup

from app.rules.engine import PageFacts, applies, describe, evaluate, observe, passes, phase_of, rules_digest, summarize
from app.rules.schema import RuleError, validate_rule

HTML = ("<html><head><title> Shop | Brand </title></head><body><nav class='breadcrumb'></nav>"
        "<p class='price_color'>£10</p><p class='price_color'>£12</p>"
        "<script type='application/ld+json'>{}</script></body></html>")


def _facts(**over):
    base = dict(url="https://a.com/products/x", html=HTML, soup=BeautifulSoup(HTML, "html.parser"),
                text="Shop now. Free shipping on everything.",
                meta={"title": " Shop | Brand ", "meta_description": None, "h1": "Shop", "word_count": 120,
                      "canonical": "https://a.com/products/x", "meta_robots": "index,follow",
                      "internal_links_count": 30, "external_links_count": 2},
                status=200, response_time_ms=850.0)
    base.update(over)
    return PageFacts(**base)


def _rule(check, rid=1, **over):
    return {"id": rid, "name": "My rule", "severity": "warning", "message": "fix it",
            "url_pattern": None, "check": check, **over}


@pytest.mark.parametrize("op, value, expected", [
    ("equals", "Shop | Brand", True), ("equals", "shop | brand", False), ("not_equals", "Other", True),
    ("contains", "| BRAND", True), ("not_contains", "brand", False), ("starts_with", "shop", True),
    ("ends_with", "brand", True), ("is_empty", None, False), ("is_not_empty", None, True),
    ("length_gte", 12, True), ("length_lte", 11, False),
])
def test_text_field_ops(op, value, expected):
    assert passes({"type": "field", "field": "title", "op": op, "value": value}, _facts()) is expected


def test_missing_text_field_is_empty():
    assert passes({"type": "field", "field": "meta_description", "op": "is_empty"}, _facts()) is True
    assert passes({"type": "field", "field": "meta_description", "op": "contains", "value": "x"}, _facts()) is False


@pytest.mark.parametrize("field, op, value, expected", [
    ("word_count", "gte", 300, False), ("word_count", "lte", 120, True), ("word_count", "eq", 120, True),
    ("internal_links_count", "gte", 10, True), ("status", "eq", 200, True), ("response_time_ms", "lte", 500, False),
])
def test_number_field_ops(field, op, value, expected):
    assert passes({"type": "field", "field": field, "op": op, "value": value}, _facts()) is expected


def test_text_checks():
    assert passes({"type": "text", "scope": "visible", "op": "contains", "value": "FREE SHIPPING"}, _facts()) is True
    assert passes({"type": "text", "scope": "visible", "op": "contains", "value": "FREE SHIPPING",
                   "case_sensitive": True}, _facts()) is False
    assert passes({"type": "text", "scope": "html", "op": "contains", "value": "ld+json"}, _facts()) is True
    assert passes({"type": "text", "scope": "visible", "op": "not_contains", "value": "lorem ipsum"}, _facts()) is True


def test_selector_checks_and_observe():
    sel = lambda op, value=None: {"type": "selector", "selector": ".price_color", "op": op, "value": value}
    assert passes(sel("exists"), _facts()) and not passes(sel("not_exists"), _facts())
    assert passes(sel("count_eq", 2), _facts()) and passes(sel("count_lte", 2), _facts())
    assert not passes(sel("count_gte", 3), _facts())
    assert observe(sel("exists"), _facts()) == 2
    assert observe({"type": "field", "field": "title", "op": "is_empty"}, _facts()) == "Shop | Brand"
    assert observe({"type": "text", "scope": "visible", "op": "contains", "value": "shipping"}, _facts()) is True


def test_url_pattern_scopes_rules():
    assert applies(_rule({}, url_pattern="/products/*"), "https://a.com/products/x?y=1")
    assert not applies(_rule({}, url_pattern="/blog/*"), "https://a.com/products/x")
    assert applies(_rule({}, url_pattern=None), "https://a.com/anything")


def test_phases():
    assert phase_of({"type": "field", "field": "status", "op": "eq", "value": 200}) == "response"
    assert phase_of({"type": "field", "field": "title", "op": "is_empty"}) == "html"
    assert phase_of({"type": "selector", "selector": "a", "op": "exists"}) == "html"


def test_evaluate_returns_issues_and_checked_ids():
    rules = [_rule({"type": "field", "field": "word_count", "op": "gte", "value": 300}, rid=7, severity="critical"),
             _rule({"type": "selector", "selector": "nav.breadcrumb", "op": "exists"}, rid=8),
             _rule({"type": "field", "field": "title", "op": "is_empty"}, rid=9, url_pattern="/blog/*"),
             _rule({"type": "field", "field": "status", "op": "eq", "value": 404}, rid=10)]
    issues, checked = evaluate(rules, _facts(), "html")
    assert checked == [7, 8]
    assert issues == [{"severity": "critical", "code": "CUSTOM_7", "message": "My rule: fix it",
                       "rule_id": 7, "source": "custom"}]
    issues, checked = evaluate(rules, _facts(), "response")
    assert checked == [10] and issues[0]["code"] == "CUSTOM_10"


def test_html_rules_skip_pages_without_html_and_bad_rules_are_skipped():
    rule = _rule({"type": "field", "field": "title", "op": "is_not_empty"})
    assert evaluate([rule], _facts(html="", soup=None), "html") == ([], [])
    broken = _rule({"type": "selector", "selector": "a", "op": "count_eq", "value": "not-a-number"}, rid=3)
    assert evaluate([broken], _facts(), "html") == ([], [])


def test_empty_message_falls_back_to_the_description():
    issues, _ = evaluate([_rule({"type": "field", "field": "word_count", "op": "gte", "value": 300}, message="")],
                         _facts(), "html")
    assert issues[0]["message"] == "My rule: Word count ≥ 300"


@pytest.mark.parametrize("check, text", [
    ({"type": "field", "field": "title", "op": "contains", "value": "| Brand"}, "Title contains '| Brand'"),
    ({"type": "field", "field": "meta_description", "op": "is_empty"}, "Meta description is empty"),
    ({"type": "field", "field": "word_count", "op": "gte", "value": 300}, "Word count ≥ 300"),
    ({"type": "field", "field": "title", "op": "length_lte", "value": 60}, "Title length ≤ 60"),
    ({"type": "text", "scope": "visible", "op": "not_contains", "value": "lorem"}, "Page text doesn't contain 'lorem'"),
    ({"type": "text", "scope": "html", "op": "contains", "value": "gtag("}, "HTML contains 'gtag('"),
    ({"type": "selector", "selector": "h1", "op": "count_eq", "value": 1}, "Exactly 1 × h1"),
    ({"type": "selector", "selector": ".x", "op": "not_exists"}, "No .x"),
    ({"type": "selector", "selector": ".x", "op": "exists"}, "Has .x"),
])
def test_describe(check, text):
    assert describe(check) == text


def test_digest_covers_only_html_rules_and_is_order_stable():
    a = _rule({"type": "field", "field": "title", "op": "is_empty"}, rid=1)
    b = _rule({"type": "field", "field": "status", "op": "eq", "value": 200}, rid=2)
    assert rules_digest([a, b]) == rules_digest([a]) == rules_digest([dict(reversed(list(a.items())))])
    assert rules_digest([a]) != rules_digest([{**a, "check": {**a["check"], "op": "is_not_empty"}}])
    assert rules_digest([]) == ""


def test_summarize_counts_checked_and_failed_pages():
    rule = _rule({"type": "field", "field": "title", "op": "is_empty"}, rid=5)
    checked = {"https://a.com/1": [5], "https://a.com/2": [5], "https://a.com/3": []}
    issues = {"https://a.com/2": [{"code": "CUSTOM_5", "rule_id": 5, "source": "custom", "severity": "warning", "message": "m"}]}
    assert summarize([rule], checked, issues) == [{
        "rule_id": 5, "name": "My rule", "severity": "warning", "description": "Title is empty",
        "pages_checked": 2, "pages_failed": 1, "example_urls": ["https://a.com/2"]}]


def test_validation_accepts_good_rules_and_normalises_numbers():
    rule = validate_rule({"name": "Long enough", "severity": "info",
                          "check": {"type": "field", "field": "word_count", "op": "gte", "value": "300"}})
    assert rule["check"]["value"] == 300 and rule["enabled"] is True and rule["url_pattern"] is None


@pytest.mark.parametrize("check, needle", [
    ({"type": "field", "field": "word_count", "op": "contains", "value": "x"}, "not valid for word_count"),
    ({"type": "field", "field": "title", "op": "contains"}, "needs a value"),
    ({"type": "field", "field": "title", "op": "length_gte", "value": "abc"}, "must be a whole number"),
    ({"type": "field", "field": "word_count", "op": "gte", "value": -1}, "must be ≥ 0"),
    ({"type": "selector", "selector": "div[", "op": "exists"}, "Invalid CSS selector"),
    ({"type": "selector", "selector": "div", "op": "count_eq"}, "needs a value"),
    ({"type": "text", "scope": "visible", "op": "contains", "value": "x" * 201}, "at most 200"),
    ({"type": "headers", "name": "X"}, "check"),
])
def test_validation_rejects_bad_rules(check, needle):
    with pytest.raises(RuleError) as err:
        validate_rule({"name": "r", "check": check})
    assert needle in str(err.value)


def test_validation_limits_names():
    with pytest.raises(RuleError):
        validate_rule({"name": "x" * 81, "check": {"type": "field", "field": "title", "op": "is_empty"}})
