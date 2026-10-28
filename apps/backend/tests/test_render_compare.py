"""Raw vs rendered: what changed, and which changes are issues."""

from app.rendering.compare import analyze_rendered, compare, rendering_issues
from app.rendering.model import RenderComparison
from app.services.page_pipeline import HtmlAnalysis


def _part(words=50, links=(), **meta):
    base = {"title": "Shop", "meta_description": "Buy", "canonical": "https://a.com/",
            "meta_robots": None, "h1": "Shop", "word_count": words}
    return HtmlAnalysis(meta={**base, **meta}, internal_links=list(links))


def test_no_changes_means_no_issues():
    c = compare("https://a.com/", _part(), _part())
    assert c.changes == {} and c.js_only_links == [] and rendering_issues(c) == []


def test_none_and_empty_string_and_whitespace_are_the_same():
    c = compare("https://a.com/", _part(meta_robots=None, title="Shop "), _part(meta_robots="", title="Shop"))
    assert c.changes == {}


def test_each_changed_field_is_recorded_and_raises_its_issue():
    raw = _part(title="Loading…", canonical="https://a.com/", meta_robots=None, meta_description=None, h1=None)
    rendered = _part(title="Espresso machines", canonical="https://a.com/espresso",
                     meta_robots="noindex", meta_description="Best machines", h1="Espresso")
    c = compare("https://a.com/", raw, rendered)
    assert c.changes["title"] == {"raw": "Loading…", "rendered": "Espresso machines"}
    assert set(c.changes) == {"title", "canonical", "meta_robots", "meta_description", "h1"}
    issues = {i["code"]: i for i in rendering_issues(c)}
    assert {k: v["severity"] for k, v in issues.items()} == {
        "JS_TITLE_CHANGED": "warning", "JS_CANONICAL_CHANGED": "warning", "JS_ROBOTS_CHANGED": "warning",
        "JS_META_DESCRIPTION_CHANGED": "info", "JS_H1_CHANGED": "info"}
    assert issues["JS_TITLE_CHANGED"]["message"] == "Title changed by JavaScript: 'Loading…' → 'Espresso machines'"
    assert issues["JS_META_DESCRIPTION_CHANGED"]["message"] == "Meta description changed by JavaScript: (none) → 'Best machines'"


def test_content_dependence_needs_double_and_two_hundred_more_words():
    assert "JS_CONTENT_DEPENDENT" in [i["code"] for i in rendering_issues(compare("u", _part(words=40), _part(words=900)))]
    assert "JS_CONTENT_DEPENDENT" not in [i["code"] for i in rendering_issues(compare("u", _part(words=40), _part(words=230)))]   # +190
    assert "JS_CONTENT_DEPENDENT" not in [i["code"] for i in rendering_issues(compare("u", _part(words=300), _part(words=599)))]  # < 2x
    issue = [i for i in rendering_issues(compare("u", _part(words=40), _part(words=900))) if i["code"] == "JS_CONTENT_DEPENDENT"][0]
    assert issue == {"severity": "warning", "code": "JS_CONTENT_DEPENDENT",
                     "message": "40 words in raw HTML, 900 after JavaScript"}


def test_js_only_links_are_sorted_capped_and_counted():
    rendered_links = [f"https://a.com/p{i:03d}" for i in range(60)] + ["https://a.com/raw"]
    c = compare("u", _part(links=["https://a.com/raw"]), _part(links=rendered_links))
    assert c.js_only_links_count == 60 and len(c.js_only_links) == 50 and c.js_only_links[0] == "https://a.com/p000"
    assert [i for i in rendering_issues(c) if i["code"] == "JS_ONLY_LINKS"][0]["message"] == \
        "60 internal links appear only after JavaScript"


def test_a_failed_render_raises_nothing():
    assert rendering_issues(RenderComparison(url="u", status="failed", error="Timeout")) == []


def test_analyze_rendered_parses_like_the_crawler():
    html = "<html><head><title>JS Title</title><link rel='canonical' href='https://a.com/x'></head>" \
           "<body><h1>Hello</h1><a href='/next'>n</a></body></html>"
    part = analyze_rendered("https://a.com/", "https://a.com/", html)
    assert part.meta["title"] == "JS Title" and part.meta["h1"] == "Hello"
    assert "https://a.com/next" in part.internal_links


def test_to_dict_is_json_ready():
    d = compare("u", _part(), _part(title="New"), render_ms=812.5).to_dict()
    assert d["url"] == "u" and d["status"] == "rendered" and d["render_ms"] == 812.5
    assert d["changes"] == {"title": {"raw": "Shop", "rendered": "New"}}
