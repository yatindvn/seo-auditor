"""Turning a top result into facts: outline, schema, counts, failures."""

from app.content_explorer.pages import DryRunPages, empty_row, fetch_results, page_facts, schema_types
from app.crawler.crawler import PageResult
from app.providers.serp import SerpItem

HTML = """<html><head><title>Rare Books Guide</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Article"},{"@type":["BreadcrumbList","Article"]}]}</script>
<script type="application/ld+json">[{"@type":"FAQPage"}]</script>
<script type="application/ld+json">{not json</script>
</head><body><h1>Rare books</h1><h2>What makes a book rare</h2><h3>First editions</h3><h2>Where to buy</h2>
<p>""" + "Collectors look for condition and provenance. " * 40 + """</p>
<img src="a.png" alt="a"><a href="/more">more</a><a href="https://other.org/">other</a></body></html>"""

ITEM = SerpItem(1, "https://books.example.com/rare", "books.example.com", "SERP title")


def test_schema_types_walk_graphs_and_lists_and_skip_bad_json():
    blocks = [{"type": "JSON-LD", "raw": '{"@graph":[{"@type":"Article"},{"@type":["BreadcrumbList","Article"]}]}'},
              {"type": "JSON-LD", "raw": '[{"@type":"FAQPage"}]'}, {"type": "JSON-LD", "raw": "{bad"}]
    assert schema_types(blocks) == ["Article", "BreadcrumbList", "FAQPage"]
    assert schema_types(None) == []


def test_facts_from_a_fetched_page():
    row = page_facts(ITEM, PageResult(url=ITEM.url, final_url=ITEM.url, status_code=200, html=HTML,
                                      headers={"content-type": "text/html"}))
    assert row["title"] == "Rare Books Guide" and row["h1"] == "Rare books" and row["status"] == 200
    assert row["outline"] == [{"level": 2, "text": "What makes a book rare"}, {"level": 3, "text": "First editions"},
                              {"level": 2, "text": "Where to buy"}]
    assert row["schema_types"] == ["Article", "BreadcrumbList", "FAQPage"]
    assert row["word_count"] > 200 and row["images"] == 1 and row["internal_links"] == 1 and row["external_links"] == 1
    assert isinstance(row["readability"], float) and isinstance(row["issues"], int) and row["error"] is None
    assert row["backlinks"] is None and row["referring_domains"] is None


def test_failures_keep_serp_fields():
    blocked = page_facts(ITEM, PageResult(url=ITEM.url, final_url=ITEM.url, status_code=403, html="<p>no</p>"))
    assert blocked["error"] == "HTTP 403" and blocked["status"] == 403 and blocked["word_count"] is None
    assert blocked["title"] == "SERP title" and blocked["outline"] == []
    down = page_facts(ITEM, PageResult(url=ITEM.url, final_url=ITEM.url, status_code=None, error="ConnectTimeout"))
    assert down["error"] == "ConnectTimeout"


def test_fetch_results_keeps_order_and_survives_exceptions():
    items = [ITEM, SerpItem(2, "https://boom.example/", "boom.example", "Boom")]

    def fetch(url):
        if "boom" in url:
            raise RuntimeError("x")
        return PageResult(url=url, final_url=url, status_code=200, html=HTML)

    rows = fetch_results(items, fetch=fetch)
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[1]["error"] == "fetch failed (RuntimeError)" and rows[0]["h1"] == "Rare books"


def test_dry_run_pages_are_stable_and_varied():
    items = [SerpItem(i, f"https://site{i}.example/rare-books", f"site{i}.example", f"rare books #{i}") for i in range(1, 11)]
    a = DryRunPages().results(items, "rare books")
    assert a == DryRunPages().results(items, "rare books")
    assert len(a) == 10 and any(r["schema_types"] for r in a)
    assert all(r["outline"] and "rare books" in r["outline"][0]["text"] for r in a if r["error"] is None)
    assert empty_row(items[0])["position"] == 1
