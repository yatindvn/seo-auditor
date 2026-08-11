from app.utils.report import build_executive_summary


class FakeCrawler:
    def __init__(self):
        self.results = {}
        self.start_url = "https://example.com"
        self.robots_txt_content = "User-agent: *\nDisallow: /admin"
        self.sitemaps_found = ["https://example.com/sitemap.xml"]
        self.sitemap_urls = {"https://example.com/", "https://example.com/about"}


def _build_summary(crawler):
    return build_executive_summary(
        crawler,
        all_page_issues={},
        site_wide={},
        duplicates={},
        redirects={},
        broken_links=[],
        recommendations=[],
    )


def test_executive_summary_includes_robots_txt_content():
    crawler = FakeCrawler()

    summary = _build_summary(crawler)

    assert summary["robots_txt_content"] == crawler.robots_txt_content


def test_executive_summary_includes_sitemap_urls():
    crawler = FakeCrawler()

    summary = _build_summary(crawler)

    assert set(summary["sitemap_urls"]) == crawler.sitemap_urls


def test_page_level_report_passes_through_keyword_analysis():
    class FakePage:
        def __init__(self):
            self.status_code = 200
            self.depth = 0
            self.response_time_ms = 100
            self.redirect_chain = []
            self.headers = {}
            self.html = "<html></html>"

    crawler = FakeCrawler()
    crawler.results = {"https://example.com/": FakePage()}

    page_meta = {
        "https://example.com/": {
            "keyword_analysis": {
                "top_keywords": [{"phrase": "espresso machine", "score": 3.0, "found_in": ["title"]}],
                "rankings": [],
                "suggested_keywords": [],
            },
        }
    }

    from app.utils.report import build_page_level_report
    rows = build_page_level_report(crawler, {"https://example.com/": []}, page_meta)

    assert rows[0]["keyword_analysis"]["top_keywords"][0]["phrase"] == "espresso machine"
