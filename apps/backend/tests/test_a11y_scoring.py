"""axe results → a page's accessibility score, violations and issues."""

from app.accessibility.model import A11yResult
from app.accessibility.scoring import a11y_issues, summarize
from app.ai import ai_suggestions


def _v(rule, impact, n=1, **over):
    return {"id": rule, "impact": impact, "help": f"Help for {rule}",
            "helpUrl": f"https://dequeuniversity.com/rules/axe/4.14/{rule}",
            "tags": ["cat.color", "wcag2aa", "wcag143", "EN-301-549"],
            "nodes": [{"target": [f"#el{i}"]} for i in range(n)], **over}


RAW = {"violations": [_v("region", "moderate"), _v("color-contrast", "serious", 12),
                      _v("image-alt", "critical", 2), _v("aria-allowed-attr", "critical"),
                      _v("landmark-one-main", None)]}


def test_summary_sorts_counts_and_scores():
    r = summarize("https://a.com/", RAW)
    assert [v["id"] for v in r.violations] == ["aria-allowed-attr", "image-alt", "color-contrast", "region", "landmark-one-main"]
    assert r.counts == {"critical": 2, "serious": 1, "moderate": 1, "minor": 1}
    assert r.score == 100 - 10 - 10 - 7 - 3 - 1
    cc = [v for v in r.violations if v["id"] == "color-contrast"][0]
    assert cc == {"id": "color-contrast", "impact": "serious", "help": "Help for color-contrast",
                  "help_url": "https://dequeuniversity.com/rules/axe/4.14/color-contrast",
                  "wcag": ["wcag2aa", "wcag143"], "nodes_count": 12,
                  "targets": ["#el0", "#el1", "#el2", "#el3", "#el4"]}


def test_score_floors_at_zero():
    raw = {"violations": [_v(f"rule-{i}", "critical") for i in range(15)]}
    assert summarize("u", raw).score == 0


def test_no_violations_is_a_perfect_score():
    r = summarize("u", {"violations": []})
    assert (r.score, r.violations, r.counts["critical"]) == (100, [], 0)


def test_nested_targets_are_joined_and_page_data_is_distrusted():
    raw = {"violations": [_v("button-name", "evil-impact", helpUrl="javascript:alert(1)",
                             help="x" * 1000, nodes=[{"target": [["iframe#f", "#inner"]]}, {"target": ["#" + "a" * 500]}])]}
    v = summarize("u", raw).violations[0]
    assert v["impact"] == "minor" and v["help_url"] is None and len(v["help"]) == 300
    assert v["targets"][0] == "iframe#f #inner" and len(v["targets"][1]) == 200


def test_issues_are_damped_and_skip_rules_raw_checks_cover():
    issues = {i["code"]: i for i in a11y_issues(summarize("u", RAW))}
    assert "A11Y_IMAGE_ALT" not in issues
    assert issues["A11Y_COLOR_CONTRAST"] == {"severity": "warning", "code": "A11Y_COLOR_CONTRAST",
                                             "message": "Help for color-contrast (12 elements, serious)",
                                             "source": "axe"}
    assert issues["A11Y_ARIA_ALLOWED_ATTR"]["severity"] == "warning"
    assert issues["A11Y_REGION"]["severity"] == "info"
    assert issues["A11Y_REGION"]["message"] == "Help for region (1 element, moderate)"
    assert issues["A11Y_LANDMARK_ONE_MAIN"]["severity"] == "info"


def test_a_failed_scan_raises_nothing():
    assert a11y_issues(A11yResult(url="u", status="failed", error="boom")) == []


def test_to_dict():
    d = summarize("u", RAW).to_dict()
    assert d["url"] == "u" and d["status"] == "scanned" and d["error"] is None and len(d["violations"]) == 5


def test_accessibility_codes_get_a_real_recommendation():
    recs = ai_suggestions.generate_recommendations(
        {"https://a.com/": [{"severity": "warning", "code": "A11Y_COLOR_CONTRAST", "message": "m"}]}, {})
    rec = [r for r in recs if r["code"] == "A11Y_COLOR_CONTRAST"][0]
    assert rec["recommendation"].startswith("Fix this accessibility problem")
    assert ai_suggestions.recommendation_text("MISSING_TITLE") == ai_suggestions.RECOMMENDATION_TEXT["MISSING_TITLE"]
    assert ai_suggestions.recommendation_text("SOMETHING_ELSE") is None


def test_axe_findings_nudge_the_health_score_rather_than_dominate_it():
    """They stay warnings, and the Accessibility category feels them in full,
    but the overall score counts them like info -- the owner's call."""
    from app.utils.report import compute_health_score

    axe = {"severity": "warning", "code": "A11Y_COLOR_CONTRAST", "message": "m", "source": "axe"}
    info = {"severity": "info", "code": "A11Y_COLOR_CONTRAST", "message": "m"}
    raw = {"severity": "warning", "code": "A11Y_IMG_NO_ALT_ATTR", "message": "m"}
    with_axe = compute_health_score({"u": [axe]}, 1)
    assert with_axe["score"] == compute_health_score({"u": [info]}, 1)["score"]
    assert with_axe["warning_issues"] == 1
    assert with_axe["categories"]["accessibility"] < compute_health_score({"u": [info]}, 1)["categories"]["accessibility"]
    assert compute_health_score({"u": [raw]}, 1)["score"] < with_axe["score"]
